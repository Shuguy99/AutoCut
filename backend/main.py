from __future__ import annotations

import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import jobs
from config import (
    ALLOWED_EXTENSIONS,
    DATA_DIR,
    JOB_RETENTION_DAYS,
    KEEP_RECENT_JOBS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    WHISPER_MODEL,
)
from downloader import download_youtube
from ollama_resolver import _ollama_native, resolve_model
from pipeline import reprocess_pipeline, run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "backend.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger("autocut")


class JobOptions(BaseModel):
    min_score: Optional[int] = None
    max_clips: Optional[int] = None
    clip_min_sec: Optional[float] = None
    clip_max_sec: Optional[float] = None
    burn_subtitles: Optional[bool] = None
    aspect: Optional[str] = None
    language: Optional[str] = None
    reuse_transcript: Optional[bool] = None


class DownloadRequest(BaseModel):
    url: str
    options: Optional[JobOptions] = None


def _opts(options: JobOptions | None) -> dict:
    return options.model_dump(exclude_none=True) if options else {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs.load_persisted()
    jobs.cleanup_old_jobs(max_days=JOB_RETENTION_DAYS, keep=KEEP_RECENT_JOBS)
    yield


app = FastAPI(title="AutoCut", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    from cutter import ffmpeg_available
    import httpx
    ollama_ok = False
    ollama_models: list[str] = []
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(_ollama_native() + "/api/tags")
            r.raise_for_status()
            ollama_ok = True
            ollama_models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return {
        "ok": True,
        "version": app.version,
        "ffmpeg": ffmpeg_available(),
        "ollama": {
            "connected": ollama_ok,
            "base_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "resolved_model": resolve_model() if ollama_ok else None,
            "models": ollama_models,
        },
        "whisper_model": WHISPER_MODEL,
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый формат: {suffix}")
    job_id = jobs.create_job(file.filename or "video.mp4")
    dest = Path(jobs.get_job(job_id)["video_path"])
    try:
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        await file.close()
    jobs.update(job_id, status="ready")
    return {"job_id": job_id, "status": "ready"}


@app.post("/api/process/{job_id}")
def process(job_id: str, options: JobOptions | None = None) -> dict:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Джоб не найден")
    opts = _opts(options)
    reuse = bool(opts.get("reuse_transcript"))
    if job["status"] == "processing":
        raise HTTPException(status_code=409, detail="Джоб уже обрабатывается")
    if reuse:
        jobs.update(job_id, status="processing", stage="score", progress=30)
        jobs.run_background(job_id, lambda j: reprocess_pipeline(j, opts))
    else:
        jobs.update(job_id, status="processing", stage="transcribe", progress=5)
        jobs.run_background(job_id, lambda j: run_pipeline(j, opts))
    return jobs.public(job_id)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    state = jobs.cancel(job_id)
    if state == "notfound":
        raise HTTPException(status_code=404, detail="Джоб не найден")
    if state == "terminal":
        raise HTTPException(status_code=409, detail="Джоб уже завершён или отменён")
    return jobs.public(job_id)


@app.post("/api/download")
def download(req: DownloadRequest) -> dict:
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Некорректная ссылка")
    job_id = jobs.create_job("youtube.mp4")
    options = _opts(req.options)

    def _run(job: dict) -> None:
        jobs.update(job_id, status="processing", stage="download", progress=2, stage_detail="Загружаю видео с YouTube")
        try:
            download_youtube(
                url,
                job["video_path"],
                progress_cb=lambda f: (
                    jobs.raise_if_cancelled(job_id),
                    jobs.update(
                        job_id, progress=2 + int(f * 28),
                        stage_detail=f"Загружаю видео с YouTube: {int(f * 100)}%",
                    ),
                ),
            )
        except Exception:
            raise
        jobs.raise_if_cancelled(job_id)
        jobs.update(job_id, progress=30, stage_detail="Видеозапись скачана, запускаю обработку")
        run_pipeline(job, options)

    jobs.update(job_id, status="download", stage="download", progress=1)
    jobs.run_background(job_id, _run)
    return {"id": job_id, **jobs.public(job_id)}


@app.get("/api/jobs/{job_id}")
def status(job_id: str) -> dict:
    job = jobs.public(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Джоб не найден")
    return job


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str) -> StreamingResponse:
    """SSE: реальное время состояния джоба. Отдаёт прогресс и финальное состояние (done)."""

    async def gen():
        last: dict | None = None
        while True:
            snap = jobs.public(job_id)
            if not snap:
                yield "event: gone\ndata: {}\n\n"
                break
            if snap != last:
                last = snap
                if snap["status"] in ("completed", "error", "cancelled"):
                    yield f"event: done\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
            if snap["status"] in ("completed", "error", "cancelled"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"jobs": jobs.list_all()}


@app.get("/api/jobs/{job_id}/clips/{filename}")
def clip_file(job_id: str, filename: str) -> FileResponse:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Джоб не найден")
    base = Path(job["clips_dir"]).resolve()
    path = (base / filename).resolve()
    if not path.is_relative_to(base) or not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@app.get("/api/jobs/{job_id}/montage.mp4")
def montage_file(job_id: str) -> FileResponse:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Джоб не найден")
    path = Path(job["montage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Монтаж ещё не готов")
    return FileResponse(path, media_type="video/mp4", filename="highlights.mp4")


@app.get("/api/jobs/{job_id}/thumbs/{filename}")
def thumb_file(job_id: str, filename: str) -> FileResponse:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Джоб не найден")
    base = Path(job["clips_dir"]).resolve()
    path = (base / filename).resolve()
    if not path.is_relative_to(base) or not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path, media_type="image/jpeg")