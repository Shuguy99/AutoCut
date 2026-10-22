import pytest

from autocut import feed


def _raw(video_id="v1", **overrides):
    data = {
        "id": video_id,
        "title": "Видео",
        "duration": 600,
        "hits": 1000,
        "author": {"name": "Канал"},
        "video_url": f"https://rutube.ru/video/{video_id}/",
        "thumbnail_url": f"https://img/{video_id}.jpg",
        "created_ts": "2026-10-01T10:00:00",
    }
    data.update(overrides)
    return data


def test_fetch_feed_maps_and_sorts(monkeypatch):
    payload = {
        "results": [
            _raw("a", hits=10),
            _raw("b", hits=500),
            _raw("c", hits=100),
        ]
    }
    calls = []

    def fake_fetch(url, timeout):
        calls.append((url, timeout))
        return payload

    monkeypatch.setattr(feed, "_fetch_json", fake_fetch)
    page = feed.fetch_feed(offset=12, limit=3)

    assert [item["id"] for item in page.items] == ["b", "c", "a"]
    assert page.items[0] == {
        "id": "b",
        "title": "Видео",
        "channel": "Канал",
        "duration": 600.0,
        "views": 500,
        "thumbnail": "https://img/b.jpg",
        "url": "https://rutube.ru/video/b/",
        "created_at": "2026-10-01T10:00:00",
    }
    assert page.has_more is False
    assert page.next_offset == 62
    assert "limit=50" in calls[0][0]
    assert "offset=12" in calls[0][0]


def test_fetch_feed_filters(monkeypatch):
    payload = {
        "results": [
            _raw("ok", duration=300),
            _raw("short", duration=30),
            _raw("long", duration=4000),
            _raw("stream", is_livestream=True),
            _raw("deleted", is_deleted=True),
            _raw("onair", is_on_air=True),
            _raw("nodur", duration=None),
        ]
    }
    monkeypatch.setattr(feed, "_fetch_json", lambda url, timeout: payload)
    page = feed.fetch_feed(limit=12)
    assert [item["id"] for item in page.items] == ["ok"]
    assert page.has_more is False
    assert page.next_offset == 50


def test_fetch_feed_deduplicates(monkeypatch):
    payload = {"results": [_raw("same"), _raw("same", hits=999)]}
    monkeypatch.setattr(feed, "_fetch_json", lambda url, timeout: payload)
    page = feed.fetch_feed()
    assert len(page.items) == 1
    assert page.items[0]["id"] == "same"
    assert page.next_offset == 50


def test_fetch_feed_oversamples_and_pages(monkeypatch):
    results = []
    for index in range(50):
        if index < 20:
            results.append(_raw(f"ok{index}", duration=300, hits=index))
        else:
            results.append(_raw(f"long{index}", duration=4000, hits=1000 + index))
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        return {"results": results}

    monkeypatch.setattr(feed, "_fetch_json", fake_fetch)
    page = feed.fetch_feed(offset=0, limit=12)

    assert len(page.items) == 12
    assert page.items[0]["id"] == "ok19"
    assert page.has_more is True
    assert page.next_offset == 50
    assert "limit=50" in calls[0]


def test_fetch_feed_duration_boundary(monkeypatch):
    payload = {
        "results": [
            _raw("min", duration=120),
            _raw("max", duration=3600),
            _raw("over", duration=3601),
            _raw("under", duration=119),
        ]
    }
    monkeypatch.setattr(feed, "_fetch_json", lambda url, timeout: payload)
    page = feed.fetch_feed()
    assert [item["id"] for item in page.items] == ["min", "max"]


def test_fetch_feed_network_error(monkeypatch):
    def boom(url, timeout):
        raise OSError("нет сети")

    monkeypatch.setattr(feed, "_fetch_json", boom)
    with pytest.raises(feed.FeedError, match="недоступна"):
        feed.fetch_feed()


def test_fetch_feed_bad_payload(monkeypatch):
    monkeypatch.setattr(feed, "_fetch_json", lambda url, timeout: {"items": []})
    with pytest.raises(feed.FeedError):
        feed.fetch_feed()


def test_fetch_feed_survives_non_numeric_views(monkeypatch):
    payload = {"results": [_raw("bad", hits="много"), _raw("good", hits=5)]}
    monkeypatch.setattr(feed, "_fetch_json", lambda url, timeout: payload)
    page = feed.fetch_feed()
    views = {item["id"]: item["views"] for item in page.items}
    assert views == {"bad": 0, "good": 5}


def test_fetch_feed_clamps_limit(monkeypatch):
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        return {"results": []}

    monkeypatch.setattr(feed, "_fetch_json", fake_fetch)
    page = feed.fetch_feed(limit=0)
    assert page.items == []
    assert "limit=50" in calls[0]
