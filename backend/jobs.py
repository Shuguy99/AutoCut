from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import JOBS_DIR, UPLOADS_DIR

log = logging.getLogger("autocut.jobs")

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_CANCELLED: set[str] = set()


class CancelledError(RuntimeError):
    """Поднимается пайплайном, когда джоб отменён пользователем."""


def cancel(job_id: str) -> str:
    """Запросить отмену. Вернёт 'ok' | 'notfound' | 'terminal'."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return "notfound"
        if job.get("status") not in ("processing", "download", "uploaded", "ready"):
            return "terminal"
        _CANCELLED.add(job_id)
        job["_event"].set()
    return "ok"


def is_cancelled(job_id: str) -> bool:
    with _LOCK:
        return job_id in _CANCELLED


def raise_if_cancelled(job_id: str) -> None:
    if is_cancelled(job_id):
        raise CancelledError("Джоб отменён")


def mark_cancelled(job_id: str) -> None:
    with _LOCK:
        _CANCELLED.discard(job_id)
        job = _JOBS.get(job_id)
        if job:
            job.update(status="cancelled", stage=None, progress=0, error=None)
            job["_event"].set()
    dump(job_id)
    # убрать частично нарезанные клипы/монтаж
    try:
        job_dir = JOBS_DIR / job_id
        clips_dir = job_dir / "clips"
        if clips_dir.exists():
            for p in clips_dir.iterdir():
                if p.is_file():
                    p.unlink(missing_ok=True)
        montage = job_dir / "highlights.mp4"
        montage.unlink(missing_ok=True)
    except OSError:
        pass


def create_job(original_name: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    job = {
        "id": job_id,
        "status": "uploaded",
        "stage": None,
        "progress": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_path": str(UPLOADS_DIR / f"{job_id}{Path(original_name).suffix.lower()}"),
        "transcript_path": str(job_dir / "transcript.json"),
        "clips_dir": str(job_dir / "clips"),
        "montage_path": str(job_dir / "highlights.mp4"),
        "result": None,
        "_event": threading.Event(),
    }
    Path(job["clips_dir"]).mkdir(exist_ok=True)
    with _LOCK:
        _JOBS[job_id] = job
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def update(job_id: str, **fields: Any) -> None:
    snapshot = False
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(fields)
            if job.get("status") in ("completed", "error"):
                snapshot = True
    if snapshot:
        dump(job_id)


def set_error(job_id: str, message: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(status="error", error=message)
            job["_event"].set()
    dump(job_id)


def run_background(job_id: str, fn: Callable[[dict[str, Any]], None]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise KeyError(f"Job {job_id} not found")
        job_snapshot = dict(job)
    job["_event"].clear()

    def _run() -> None:
        try:
            fn(job_snapshot)
        except CancelledError:
            log.info("job %s cancelled", job_id)
            mark_cancelled(job_id)
        except Exception as exc:
            log.exception("job %s crashed", job_id)
            traceback.print_exc()
            set_error(job_id, f"{type(exc).__name__}: {exc}")

    threading.Thread(target=_run, daemon=True).start()


def dump(job_id: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        doc = _export(job)
    path = Path(job["clips_dir"]).parent / "job.json"
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
    except OSError:
        log.warning("cannot persist job %s", job_id)


def load_persisted() -> None:
    to_dump: list[str] = []
    if not JOBS_DIR.exists():
        log.info("no jobs dir, nothing to restore")
        return
    with _LOCK:
        for job_dir in sorted(JOBS_DIR.iterdir()):
            if not job_dir.is_dir():
                continue
            meta = job_dir / "job.json"
            if meta.exists():
                try:
                    with open(meta, "r", encoding="utf-8") as fh:
                        doc = json.load(fh)
                except (OSError, json.JSONDecodeError):
                    continue
                job_id = doc.get("id") or job_dir.name
                _JOBS[job_id] = {
                    "id": job_id,
                    "status": doc.get("status", "error"),
                    "stage": doc.get("stage"),
                    "progress": doc.get("progress", 0),
                    "error": doc.get("error"),
                    "created_at": doc.get("created_at", ""),
                    "video_path": "",
                    "transcript_path": str(job_dir / "transcript.json"),
                    "clips_dir": str(job_dir / "clips"),
                    "montage_path": str(job_dir / "highlights.mp4"),
                    "result": doc.get("result"),
                    "_event": threading.Event(),
                }
            else:
                synth = _synthesize_job(job_dir)
                if not synth:
                    continue
                _JOBS[synth["id"]] = synth
                job_id = synth["id"]
                to_dump.append(job_id)
            # подставить путь загруженного видео рядом с job_dir, если известен по суффиксу файлов
            video = _find_uploaded_video(job_id, {})
            if video:
                _JOBS[job_id]["video_path"] = str(video)
    for job_id in to_dump:
        dump(job_id)
    log.info("restored %d persisted jobs", sum(1 for j in _JOBS.values() if j["status"] in ("completed", "error")))


def _synthesize_job(job_dir: Path) -> dict[str, Any] | None:
    """Восстановить джоб из артефактов на диске, когда job.json ещё не создавался."""
    montage_path = job_dir / "highlights.mp4"
    if not montage_path.exists():
        return None
    try:
        from cutter import probe_duration
    except Exception:
        def probe_duration(path: Path) -> float:
            return 0.0
    clips_dir = job_dir / "clips"
    clips = []
    for p in sorted(clips_dir.glob("clip_*.mp4")):
        thumb = p.with_suffix(".jpg")
        try:
            duration = probe_duration(p)
        except Exception:
            duration = 0.0
        clips.append(
            {
                "id": p.stem,
                "filename": p.name,
                "thumb": thumb.name if thumb.exists() else None,
                "title": f"Фрагмент {len(clips) + 1}",
                "reason": "",
                "start": None,
                "end": None,
                "score": None,
                "duration": duration,
            }
        )
    if not clips:
        return None
    try:
        montage_duration = probe_duration(montage_path)
    except Exception:
        montage_duration = 0.0
    job_id = job_dir.name
    result = {
        "montage_duration": montage_duration,
        "montage": {
            "file": f"/api/jobs/{job_id}/montage.mp4",
            "duration": montage_duration,
            "clip_count": len(clips),
        },
        "clips": [
            {
                "id": c["id"],
                "title": c["title"],
                "filename": c["filename"],
                "thumb": c["thumb"],
                "reason": c["reason"],
                "start": c["start"],
                "end": c["end"],
                "score": c["score"],
                "duration": c["duration"],
            }
            for c in clips
        ],
    }
    created = montage_path.stat().st_mtime
    return {
        "id": job_id,
        "status": "completed",
        "stage": "done",
        "progress": 100,
        "error": None,
        "created_at": datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
        "video_path": "",
        "transcript_path": str(job_dir / "transcript.json"),
        "clips_dir": str(clips_dir),
        "montage_path": str(montage_path),
        "result": result,
        "_event": threading.Event(),
    }


def _find_uploaded_video(job_id: str, doc: dict[str, Any]) -> Path | None:
    for suffix in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts"):
        p = UPLOADS_DIR / f"{job_id}{suffix}"
        if p.exists():
            return p
    return None


def _export(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result")
    upload_video = Path(job.get("video_path", "")).name if job.get("video_path") else ""
    exported = {
        k: v
        for k, v in job.items()
        if not k.startswith("_") and k not in ("video_path", "transcript_path", "clips_dir", "montage_path")
    }
    exported["video_filename"] = upload_video
    if result and isinstance(result, dict):
        ops = []
        for c in result.get("clips", []):
            raw_file = c.get("file")
            raw_thumb = c.get("thumb") or c.get("thumbnail")
            filen = c.get("filename") or (str(raw_file).rsplit("/", 1)[-1] if isinstance(raw_file, str) else "")
            file_url = raw_file if (isinstance(raw_file, str) and raw_file.startswith("/api/")) else f"/api/jobs/{job['id']}/clips/{filen}"
            thumb_url = (
                raw_thumb
                if (isinstance(raw_thumb, str) and raw_thumb.startswith("/api/"))
                else (f"/api/jobs/{job['id']}/thumbs/{raw_thumb}" if raw_thumb else None)
            )
            ops.append(
                {
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "start": c.get("start"),
                    "end": c.get("end"),
                    "score": c.get("score"),
                    "reason": c.get("reason"),
                    "duration": c.get("duration"),
                    "file": file_url,
                    "thumb": thumb_url,
                }
            )
        exported["result"] = {
            "clips": ops,
            "montage": {
                "file": f"/api/jobs/{job['id']}/montage.mp4",
                "duration": result.get("montage_duration"),
                "clip_count": len(result.get("clips", [])),
            },
        }
    return exported


def public(job_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return {}
        return _export(dict(job))


def list_all() -> list[dict[str, Any]]:
    with _LOCK:
        ids = sorted(_JOBS.keys(), key=lambda jid: _JOBS[jid].get("created_at", ""), reverse=True)
        jobs_snapshot = [dict(_JOBS[jid]) for jid in ids]
    items = []
    for job in jobs_snapshot:
        if job.get("status") in ("completed", "processing", "error"):
            items.append(_export(job))
    return items


def cleanup_old_jobs(max_days: float = 7.0, keep: int = 10) -> int:
    """Удаляет завершённые/упавшие джобы старше max_days, всегда оставляя последние `keep`.

    Возвращает число удалённых. Запускается при старте, безопасен для повторного вызова.
    """
    with _LOCK:
        items = sorted(
            _JOBS.items(),
            key=lambda kv: kv[1].get("created_at", ""),
            reverse=True,
        )
    now = time.time()
    removed = 0
    kept_count = 0
    for job_id, job in items:
        if job.get("status") not in ("completed", "error"):
            continue
        kept_count += 1
        if kept_count <= keep:
            continue
        created = str(job.get("created_at") or "")
        if not created:
            continue
        try:
            age_days = (now - datetime.fromisoformat(created).timestamp()) / 86400.0
        except ValueError:
            age_days = float("inf")
        if age_days <= max_days:
            continue
        _remove_job(job_id, job)
        removed += 1
    if removed:
        log.info("cleanup: removed %d old jobs", removed)
    return removed


def _remove_job(job_id: str, job: dict[str, Any]) -> None:
    with _LOCK:
        _JOBS.pop(job_id, None)
    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    upload = Path(str(job.get("video_path") or ""))
    if upload.name.startswith(job_id) and upload.exists():
        upload.unlink(missing_ok=True)