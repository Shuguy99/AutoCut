import threading
import time

import pytest

from autocut.config import Config
from autocut.jobs import JobManager, QueueFullError
from autocut.models import JobOptions


def _wait(manager, job_id, status="done", timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job and job.status == status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job did not reach {status}")


def test_job_runs(config: Config):
    def runner(source, options, config, progress=None, is_cancelled=None):
        progress("render", 80, "почти")
        return {"result_dir": "/tmp/x", "clips": [], "source": {}}

    manager = JobManager(config, runner=runner)
    job = manager.submit("/tmp/a.mp4", JobOptions(clips=1))
    finished = _wait(manager, job.id)
    assert finished.progress == 100
    assert finished.result["result_dir"] == "/tmp/x"
    manager.shutdown()


def test_job_failure(config: Config):
    def runner(*args, **kwargs):
        raise RuntimeError("boom")

    manager = JobManager(config, runner=runner)
    job = manager.submit("/tmp/a.mp4", JobOptions(clips=1))
    finished = _wait(manager, job.id, status="failed")
    assert "boom" in finished.error
    manager.shutdown()


def test_queue_limit(config: Config):
    gate = threading.Event()

    def runner(*args, **kwargs):
        gate.wait(3)
        return {"clips": []}

    manager = JobManager(config, runner=runner, max_queue=1)
    first = manager.submit("/tmp/a.mp4", JobOptions(clips=1))
    _wait(manager, first.id, status="running")
    manager.submit("/tmp/b.mp4", JobOptions(clips=1))
    with pytest.raises(QueueFullError):
        manager.submit("/tmp/c.mp4", JobOptions(clips=1))
    gate.set()
    manager.shutdown()


def test_submit_many_creates_all_jobs(config: Config):
    def runner(source, options, config, progress=None, is_cancelled=None):
        return {"clips": []}

    manager = JobManager(config, runner=runner, max_queue=5)
    jobs = manager.submit_many(
        ["/tmp/a.mp4", "/tmp/b.mp4"], JobOptions(clips=1)
    )
    assert len(jobs) == 2
    assert {job.source for job in jobs} == {"/tmp/a.mp4", "/tmp/b.mp4"}
    for job in jobs:
        _wait(manager, job.id)
    manager.shutdown()


def test_submit_many_queue_full_adds_nothing(config: Config):
    gate = threading.Event()

    def runner(*args, **kwargs):
        gate.wait(3)
        return {"clips": []}

    manager = JobManager(config, runner=runner, max_queue=1)
    first = manager.submit("/tmp/a.mp4", JobOptions(clips=1))
    _wait(manager, first.id, status="running")

    with pytest.raises(QueueFullError):
        manager.submit_many(
            ["/tmp/b.mp4", "/tmp/c.mp4"], JobOptions(clips=1)
        )
    assert len(manager.list()) == 1

    gate.set()
    manager.shutdown()
