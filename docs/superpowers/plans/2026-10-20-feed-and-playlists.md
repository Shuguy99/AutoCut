# Лента RuTube и плейлисты — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в AutoCut ленту популярных видео RuTube и пакетную обработку плейлистов (веб + CLI).

**Architecture:** Новый модуль `feed.py` инкапсулирует RuTube recommendation API. В `downloader.py` появляется `list_playlist()` на flat-режиме yt-dlp. `JobManager.submit_many()` создаёт отдельную задачу на каждое выбранное видео. FastAPI отдаёт три новых эндпоинта, фронтенд добавляет блок ленты и режим «Плейлист» без сборщика.

**Tech Stack:** Python 3.14, FastAPI, pydantic v2, yt-dlp, stdlib `urllib`, pytest, ванильный JS/CSS.

**Spec:** `docs/superpowers/specs/2026-10-20-feed-and-playlists-design.md`

## Global Constraints

- Python ≥ 3.11 (в окружении 3.14.8); запуск тестов — `.venv/bin/python -m pytest`.
- Новых зависимостей нет: сеть для ленты — `urllib.request` из stdlib.
- Сетевые вызовы только в `autocut/feed.py` и `autocut/downloader.py`; тесты никогда не ходят в сеть.
- Все сообщения пользователю — по-русски.
- Веб слушает `127.0.0.1` по умолчанию; очередь веб-приложения — 20 задач, worker один.
- В репозитории не настроена git identity, поэтому коммит всегда с явными флагами:
  `git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "..."`.
- TDD: сначала падающий тест, затем минимальная реализация, затем полный прогон затронутых тестов.
- Работаем в ветке `feature/rutube-feed-playlists` (уже создана, спека закоммичена).

---

## File Map

```
autocut/
  feed.py                     # NEW: RuTube recommendation API → FeedPage
  models.py                   # + PlaylistItem, PlaylistInfo
  downloader.py               # + NotAPlaylistError, list_playlist()
  jobs.py                     # + submit_many(); submit() делегирует
  cli.py                      # + --playlist-limit и цикл по плейлисту
  web/app.py                  # + /api/feed, /api/playlist, /api/jobs/batch
  web/static/index.html       # + блок ленты, режим, шаблоны
  web/static/app.js           # + загрузка ленты, режим плейлиста, batch
  web/static/style.css        # + стили ленты и списка
tests/
  test_feed.py                # NEW
  test_downloader.py          # + list_playlist
  test_jobs.py                # + submit_many
  test_api.py                 # + feed/playlist/batch
  test_cli.py                 # + playlist-limit
docs/superpowers/plans/2026-10-20-feed-and-playlists.md
README.md                     # + описание ленты и плейлистов
```

---

### Task 1: Модуль ленты RuTube

**Files:**
- Create: `autocut/feed.py`
- Create: `tests/test_feed.py`

**Interfaces:**
- Consumes: ничего из предыдущих задач.
- Produces:
  - `FeedError(RuntimeError)`
  - `FeedPage` (dataclass): `items: list[dict]`, `has_more: bool`
  - `fetch_feed(offset: int = 0, limit: int = 12) -> FeedPage`
  - элемент `items`: ключи `id, title, channel, duration, views, thumbnail, url, created_at`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_feed.py`:

```python
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
    assert page.has_more is True
    assert "limit=3" in calls[0][0]
    assert "offset=12" in calls[0][0]


