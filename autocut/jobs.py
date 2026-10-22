"""In-memory очередь задач с одним worker-потоком."""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

from .config import Config
from .downloader import DownloadError
from .media import MediaError
from .models import JobOptions
from .pipeline import CancelledError, PipelineError, run_pipeline
from .render import RenderError
from .transcribe import TranscriptionError

logger = logging.getLogger(__name__)

EXPECTED_ERRORS = (
    PipelineError,
    DownloadError,
    TranscriptionError,
    MediaError,
    RenderError,
)


class QueueFullError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    source: str
    options: JobOptions
    status: str = "queued"
    stage: str = "queued"
    progress: float = 0.0
    message: str = ""
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(
        default_factory=threading.Event, repr=False
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "options": self.options.model_dump(),
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
        }


class JobManager:
    """Последовательная очередь задач.

    ``max_queue`` ограничивает число ожидающих задач (запущенная задача в
    очередь не входит). Один worker обрабатывает задачи по одной.
    """

    def __init__(self, config: Config, runner=run_pipeline, max_queue: int = 3):
        self._config = config
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._queue: queue.Queue[Job] = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def submit(self, source: str, options: JobOptions) -> Job:
        return self.submit_many([source], options)[0]

    def submit_many(
        self, sources: list[str], options: JobOptions
    ) -> list[Job]:
        if not sources:
            raise ValueError("нужен хотя бы один источник")
        jobs = [
            Job(id=uuid.uuid4().hex[:12], source=source, options=options)
            for source in sources
        ]
        with self._lock:
            if self._closed:
                raise QueueFullError("менеджер задач остановлен")
            free = self._queue.maxsize - self._queue.qsize()
            if len(jobs) > free:
                raise QueueFullError(
                    f"очередь заполнена: свободно {max(0, free)} мест"
                )
            for job in jobs:
                self._jobs[job.id] = job
            try:
                for job in jobs:
                    self._queue.put_nowait(job)
            except queue.Full as exc:  # защита от гонки с shutdown
                for job in jobs:
                    self._jobs.pop(job.id, None)
                raise QueueFullError(
                    "очередь заполнена, попробуйте позже"
                ) from exc
        return jobs

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(
            jobs, key=lambda job: (job.created_at, job.id), reverse=True
        )

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in {"done", "failed", "cancelled"}:
                return False
            job.cancel_event.set()
            if job.status == "queued":
                job.status = "cancelled"
                job.message = "отменено до запуска"
            return True

    def shutdown(self) -> None:
        """Останавливает worker после текущей задачи."""
        with self._lock:
            self._closed = True
        self._thread.join(timeout=5)

    def _worker(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._closed:
                    return
                continue
            try:
                if self._closed:
                    if job.status == "queued":
                        job.status = "cancelled"
                        job.message = "менеджер задач остановлен"
                    return
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.message = "отменено до запуска"
                    continue
                job.status = "running"
                job.stage = "start"
                job.message = "запуск"

                def progress(stage: str, percent: float, message: str) -> None:
                    with self._lock:
                        job.stage = stage
                        job.progress = float(percent)
                        job.message = message

                result = self._runner(
                    job.source, job.options, self._config,
                    progress=progress,
                    is_cancelled=job.cancel_event.is_set,
                )
                job.result = result
                job.status = "done"
                job.progress = 100.0
                job.message = "готово"
            except CancelledError:
                job.status = "cancelled"
                job.message = "отменено"
            except EXPECTED_ERRORS as exc:
                logger.warning("job %s failed: %s", job.id, exc)
                job.status = "failed"
                job.error = str(exc)
                job.message = "ошибка"
            except Exception as exc:  # noqa: BLE001
                logger.exception("job %s failed", job.id)
                job.status = "failed"
                job.error = str(exc)
                job.message = "ошибка"
            finally:
                self._queue.task_done()
