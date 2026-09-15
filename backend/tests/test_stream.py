import threading
import time

from fastapi.testclient import TestClient

import jobs
from main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "version" in r.json()


def test_stream_done_for_completed_job():
    jid = jobs.create_job("video.mp4")
    jobs.update(jid, status="completed", stage="done", progress=100,
                result={"clips": [], "montage_duration": 0.0})
    with client.stream("GET", f"/api/jobs/{jid}/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.read().decode("utf-8")
    assert "event: done" in body
    assert '"status": "completed"' in body


def test_stream_emits_progress_then_done():
    """Джоб процесс в отдельном потоке, пока мы читаем SSE — должны увидеть
    и промежуточный снапшот, и финальный done."""
    jid = jobs.create_job("video.mp4")
    jobs.update(jid, status="processing", stage="cut", progress=70, result=None)

    out: dict[str, str] = {}

    def read() -> None:
        with client.stream("GET", f"/api/jobs/{jid}/stream") as resp:
            out["body"] = resp.read().decode("utf-8")

    t = threading.Thread(target=read)
    t.start()
    time.sleep(0.4)
    jobs.update(jid, status="completed", stage="done", progress=100,
                result={"clips": [], "montage_duration": 0.0})
    t.join(timeout=5)

    body = out.get("body", "")
    assert "event: done" in body
    assert '"status": "completed"' in body


def test_stream_unknown_job_closes():
    with client.stream("GET", "/api/jobs/nope/stream") as resp:
        body = resp.read().decode("utf-8")
    assert "event: gone" in body


def test_stream_404_bad_path():
    r = client.get("/api/jobs/unknown/clips/nope.mp4")
    assert r.status_code == 404