def test_fetch_feed_filters(monkeypatch):
    payload = {
        "results": [
            _raw("ok", duration=300),
            _raw("short", duration=30),
            _raw("long", duration=2000),
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


def test_fetch_feed_deduplicates(monkeypatch):
    payload = {"results": [_raw("same"), _raw("same", hits=999)]}
    monkeypatch.setattr(feed, "_fetch_json", lambda url, timeout: payload)
    page = feed.fetch_feed()
    assert len(page.items) == 1
    assert page.items[0]["id"] == "same"


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
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_feed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autocut.feed'`.

- [ ] **Step 3: Реализовать `autocut/feed.py`**

```python
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

FEED_URL = "https://rutube.ru/api/v2/video/recommendation/main"
USER_AGENT = "Mozilla/5.0"
MIN_DURATION = 120.0
MAX_DURATION = 1800.0
TIMEOUT = 15.0


class FeedError(RuntimeError):
    pass


@dataclass
class FeedPage:
    items: list[dict]
    has_more: bool


def _fetch_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _to_item(raw: dict) -> dict | None:
    if raw.get("is_deleted") or raw.get("is_livestream") or raw.get("is_on_air"):
        return None
    video_id = raw.get("id")
    if not video_id:
        return None
    try:
        duration = float(raw.get("duration"))
    except (TypeError, ValueError):
        return None
    if not (MIN_DURATION <= duration <= MAX_DURATION):
        return None
    author = raw.get("author") or {}
    return {
        "id": str(video_id),
        "title": raw.get("title") or "Без названия",
        "channel": author.get("name") or "unknown",
        "duration": duration,
        "views": int(raw.get("hits") or 0),
        "thumbnail": raw.get("thumbnail_url"),
        "url": raw.get("video_url") or f"https://rutube.ru/video/{video_id}/",
        "created_at": raw.get("created_ts"),
    }


def fetch_feed(offset: int = 0, limit: int = 12, timeout: float = TIMEOUT) -> FeedPage:
    query = urllib.parse.urlencode({"limit": limit, "offset": offset})
    try:
        payload = _fetch_json(f"{FEED_URL}?{query}", timeout)
    except Exception as exc:  # noqa: BLE001
        raise FeedError(f"лента RuTube недоступна: {exc}") from exc

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise FeedError("лента RuTube вернула неожиданный ответ")

    items: list[dict] = []
    seen: set[str] = set()
    for raw in results:
        if not isinstance(raw, dict):
            continue
        item = _to_item(raw)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)
    items.sort(key=lambda item: item["views"], reverse=True)
    return FeedPage(items=items, has_more=len(results) >= limit)
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_feed.py -v`
Expected: 5 passed.

- [ ] **Step 5: Коммит**

```bash
git add autocut/feed.py tests/test_feed.py
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: RuTube recommendation feed parser"
```

---

### Task 2: Эндпоинт `GET /api/feed`

**Files:**
- Modify: `autocut/web/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `feed.fetch_feed`, `feed.FeedPage`, `feed.FeedError` из Task 1.
- Produces: `GET /api/feed?offset=0&limit=12` →
  `{"items": [...], "next_offset": 12, "has_more": true}`; 422 при неверных параметрах, 502 при `FeedError`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_api.py`:

```python
from autocut import feed as feed_module
from autocut.feed import FeedPage


def test_feed_endpoint(config: Config, monkeypatch):
    page = FeedPage(
        items=[{
            "id": "v1", "title": "T", "channel": "C", "duration": 300.0,
            "views": 5, "thumbnail": None,
            "url": "https://rutube.ru/video/v1/", "created_at": None,
        }],
        has_more=True,
    )
    calls = {}

    def fake_fetch(offset=0, limit=12):
        calls.update(offset=offset, limit=limit)
        return page

    monkeypatch.setattr("autocut.web.app.fetch_feed", fake_fetch)
    client = _client(config)
    response = client.get("/api/feed?offset=12&limit=6")

    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["id"] == "v1"
    assert data["next_offset"] == 18
    assert data["has_more"] is True
    assert calls == {"offset": 12, "limit": 6}


def test_feed_endpoint_error(config: Config, monkeypatch):
    def boom(offset=0, limit=12):
        raise feed_module.FeedError("лента RuTube недоступна: timeout")

    monkeypatch.setattr("autocut.web.app.fetch_feed", boom)
    client = _client(config)
    response = client.get("/api/feed")
    assert response.status_code == 502
    assert "недоступна" in response.json()["detail"]


def test_feed_endpoint_validates_limit(config: Config):
    client = _client(config)
    assert client.get("/api/feed?limit=100").status_code == 422
    assert client.get("/api/feed?offset=-1").status_code == 422
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_api.py -k feed -v`
Expected: FAIL — 404 (маршрута нет).

- [ ] **Step 3: Добавить маршрут в `autocut/web/app.py`**

В импорты добавить:

```python
from ..feed import FeedError, fetch_feed
```

После `@app.get("/")` (перед `create_job`) добавить:

```python
    @app.get("/api/feed")
    def get_feed(offset: int = 0, limit: int = 12) -> dict:
        if not (1 <= limit <= 24) or offset < 0:
            raise HTTPException(
                status_code=422, detail="limit должен быть 1–24, offset ≥ 0"
            )
        try:
            page = fetch_feed(offset=offset, limit=limit)
        except FeedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "items": page.items,
            "next_offset": offset + limit,
            "has_more": page.has_more,
        }
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_api.py -k feed -v`
Expected: 3 passed.

- [ ] **Step 5: Коммит**

```bash
git add autocut/web/app.py tests/test_api.py
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: GET /api/feed for RuTube recommendations"
```

---

### Task 3: `list_playlist()` в загрузчике

**Files:**
- Modify: `autocut/models.py`
- Modify: `autocut/downloader.py`
- Test: `tests/test_downloader.py`

**Interfaces:**
- Consumes: `YoutubeDL`, `_opts` из `downloader.py`.
- Produces:
  - `PlaylistItem`: `video_id, title, channel, duration: float | None, url, thumbnail: str | None`
  - `PlaylistInfo`: `title, items: list[PlaylistItem], truncated: bool`
  - `NotAPlaylistError(DownloadError)`
  - `list_playlist(url, limit=30, proxy=None, cookies=None) -> PlaylistInfo`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_downloader.py`:

```python
class FakePlaylistYDL:
    last_opts = None

    def __init__(self, opts):
        FakePlaylistYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        return {
            "_type": "playlist",
            "title": "Сборник",
            "channel": "Канал",
            "entries": [
                {
                    "id": "v1", "title": "Первое", "duration": 120,
                    "url": "https://rutube.ru/video/v1/",
                    "thumbnail": "https://img/1.jpg",
                },
                {
                    "id": "v2", "title": "Второе", "duration": None,
                    "url": "https://rutube.ru/video/v2/",
                },
                {"id": "bad", "title": "Без ссылки"},
                None,
            ],
        }


def test_list_playlist(monkeypatch):
    monkeypatch.setattr(downloader, "YoutubeDL", FakePlaylistYDL)
    info = downloader.list_playlist("https://rutube.ru/plst/1/", limit=2)

    assert info.title == "Сборник"
    assert info.truncated is True
    assert [item.video_id for item in info.items] == ["v1", "v2"]
    assert info.items[0].channel == "Канал"
    assert info.items[0].duration == 120.0
    assert info.items[1].duration is None
    assert FakePlaylistYDL.last_opts["noplaylist"] is False
    assert FakePlaylistYDL.last_opts["extract_flat"] == "in_playlist"
    assert FakePlaylistYDL.last_opts["playlistend"] == 2


def test_list_playlist_rejects_single_video(monkeypatch):
    monkeypatch.setattr(downloader, "YoutubeDL", FakeYDL)
    with pytest.raises(downloader.NotAPlaylistError):
        downloader.list_playlist("https://youtu.be/abc123")


def test_list_playlist_error(monkeypatch):
    class BrokenYDL(FakePlaylistYDL):
        def extract_info(self, url, download=False):
            raise RuntimeError("network down")

    monkeypatch.setattr(downloader, "YoutubeDL", BrokenYDL)
    with pytest.raises(downloader.DownloadError):
        downloader.list_playlist("https://rutube.ru/plst/1/")
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_downloader.py -k playlist -v`
Expected: FAIL — `AttributeError: module 'autocut.downloader' has no attribute 'list_playlist'`.

- [ ] **Step 3: Добавить модели в `autocut/models.py`**

После `SourceInfo` добавить:

```python
@dataclass
class PlaylistItem:
    video_id: str
    title: str
    channel: str
    duration: float | None
    url: str
    thumbnail: str | None = None


@dataclass
class PlaylistInfo:
    title: str
    items: list[PlaylistItem]
    truncated: bool = False
```

- [ ] **Step 4: Реализовать `list_playlist()` в `autocut/downloader.py`**

Импорт моделей расширить:

```python
from .models import PlaylistInfo, PlaylistItem, SourceInfo
```

После `class DownloadError` добавить:

```python
class NotAPlaylistError(DownloadError):
    pass
```

В конец файла добавить:

```python
def list_playlist(
    url: str,
    limit: int = 30,
    proxy: str | None = None,
    cookies: str | Path | None = None,
) -> PlaylistInfo:
    opts = _opts(
        extract_flat="in_playlist",
        noplaylist=False,
        playlistend=limit,
        skip_download=True,
        format=None,
    )
    if proxy:
        opts["proxy"] = proxy
    if cookies:
        opts["cookiefile"] = str(cookies)

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise DownloadError(f"не удалось получить плейлист: {exc}") from exc

    if not info or info.get("_type") != "playlist":
        raise NotAPlaylistError("это не плейлист или он пуст")

    entries = info.get("entries") or []
    playlist_title = str(info.get("title") or "Плейлист")
    playlist_channel = str(
        info.get("channel") or info.get("uploader") or "unknown"
    )
    items: list[PlaylistItem] = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get("id")
        link = entry.get("webpage_url") or entry.get("url")
        if not video_id or not link or not str(link).startswith("http"):
            continue
        duration = entry.get("duration")
        items.append(
            PlaylistItem(
                video_id=str(video_id),
                title=str(entry.get("title") or "Без названия"),
                channel=str(
                    entry.get("channel")
                    or entry.get("uploader")
                    or playlist_channel
                ),
                duration=float(duration) if duration is not None else None,
                url=str(link),
                thumbnail=entry.get("thumbnail"),
            )
        )

    if not items:
        raise NotAPlaylistError("в плейлисте нет доступных видео")
    return PlaylistInfo(
        title=playlist_title,
        items=items,
        truncated=len(entries) >= limit,
    )
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_downloader.py -v`
Expected: все passed (3 новых + старые).

- [ ] **Step 6: Коммит**

```bash
git add autocut/models.py autocut/downloader.py tests/test_downloader.py
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: list playlist entries via yt-dlp flat extraction"
```

---

### Task 4: Эндпоинт `POST /api/playlist`

**Files:**
- Modify: `autocut/web/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `list_playlist`, `DownloadError`, `NotAPlaylistError` из Task 3.
- Produces: `POST /api/playlist`
  body `{"url": str, "limit": 30, "proxy": null}` →
  `{"title": str, "items": [...], "truncated": bool}`;
  400 — не плейлист/пусто, 502 — сеть, 422 — невалидный limit.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_api.py` (импорты — рядом с существующими):

```python
from autocut.downloader import DownloadError, NotAPlaylistError
from autocut.models import PlaylistInfo, PlaylistItem


def test_playlist_endpoint(config: Config, monkeypatch):
    info = PlaylistInfo(
        title="Сборник",
        items=[PlaylistItem(
            "v1", "Первое", "Канал", 120.0,
            "https://rutube.ru/video/v1/", None,
        )],
        truncated=True,
    )
    calls = {}

    def fake_list(url, limit=30, proxy=None, cookies=None):
        calls.update(url=url, limit=limit, proxy=proxy, cookies=cookies)
        return info

    monkeypatch.setattr("autocut.web.app.list_playlist", fake_list)
    client = _client(config)
    response = client.post("/api/playlist", json={
        "url": " https://rutube.ru/plst/1/ ",
        "limit": 5,
        "proxy": "socks5://x:1",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Сборник"
    assert data["items"][0]["video_id"] == "v1"
    assert data["truncated"] is True
    assert calls["url"] == "https://rutube.ru/plst/1/"
    assert calls["limit"] == 5
    assert calls["proxy"] == "socks5://x:1"


def test_playlist_endpoint_not_a_playlist(config: Config, monkeypatch):
    def boom(*args, **kwargs):
        raise NotAPlaylistError("это не плейлист или он пуст")

    monkeypatch.setattr("autocut.web.app.list_playlist", boom)
    client = _client(config)
    response = client.post("/api/playlist", json={"url": "https://youtu.be/x"})
    assert response.status_code == 400


def test_playlist_endpoint_network_error(config: Config, monkeypatch):
    def boom(*args, **kwargs):
        raise DownloadError("не удалось получить плейлист: timeout")

    monkeypatch.setattr("autocut.web.app.list_playlist", boom)
    client = _client(config)
    response = client.post(
        "/api/playlist", json={"url": "https://rutube.ru/plst/1/"}
    )
    assert response.status_code == 502


def test_playlist_endpoint_validates_limit(config: Config):
    client = _client(config)
    response = client.post(
        "/api/playlist", json={"url": "https://x", "limit": 0}
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_api.py -k playlist -v`
Expected: FAIL — 404.

- [ ] **Step 3: Добавить схему и маршрут в `autocut/web/app.py`**

Импорты расширить:

```python
from dataclasses import asdict

from ..downloader import DownloadError, NotAPlaylistError, list_playlist
```

После `CreateJobRequest` добавить:

```python
class PlaylistRequest(BaseModel):
    url: str = Field(min_length=1)
    limit: int = Field(30, ge=1, le=50)
    proxy: str | None = None
```

После маршрута `/api/feed` добавить:

```python
    @app.post("/api/playlist")
    def playlist(request: PlaylistRequest) -> dict:
        try:
            info = list_playlist(
                request.url.strip(),
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
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_api.py -k playlist -v`
Expected: 4 passed.

- [ ] **Step 5: Коммит**

```bash
git add autocut/web/app.py tests/test_api.py
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: POST /api/playlist for flat playlist listing"
```

---

### Task 5: `JobManager.submit_many()`

**Files:**
- Modify: `autocut/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `Job`, `JobOptions`, `QueueFullError`.
- Produces: `submit_many(sources: list[str], options: JobOptions) -> list[Job]`;
  `submit()` остаётся совместимым и делегирует в `submit_many`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_jobs.py`:

```python
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
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_jobs.py -k submit_many -v`
Expected: FAIL — `AttributeError: 'JobManager' object has no attribute 'submit_many'`.

- [ ] **Step 3: Реализовать `submit_many()` в `autocut/jobs.py`**

Заменить метод `submit` целиком на:

```python
    def submit(self, source: str, options: JobOptions) -> Job:
        return self.submit_many([source], options)[0]

    def submit_many(
        self, sources: list[str], options: JobOptions
    ) -> list[Job]:
        jobs = [
            Job(id=uuid.uuid4().hex[:12], source=source, options=options)
            for source in sources
        ]
        with self._lock:
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
            except queue.Full as exc:
                for job in jobs:
                    self._jobs.pop(job.id, None)
                raise QueueFullError(
                    "очередь заполнена, попробуйте позже"
                ) from exc
        return jobs
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_jobs.py -v`
Expected: все passed.

- [ ] **Step 5: Коммит**

```bash
git add autocut/jobs.py tests/test_jobs.py
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: batch job submission with atomic queue check"
```

---

### Task 6: Эндпоинт `POST /api/jobs/batch` и очередь 20

**Files:**
- Modify: `autocut/web/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `JobManager.submit_many` из Task 5.
- Produces: `POST /api/jobs/batch` body `{"sources": [1..20], "options": {}}` →
  `{"jobs": [...]}`; 429 при переполнении, 422 при пустом списке/больше 20.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_api.py`:

```python
import threading


def test_batch_jobs(config: Config):
    client = _client(config)
    response = client.post("/api/jobs/batch", json={
        "sources": ["/tmp/a.mp4", "/tmp/b.mp4"],
        "options": {"clips": 1},
    })
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert len(jobs) == 2
    assert {job["source"] for job in jobs} == {"/tmp/a.mp4", "/tmp/b.mp4"}


def test_batch_jobs_validates_sources(config: Config):
    client = _client(config)
    assert client.post(
        "/api/jobs/batch", json={"sources": [], "options": {}}
    ).status_code == 422
    assert client.post(
        "/api/jobs/batch",
        json={"sources": ["/tmp/x.mp4"] * 21, "options": {}},
    ).status_code == 422


def test_batch_jobs_queue_full(config: Config):
    gate = threading.Event()

    def runner(source, options, config, progress=None, is_cancelled=None):
        gate.wait(3)
        return {"clips": []}

    manager = JobManager(config, runner=runner, max_queue=1)
    manager.submit("/tmp/busy.mp4", JobOptions(clips=1))
    for _ in range(100):
        if manager.list()[0].status == "running":
            break
        time.sleep(0.02)

    client = TestClient(create_app(config, manager))
    response = client.post("/api/jobs/batch", json={
        "sources": ["/tmp/a.mp4", "/tmp/b.mp4"],
        "options": {"clips": 1},
    })
    assert response.status_code == 429

    gate.set()
    manager.shutdown()
```

В импорты `tests/test_api.py` добавить `from autocut.models import JobOptions`.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_api.py -k batch -v`
Expected: FAIL — 404.

- [ ] **Step 3: Реализовать в `autocut/web/app.py`**

Добавить схему после `CreateJobRequest`:

```python
class BatchJobRequest(BaseModel):
    sources: list[str] = Field(min_length=1, max_length=20)
    options: JobOptions = Field(default_factory=JobOptions)
```

После `create_job` добавить:

```python
    @app.post("/api/jobs/batch")
    def create_jobs(request: BatchJobRequest) -> dict:
        sources = [
            source.strip()
            for source in request.sources
            if source.strip()
        ]
        if not sources:
            raise HTTPException(
                status_code=422, detail="нужен хотя бы один источник"
            )
        try:
            jobs = manager.submit_many(sources, request.options)
        except QueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return {"jobs": [_job_payload(job, config) for job in jobs]}
```

В `create_app` заменить создание менеджера:

```python
    manager = manager or JobManager(config, max_queue=20)
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_api.py -k batch -v`
Expected: 3 passed.

- [ ] **Step 5: Коммит**

```bash
git add autocut/web/app.py tests/test_api.py
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: batch jobs endpoint with 20-slot web queue"
```

---

### Task 7: Блок «Лента RuTube» в UI

**Files:**
- Modify: `autocut/web/static/index.html`
- Modify: `autocut/web/static/app.js`
- Modify: `autocut/web/static/style.css`

**Interfaces:**
- Consumes: `GET /api/feed` из Task 2.
- Produces: секция `#feed`, карточки с кнопкой «В форму»; кнопка подставляет `item.url` в `#source`, прокручивает и подсвечивает поле.

- [ ] **Step 1: Добавить разметку в `index.html`**

Внутри `<main>`, перед `<section class="card form-card">`, вставить:

```html
    <section class="card feed-card">
      <div class="section-head">
        <h2>Лента RuTube</h2>
        <button id="feed-refresh" class="ghost" type="button">Обновить</button>
      </div>
      <div id="feed" class="feed-grid"></div>
      <div id="feed-state" class="feed-state"></div>
      <button id="feed-more" class="ghost hidden" type="button">Показать ещё</button>
    </section>
```

Перед `<script src="/static/app.js"></script>` добавить шаблон:

```html
  <template id="feed-card-template">
    <article class="feed-item">
      <img alt="" loading="lazy">
      <div class="feed-body">
        <div class="feed-title"></div>
        <div class="feed-meta"></div>
        <button class="feed-pick ghost" type="button">В форму</button>
      </div>
    </article>
  </template>
```

- [ ] **Step 2: Добавить JS в `app.js`**

После `const cards = new Map();` добавить:

```js
const feedRoot = document.getElementById("feed");
const feedState = document.getElementById("feed-state");
const feedMore = document.getElementById("feed-more");
const feedRefresh = document.getElementById("feed-refresh");
const feedTemplate = document.getElementById("feed-card-template");
const feedSeen = new Set();
let feedOffset = 0;
let feedLoading = false;
```

После функции `el` добавить:

```js
function formatViews(value) {
  const count = Number(value) || 0;
  if (count >= 1000000) {
    return `${(count / 1000000).toFixed(1).replace(".", ",")} млн`;
  }
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1).replace(".", ",")} тыс.`;
  }
  return String(count);
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.round(Number(seconds));
  if (!Number.isFinite(total)) return "—";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function feedCard(item) {
  const node = feedTemplate.content.firstElementChild.cloneNode(true);
  const image = el("img", node);
  if (item.thumbnail) {
    image.src = item.thumbnail;
    image.alt = item.title;
  } else {
    image.remove();
  }
  el(".feed-title", node).textContent = item.title;
  el(".feed-meta", node).textContent =
    `${item.channel} · ${formatDuration(item.duration)} · ${formatViews(item.views)}`;
  el(".feed-pick", node).addEventListener("click", () => {
    const input = document.getElementById("source");
    input.value = item.url;
    input.focus();
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    input.classList.add("flash");
    setTimeout(() => input.classList.remove("flash"), 1200);
  });
  return node;
}

async function loadFeed(reset = false) {
  if (feedLoading) return;
  feedLoading = true;
  if (reset) {
    feedSeen.clear();
    feedRoot.innerHTML = "";
    feedOffset = 0;
    feedMore.classList.add("hidden");
  }
  feedState.classList.remove("error");
  feedState.textContent = "Загружаем ленту…";
  try {
    const response = await fetch(`/api/feed?offset=${feedOffset}&limit=12`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    for (const item of data.items || []) {
      if (feedSeen.has(item.id)) continue;
      feedSeen.add(item.id);
      feedRoot.append(feedCard(item));
    }
    feedOffset = data.next_offset ?? feedOffset + 12;
    feedMore.classList.toggle("hidden", !data.has_more);
    feedState.textContent = feedSeen.size ? "" : "Лента пуста.";
  } catch (err) {
    feedState.textContent = `Лента недоступна: ${err.message}`;
    feedState.classList.add("error");
  } finally {
    feedLoading = false;
  }
}

feedMore.addEventListener("click", () => loadFeed(false));
feedRefresh.addEventListener("click", () => loadFeed(true));
loadFeed(true);
```

- [ ] **Step 3: Добавить стили в `style.css`**

В конец файла, перед медиазапросом, добавить:

```css
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.section-head h2 { margin: 0; font-size: 18px; }
button.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  padding: 7px 14px;
  font-weight: 400;
}
button.ghost:hover { color: var(--text); border-color: var(--accent); }

.feed-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.feed-item {
  background: #0f121a;
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.feed-item img {
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  display: block;
  background: #0b0d13;
}
.feed-body {
  padding: 10px 12px 12px;
  display: grid;
  gap: 6px;
  flex: 1;
  align-content: start;
}
.feed-title {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.feed-meta { color: var(--muted); font-size: 12px; }
.feed-state { color: var(--muted); font-size: 13px; margin-top: 12px; }
.feed-state.error { color: var(--danger); }
#feed-more { margin-top: 14px; }
input.flash {
  border-color: var(--accent-2);
  box-shadow: 0 0 0 3px rgba(77, 226, 197, .2);
}
```

- [ ] **Step 4: Проверить вручную**

```bash
.venv/bin/autocut web --port 8010
```

Открыть `http://127.0.0.1:8010`, убедиться:
- лента загрузилась карточками с превью;
- «Показать ещё» добавляет карточки;
- «В форму» подставляет ссылку и подсвечивает поле;
- при остановленном RuTube (или офлайн) видна ошибка и кнопка «Обновить».

- [ ] **Step 5: Коммит**

```bash
git add autocut/web/static/index.html autocut/web/static/app.js autocut/web/static/style.css
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: RuTube feed cards in web UI"
```

---

### Task 8: Режим «Плейлист» в UI

**Files:**
- Modify: `autocut/web/static/index.html`
- Modify: `autocut/web/static/app.js`
- Modify: `autocut/web/static/style.css`

**Interfaces:**
- Consumes: `POST /api/playlist` (Task 4), `POST /api/jobs/batch` (Task 6), `formatDuration` (Task 7).
- Produces: переключатель «Видео / Плейлист», панель выбора, запуск выбранных.

- [ ] **Step 1: Добавить разметку**

В начало `<form id="job-form">` вставить:

```html
        <div class="mode-switch" role="group" aria-label="Режим источника">
          <button type="button" class="mode active" data-mode="video">Видео</button>
          <button type="button" class="mode" data-mode="playlist">Плейлист</button>
        </div>
```

После `<p id="form-error" class="error hidden"></p>` добавить:

```html
        <div id="playlist-panel" class="playlist-panel hidden">
          <div class="playlist-head">
            <strong id="playlist-title"></strong>
            <span id="playlist-count" class="feed-meta"></span>
          </div>
          <div id="playlist-items" class="playlist-items"></div>
          <button id="playlist-run" type="button" disabled>
            Запустить выбранные (0)
          </button>
        </div>
```

Перед шаблоном ленты добавить:

```html
  <template id="playlist-item-template">
    <label class="playlist-item">
      <input type="checkbox">
      <img alt="" loading="lazy">
      <span class="playlist-item-body">
        <span class="playlist-item-title"></span>
        <span class="playlist-item-meta"></span>
      </span>
    </label>
  </template>
```

- [ ] **Step 2: Добавить JS**

После констант ленты добавить:

```js
const playlistPanel = document.getElementById("playlist-panel");
const playlistTitle = document.getElementById("playlist-title");
const playlistCount = document.getElementById("playlist-count");
const playlistItemsRoot = document.getElementById("playlist-items");
const playlistRun = document.getElementById("playlist-run");
const playlistTemplate = document.getElementById("playlist-item-template");
const selectedPlaylist = new Map();
let mode = "video";
```

После функции `formatDuration` добавить:

```js
function setMode(next) {
  mode = next;
  document.querySelectorAll(".mode").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === next);
  });
  document.getElementById("submit").textContent =
    next === "playlist" ? "Показать список" : "Сделать клипы";
  if (next === "video") playlistPanel.classList.add("hidden");
}

function currentOptions() {
  return {
    clips: Number(document.getElementById("clips").value),
    min_duration: Number(document.getElementById("min-duration").value),
    max_duration: Number(document.getElementById("max-duration").value),
    layout: document.getElementById("layout").value,
    proxy: document.getElementById("proxy").value.trim() || null,
  };
}

function updatePlaylistCount() {
  const count = selectedPlaylist.size;
  playlistRun.textContent = `Запустить выбранные (${count})`;
  playlistRun.disabled = count === 0;
}

function playlistItem(item) {
  const node = playlistTemplate.content.firstElementChild.cloneNode(true);
  const checkbox = el("input", node);
  const image = el("img", node);
  if (item.thumbnail) {
    image.src = item.thumbnail;
    image.alt = item.title;
  } else {
    image.remove();
  }
  el(".playlist-item-title", node).textContent = item.title;
  el(".playlist-item-meta", node).textContent =
    `${item.channel} · ${formatDuration(item.duration)}`;
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) selectedPlaylist.set(item.url, item);
    else selectedPlaylist.delete(item.url);
    updatePlaylistCount();
  });
  return node;
}

async function loadPlaylist(url) {
  playlistPanel.classList.remove("hidden");
  playlistItemsRoot.innerHTML = "";
  selectedPlaylist.clear();
  updatePlaylistCount();
  playlistTitle.textContent = "Загружаем плейлист…";
  playlistCount.textContent = "";

  const response = await fetch("/api/playlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url,
      limit: 30,
      proxy: document.getElementById("proxy").value.trim() || null,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  playlistTitle.textContent = data.title;
  playlistCount.textContent = data.truncated
    ? `первые ${data.items.length}`
    : `видео: ${data.items.length}`;
  for (const item of data.items) {
    playlistItemsRoot.append(playlistItem(item));
  }
  if (!data.items.length) {
    playlistTitle.textContent = "В плейлисте нет доступных видео";
  }
}

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

playlistRun.addEventListener("click", async () => {
  const sources = [...selectedPlaylist.values()].map((item) => item.url);
  if (!sources.length) return;
  playlistRun.disabled = true;
  try {
    const response = await fetch("/api/jobs/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources, options: currentOptions() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    for (const job of data.jobs || []) renderJob(job);
    startPolling();
    selectedPlaylist.clear();
    playlistItemsRoot.innerHTML = "";
    updatePlaylistCount();
    playlistTitle.textContent = "";
    playlistCount.textContent = "";
  } catch (err) {
    formError.textContent = err.message;
    formError.classList.remove("hidden");
  } finally {
    playlistRun.disabled = selectedPlaylist.size === 0;
  }
});
```

- [ ] **Step 3: Переписать обработчик формы**

Заменить начало обработчика `form.addEventListener("submit", ...)` до объявления `payload` на:

```js
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.classList.add("hidden");
  const source = document.getElementById("source").value.trim();
  if (!source) return;

  if (mode === "playlist") {
    try {
      await loadPlaylist(source);
    } catch (err) {
      formError.textContent = err.message;
      formError.classList.remove("hidden");
    }
    return;
  }

  const payload = { source, options: currentOptions() };
```

Остальная часть обработчика не меняется (удалить старый `const payload = {...}`).

- [ ] **Step 4: Добавить стили**

В конец `style.css` добавить:

```css
.mode-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  background: #0f121a;
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 14px;
}
.mode {
  background: transparent;
  color: var(--muted);
  padding: 6px 16px;
  font-weight: 600;
}
.mode.active { background: var(--accent); color: #fff; }

.playlist-panel {
  margin-top: 18px;
  border-top: 1px solid var(--border);
  padding-top: 16px;
  display: grid;
  gap: 12px;
}
.playlist-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
}
.playlist-items {
  display: grid;
  gap: 8px;
  max-height: 420px;
  overflow-y: auto;
}
.playlist-item {
  display: grid;
  grid-template-columns: auto 96px 1fr;
  gap: 12px;
  align-items: center;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #0f121a;
  cursor: pointer;
}
.playlist-item input {
  width: 18px;
  height: 18px;
  accent-color: var(--accent);
}
.playlist-item img {
  width: 96px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 6px;
  display: block;
}
.playlist-item-body { display: grid; gap: 4px; font-size: 13px; }
.playlist-item-title { font-weight: 600; }
.playlist-item-meta { color: var(--muted); font-size: 12px; }
```

- [ ] **Step 5: Проверить вручную**

```bash
.venv/bin/autocut web --port 8010
```

Открыть `http://127.0.0.1:8010`:
- переключить на «Плейлист», вставить `https://rutube.ru/plst/308547/`, нажать «Показать список»;
- появляется список с чекбоксами и превью;
- отметить 2 видео, нажать «Запустить выбранные (2)» — появляются две карточки задач;
- проверить, что настройки клипов из формы применились (в карточке задачи видны этапы);
- отменить обе задачи.

- [ ] **Step 6: Коммит**

```bash
git add autocut/web/static/index.html autocut/web/static/app.js autocut/web/static/style.css
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: playlist selection UI with batch launch"
```

---

### Task 9: CLI `--playlist-limit`

**Files:**
- Modify: `autocut/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `list_playlist`, `NotAPlaylistError`, `is_url`, `PlaylistInfo` из Task 3.
- Produces: `run --playlist-limit N` (1–50, default 1); последовательная обработка, код 1 при ошибках.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_cli.py`:

```python
from autocut import cli
from autocut.models import PlaylistInfo, PlaylistItem


def test_playlist_limit_default():
    args = build_parser().parse_args(["run", "video.mp4"])
    assert args.playlist_limit == 1


def _items():
    return [
        PlaylistItem("v1", "Первое", "Канал", 100.0, "https://rutube.ru/video/v1/"),
        PlaylistItem("v2", "Второе", "Канал", 100.0, "https://rutube.ru/video/v2/"),
    ]


def test_run_playlist(monkeypatch, tmp_path):
    items = _items()
    monkeypatch.setattr(
        cli, "list_playlist", lambda *args, **kwargs: PlaylistInfo("Сборник", items)
    )
    calls = []

    def fake_pipeline(source, options, config, progress=None):
        calls.append(source)
        return {"result_dir": str(tmp_path), "source": {}, "clips": []}

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    code = cli.main([
        "run", "https://rutube.ru/plst/1/", "--playlist-limit", "2",
        "--output", str(tmp_path / "output"),
    ])
    assert code == 0
    assert calls == [items[0].url, items[1].url]


def test_run_playlist_continues_after_error(monkeypatch, tmp_path):
    items = _items()
    monkeypatch.setattr(
        cli, "list_playlist", lambda *args, **kwargs: PlaylistInfo("Сборник", items)
    )
    calls = []

    def fake_pipeline(source, options, config, progress=None):
        calls.append(source)
        if source == items[0].url:
            raise cli.PipelineError("boom")
        return {"result_dir": str(tmp_path), "source": {}, "clips": []}

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    code = cli.main([
        "run", "https://rutube.ru/plst/1/", "--playlist-limit", "2",
        "--output", str(tmp_path / "output"),
    ])
    assert code == 1
    assert calls == [items[0].url, items[1].url]


def test_run_playlist_requires_playlist(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise cli.NotAPlaylistError("это не плейлист или он пуст")

    monkeypatch.setattr(cli, "list_playlist", boom)
    code = cli.main([
        "run", "https://youtu.be/x", "--playlist-limit", "3",
        "--output", str(tmp_path / "output"),
    ])
    assert code == 1
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k playlist -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'playlist_limit'`.

- [ ] **Step 3: Реализовать в `autocut/cli.py`**

Импорт расширить:

```python
from .downloader import (
    DownloadError,
    NotAPlaylistError,
    get_trending,
    is_url,
    list_playlist,
)
```

В `build_parser()` после строки `_add_common(run_parser)` добавить:

```python
    run_parser.add_argument(
        "--playlist-limit",
        type=int,
        default=1,
        metavar="N",
        help="сколько видео из плейлиста обработать (1–50)",
    )
```

После `_print_result` добавить:

```python
JOB_ERRORS = (
    PipelineError, DownloadError, TranscriptionError, MediaError, RenderError
)


def _run_playlist(args, options, config, progress) -> int:
    try:
        playlist = list_playlist(
            args.source,
            limit=args.playlist_limit,
            proxy=args.proxy or config.proxy,
            cookies=args.cookies or config.cookies,
        )
    except DownloadError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    failures = 0
    for item in playlist.items:
        print(f"\n=== {item.title} ===", file=sys.stderr)
        try:
            result = run_pipeline(
                item.url, options, config, progress=progress
            )
        except JOB_ERRORS as exc:
            failures += 1
            print(f"Ошибка: {exc}", file=sys.stderr)
            continue
        _print_result(result, args.json)

    done = len(playlist.items) - failures
    print(
        f"\nОбработано {done} из {len(playlist.items)}", file=sys.stderr
    )
    return 1 if failures else 0
```

В `main()` после `args = parser.parse_args(argv)` добавить проверку:

```python
    playlist_limit = getattr(args, "playlist_limit", 1)
    if not 1 <= playlist_limit <= 50:
        parser.error("--playlist-limit должен быть от 1 до 50")
```

В `main()` заменить блок `try` (от `if args.command == "trending":` до `result = run_pipeline(...)`) на:

```python
    try:
        if args.command == "trending":
            source = get_trending(
                region=args.region,
                proxy=args.proxy or config.proxy,
                cookies=args.cookies or config.cookies,
            )
            print(f"Выбрано видео: {source}", file=sys.stderr)
        elif (
            args.command == "run"
            and args.playlist_limit > 1
            and is_url(args.source)
        ):
            return _run_playlist(args, options, config, progress)
        else:
            source = args.source
        result = run_pipeline(source, options, config, progress=progress)
    except JOB_ERRORS as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        return 130
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: все passed.

- [ ] **Step 5: Коммит**

```bash
git add autocut/cli.py tests/test_cli.py
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "feat: CLI playlist processing with --playlist-limit"
```

---

### Task 10: Документация и E2E

**Files:**
- Modify: `README.md`
- Test: ручная проверка

**Interfaces:**
- Consumes: всё предыдущее.
- Produces: документация и подтверждённый E2E.

- [ ] **Step 1: Обновить README**

В раздел с CLI-примерами добавить:

```bash
.venv/bin/autocut run "https://rutube.ru/plst/308547/" --playlist-limit 5
```

В описание веб-интерфейса добавить абзац:

```markdown
Над формой показывается лента рекомендаций RuTube: превью, канал, длительность
и просмотры. Кнопка «В форму» подставляет ссылку в поле источника.
Переключатель «Плейлист» позволяет загрузить список видео, отметить нужные
и запустить нарезку пакетом — каждое видео обрабатывается отдельной задачей.
```

В ограничения добавить:

```markdown
- Лента берётся из рекомендаций RuTube, а не из редакционного чарта; порядок
  внутри страницы сортируется по просмотрам.
- Для плейлистов длительность из flat-списка может быть неизвестна — в списке
  показывается «—», на обработку это не влияет.
```

- [ ] **Step 2: Полный прогон тестов**

Run: `.venv/bin/python -m pytest -q`
Expected: все тесты passed (было 56, станет больше).

- [ ] **Step 3: E2E ленты и плейлиста**

```bash
.venv/bin/autocut web --port 8010
```

В другом терминале:

```bash
curl -s "http://127.0.0.1:8010/api/feed?limit=6" | .venv/bin/python -m json.tool | head -40

curl -s -X POST "http://127.0.0.1:8010/api/playlist" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://rutube.ru/plst/308547/", "limit": 5}' \
  | .venv/bin/python -m json.tool | head -40
```

Expected: лента содержит `items` с `id/title/duration/views`; плейлист содержит 5 элементов с `video_id/url`.

В браузере открыть `http://127.0.0.1:8010` и проверить:
- карточки ленты кликабельны, «В форму» подставляет ссылку;
- «Показать ещё» догружает;
- режим «Плейлист» показывает список, чекбоксы работают, счётчик обновляется;
- запуск двух выбранных видео создаёт две задачи, обе доходят до `done` (можно с `--clips 1`, но веб использует настройки формы — поставьте «Клипов: 1», длины 10–25).

- [ ] **Step 4: Коммит**

```bash
git add README.md
git -c user.name="AutoCut" -c user.email="autocut@local" commit -m "docs: describe RuTube feed and playlist support"
```

---

## Self-Review

- **Покрытие спеки:** лента (Task 1–2, 7), плейлисты (Task 3–4, 8), пакетный запуск (Task 5–6), CLI (Task 9), документация и E2E (Task 10). Ошибки 400/422/429/502 реализованы в Task 2, 4, 6.
- **Плейсхолдеров нет:** каждый шаг содержит конкретный код или команду.
- **Согласованность типов:** `FeedPage`, `PlaylistItem`, `PlaylistInfo`, `submit_many`, `list_playlist` используются одинаково во всех задачах; `currentOptions()` появляется в Task 8 и используется обеими ветками формы.
- **Риск:** `Field(min_length=1, max_length=20)` для списка требует pydantic v2 (в проекте v2) — тест Task 6 это фиксирует.

---

## Amendment 2026-10-20: передискретизация ленты

При проверке Task 7 живой `/api/feed` отдавал 1 карточку на страницу: рекомендации RuTube на ~90% длиннее 30 минут. Спека обновлена (раздел 5.1):

- фильтр длительности — `120 <= duration <= 3600` секунд;
- у API запрашивается сырая порция `raw = min(99, max(50, limit * 4))`, наружу отдаётся до `limit` подходящих;
- `FeedPage` получает `next_offset: int`; `has_more` считается по сырой порции;
- `GET /api/feed` возвращает `page.next_offset`, а не `offset + limit`.

Код Task 1/2 и их тесты обновляются отдельным фикс-коммитом; Tasks 3–10 не меняются.
