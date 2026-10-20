import time

from fastapi.testclient import TestClient

from autocut.config import Config
from autocut.jobs import JobManager
from autocut.web.app import create_app


def _fake_runner(source, options, config, progress=None, is_cancelled=None):
    progress("done", 100, "готово")
    return {
        "result_dir": str(config.output_dir / "demo"),
        "clips": [],
        "source": {},
    }


def _client(config: Config) -> TestClient:
    manager = JobManager(config, runner=_fake_runner)
    return TestClient(create_app(config, manager))


def test_create_and_get_job(config: Config):
    client = _client(config)
    response = client.post("/api/jobs", json={
        "source": "/tmp/video.mp4",
        "options": {"clips": 2, "min_duration": 10, "max_duration": 30},
    })
    assert response.status_code == 200
    job_id = response.json()["id"]
    data = {}
    for _ in range(100):
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] == "done":
            break
        time.sleep(0.02)
    assert data["status"] == "done"
    assert client.get("/api/jobs").json()[0]["id"] == job_id


def test_missing_job(config: Config):
    client = _client(config)
    assert client.get("/api/jobs/nope").status_code == 404


def test_file_serving_and_traversal(config: Config):
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "demo.txt").write_text("ok", encoding="utf-8")
    client = _client(config)
    assert client.get("/files/demo.txt").text == "ok"
    assert client.get("/files/../../etc/passwd").status_code == 404


def test_subtitles_served_as_text(config: Config):
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "clip.ass").write_text("[Script Info]", encoding="utf-8")
    client = _client(config)
    response = client.get("/files/clip.ass")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "[Script Info]" in response.text


def test_index(config: Config):
    client = _client(config)
    response = client.get("/")
    assert response.status_code == 200
    assert "AutoCut" in response.text
