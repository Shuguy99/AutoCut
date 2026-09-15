from datetime import datetime, timedelta, timezone

import config
import jobs


def _make_result(filename="clip_00.mp4", thumb="clip_00.jpg"):
    return {
        "clips": [
            {"id": 0, "title": "Хайлайт", "start": 1.0, "end": 5.0, "score": 80,
             "reason": "сильный момент", "duration": 4.0, "filename": filename, "thumb": thumb}
        ],
        "montage_duration": 4.0,
    }


def test_create_and_public():
    jid = jobs.create_job("video.mp4")
    assert jobs.get_job(jid)["status"] == "uploaded"
    pub = jobs.public(jid)
    assert pub["id"] == jid
    assert pub["status"] == "uploaded"
    # служебные пути не должны утекать в API
    assert "montage_path" not in pub
    assert "clips_dir" not in pub
    assert "transcript_path" not in pub


def test_update_transitions():
    jid = jobs.create_job("video.mp4")
    jobs.update(jid, status="processing", stage="transcribe", progress=5)
    pub = jobs.public(jid)
    assert pub["status"] == "processing"
    assert pub["stage"] == "transcribe"
    assert pub["progress"] == 5

    jobs.update(jid, progress=70)
    assert jobs.public(jid)["progress"] == 70

    jobs.set_error(jid, "boom")
    pub = jobs.public(jid)
    assert pub["status"] == "error"
    assert pub["error"] == "boom"


def test_completed_persists_roundtrip(tmp_path):
    jid = jobs.create_job("video.mp4")
    jobs.update(jid, status="completed", stage="done", progress=100, result=_make_result())

    # «перезапуск сервиса»: сбрасываем реестр и загружаем с диска
    jobs._JOBS.clear()
    jobs.load_persisted()

    restored = jobs.public(jid)
    assert restored["status"] == "completed"
    assert restored["progress"] == 100
    clip = restored["result"]["clips"][0]
    # URL-ы нормализованы и не задвоены
    assert clip["file"] == f"/api/jobs/{jid}/clips/clip_00.mp4"
    assert clip["thumb"] == f"/api/jobs/{jid}/thumbs/clip_00.jpg"


def test_export_accepts_both_url_forms():
    """Старые джобы хранят уже готовые URL в result — их нельзя префиксовать повторно."""
    jid = jobs.create_job("video.mp4")
    # имитируем восстановленный из job.json джоб, где result уже содержит /api/... пути
    with jobs._LOCK:
        job = jobs._JOBS[jid]
        job["result"] = {
            "clips": [{
                "id": 0, "title": "Хайлайт", "start": 1.0, "end": 5.0, "score": 80,
                "reason": "x", "duration": 4.0,
                "file": f"/api/jobs/{jid}/clips/clip_00.mp4",
                "thumb": f"/api/jobs/{jid}/thumbs/clip_00.jpg",
            }],
            "montage_duration": 4.0,
        }
        job["status"] = "completed"
    clip = jobs.public(jid)["result"]["clips"][0]
    assert clip["file"].count("/api/jobs/") == 1
    assert clip["thumb"].count("/api/jobs/") == 1
    assert clip["file"] == f"/api/jobs/{jid}/clips/clip_00.mp4"
    assert clip["thumb"] == f"/api/jobs/{jid}/thumbs/clip_00.jpg"


def test_export_no_thumb():
    jid = jobs.create_job("video.mp4")
    result = {
        "clips": [{"id": 0, "title": "Хайлайт", "start": 1.0, "end": 5.0, "score": 80,
                   "reason": "x", "duration": 4.0, "filename": "clip_00.mp4", "thumb": None}],
        "montage_duration": 4.0,
    }
    with jobs._LOCK:
        jobs._JOBS[jid]["result"] = result
        jobs._JOBS[jid]["status"] = "completed"
    clip = jobs.public(jid)["result"]["clips"][0]
    assert clip["thumb"] is None


def test_list_all_excludes_active_uploads_and_includes_completed():
    a = jobs.create_job("a.mp4")
    b = jobs.create_job("b.mp4")
    jobs.update(a, status="processing", stage="cut", progress=70)
    jobs.update(b, status="completed", progress=100, result=_make_result())
    ids = [j["id"] for j in jobs.list_all()]
    assert b in ids
    assert a in ids  # processing тоже виден


def test_cleanup_removes_only_old_jobs():
    old = jobs.create_job("old.mp4")
    with jobs._LOCK:
        jobs._JOBS[old]["created_at"] = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()
        jobs._JOBS[old]["status"] = "completed"
        jobs._JOBS[old]["result"] = _make_result()

    fresh = jobs.create_job("fresh.mp4")
    jobs.update(fresh, status="completed", progress=100, result=_make_result())

    removed = jobs.cleanup_old_jobs(max_days=7, keep=0)
    assert removed == 1
    assert jobs.get_job(old) is None
    assert jobs.get_job(fresh) is not None
    assert not (config.JOBS_DIR / old).exists()


def test_cleanup_keeps_recent_regardless_of_age():
    old = jobs.create_job("old.mp4")
    with jobs._LOCK:
        jobs._JOBS[old]["created_at"] = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()
        jobs._JOBS[old]["status"] = "completed"
        jobs._JOBS[old]["result"] = _make_result()
    removed = jobs.cleanup_old_jobs(max_days=7, keep=10)
    assert removed == 0
    assert jobs.get_job(old) is not None


def test_cancel_lifecycle():
    jid = jobs.create_job("v.mp4")
    jobs.update(jid, status="processing", stage="cut", progress=70)
    assert jobs.cancel(jid) == "ok"
    assert jobs.is_cancelled(jid)
    try:
        jobs.raise_if_cancelled(jid)
        assert False, "raise_if_cancelled должен поднять CancelledError"
    except jobs.CancelledError:
        pass

    jobs.mark_cancelled(jid)
    assert not jobs.is_cancelled(jid)
    assert jobs.public(jid)["status"] == "cancelled"
    # клипы-недоделки удаляются при отмене
    assert jobs.get_job(jid) is not None
    assert jobs.cancel(jid) == "terminal"


def test_cancel_unknown_job():
    assert jobs.cancel("no-such-job") == "notfound"


def test_stage_detail_in_public():
    jid = jobs.create_job("v.mp4")
    jobs.update(jid, status="processing", stage="score", progress=35, stage_detail="Оценка интересности: 2/34")
    assert jobs.public(jid)["stage_detail"] == "Оценка интересности: 2/34"