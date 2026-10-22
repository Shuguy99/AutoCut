"""FastAPI-приложение: REST API, SSE-прогресс и отдача результатов."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from ..config import Config, load_config
from ..downloader import (
    MEDIA_SUFFIXES,
    DownloadError,
    NotAPlaylistError,
    list_playlist,
)
from ..feed import FeedError, fetch_feed
from ..jobs import Job, JobManager, QueueFullError
from ..models import JobOptions
from ..storage import slugify

STATIC_DIR = Path(__file__).parent / "static"

# Некоторые системы сопоставляют .ass с audio/aac — отдаём субтитры как текст.
TEXT_MEDIA_TYPES = {
    ".ass": "text/plain; charset=utf-8",
    ".srt": "text/plain; charset=utf-8",
}

MAX_BATCH = 20
MAX_UPLOAD_BYTES = 4 * 1024**3


def _clean_source(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("источник не может быть пустым")
    return value


class CreateJobRequest(BaseModel):
    source: str = Field(min_length=1)
    options: JobOptions = Field(default_factory=JobOptions)

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        return _clean_source(value)


class BatchJobRequest(BaseModel):
    sources: list[str] = Field(min_length=1)
    options: JobOptions = Field(default_factory=JobOptions)

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, values: list[str]) -> list[str]:
        cleaned = [_clean_source(value) for value in values if value.strip()]
        if not cleaned:
            raise ValueError("нужен хотя бы один источник")
        if len(cleaned) > MAX_BATCH:
            raise ValueError(f"за один раз можно запустить не более {MAX_BATCH} видео")
        return cleaned


class PlaylistRequest(BaseModel):
    url: str = Field(min_length=1)
    limit: int = Field(30, ge=1, le=50)
    proxy: str | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return _clean_source(value)


def _job_payload(job: Job, config: Config) -> dict:
    """Добавляет к задаче URL файлов результата относительно output_dir."""
    data = job.to_dict()
    root = Path(config.output_dir).expanduser().resolve()

    def url(value: str | None) -> str | None:
        if not value:
            return None
        try:
            rel = Path(value).resolve().relative_to(root)
        except ValueError:
            return None
        return "/files/" + quote(rel.as_posix())

    if data["result"]:
        clips = []
        for clip in data["result"].get("clips", []):
            item = dict(clip)
            item["file_url"] = url(clip.get("file"))
            item["preview_url"] = url(clip.get("preview"))
            item["subtitle_url"] = url(clip.get("subtitle"))
            item["publish_url"] = url(clip.get("publish_file"))
            clips.append(item)
        data["result"] = {**data["result"], "clips": clips}
        folder = data["result"].get("result_dir")
        data["result"]["folder_url"] = (
            url(str(Path(folder) / "metadata.json")) if folder else None
        )
    return data


def create_app(
    config: Config | None = None, manager: JobManager | None = None
) -> FastAPI:
    """Создаёт приложение; ``manager`` можно подменить в тестах."""
    config = config or load_config()
    owns_manager = manager is None
    manager = manager or JobManager(config, max_queue=MAX_BATCH)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if owns_manager:
            manager.shutdown()

    app = FastAPI(title="AutoCut", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/health")
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/feed")
    def get_feed(
        offset: int = Query(0, ge=0),
        limit: int = Query(12, ge=1, le=24),
    ) -> dict:
        try:
            page = fetch_feed(offset=offset, limit=limit)
        except FeedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "items": page.items,
            "next_offset": page.next_offset,
            "has_more": page.has_more,
        }

    @app.post("/api/playlist")
    def playlist(request: PlaylistRequest) -> dict:
        try:
            info = list_playlist(
                request.url,
                limit=request.limit,
                proxy=request.proxy or config.proxy,
                cookies=str(config.cookies) if config.cookies else None,
            )
        except NotAPlaylistError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DownloadError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "title": info.title,
            "items": [asdict(item) for item in info.items],
            "truncated": info.truncated,
        }

    @app.post("/api/upload")
    async def upload_video(file: UploadFile = File(...)) -> dict:
        """Принимает локальный видеофайл в work/uploads и возвращает путь."""
        name = Path(file.filename or "video.mp4").name
        suffix = Path(name).suffix.lower()
        if suffix not in MEDIA_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"неподдерживаемый формат: {suffix or 'без расширения'}",
            )
        upload_dir = Path(config.work_dir).expanduser() / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        stem = slugify(Path(name).stem, max_len=40) or "video"
        target = upload_dir / f"{uuid.uuid4().hex[:12]}_{stem}{suffix}"
        size = 0
        try:
            with target.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="файл больше 4 ГБ",
                        )
                    output.write(chunk)
            if size == 0:
                raise HTTPException(status_code=400, detail="пустой файл")
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {
            "path": str(target.resolve()),
            "name": name,
            "size": size,
        }

    @app.post("/api/jobs")
    def create_job(request: CreateJobRequest) -> dict:
        try:
            job = manager.submit(request.source, request.options)
        except QueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return _job_payload(job, config)

    @app.post("/api/jobs/batch")
    def create_jobs(request: BatchJobRequest) -> dict:
        try:
            jobs = manager.submit_many(request.sources, request.options)
        except QueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return {"jobs": [_job_payload(job, config) for job in jobs]}

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return [_job_payload(job, config) for job in manager.list()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job не найден")
        return _job_payload(job, config)

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str) -> dict:
        if not manager.cancel(job_id):
            raise HTTPException(
                status_code=404, detail="job не найден или завершён"
            )
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/events")
    def events(job_id: str) -> StreamingResponse:
        async def stream():
            last = None
            ticks = 0
            while True:
                job = manager.get(job_id)
                if job is None:
                    yield 'event: error\ndata: {"error":"job не найден"}\n\n'
                    return
                payload = json.dumps(
                    _job_payload(job, config), ensure_ascii=False
                )
                if payload != last:
                    yield f"data: {payload}\n\n"
                    last = payload
                if job.status in {"done", "failed", "cancelled"}:
                    return
                ticks += 1
                if ticks % 25 == 0:
                    yield ": ping\n\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/files/{path:path}")
    def serve_file(path: str) -> FileResponse:
        root = Path(config.output_dir).expanduser().resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="файл не найден")
        return FileResponse(
            target, media_type=TEXT_MEDIA_TYPES.get(target.suffix.lower())
        )

    return app
