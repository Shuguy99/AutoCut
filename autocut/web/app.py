from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import Config, load_config
from ..jobs import Job, JobManager, QueueFullError
from ..models import JobOptions

STATIC_DIR = Path(__file__).parent / "static"

# Некоторые системы сопоставляют .ass с audio/aac — отдаём субтитры как текст.
TEXT_MEDIA_TYPES = {
    ".ass": "text/plain; charset=utf-8",
    ".srt": "text/plain; charset=utf-8",
}


class CreateJobRequest(BaseModel):
    source: str = Field(min_length=1)
    options: JobOptions = Field(default_factory=JobOptions)


def _job_payload(job: Job, config: Config) -> dict:
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
    config = config or load_config()
    manager = manager or JobManager(config)
    app = FastAPI(title="AutoCut", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.post("/api/jobs")
    def create_job(request: CreateJobRequest) -> dict:
        try:
            job = manager.submit(request.source.strip(), request.options)
        except QueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return _job_payload(job, config)

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
