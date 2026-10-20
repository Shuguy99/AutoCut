from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

FEED_URL = "https://rutube.ru/api/v2/video/recommendation/main"
USER_AGENT = "Mozilla/5.0"
MIN_DURATION = 120.0
MAX_DURATION = 3600.0
RAW_PAGE_MIN = 50
RAW_PAGE_MAX = 99
TIMEOUT = 15.0


class FeedError(RuntimeError):
    pass


@dataclass
class FeedPage:
    items: list[dict]
    has_more: bool
    next_offset: int


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


def _raw_limit(limit: int) -> int:
    return min(RAW_PAGE_MAX, max(RAW_PAGE_MIN, limit * 4))


def fetch_feed(offset: int = 0, limit: int = 12, timeout: float = TIMEOUT) -> FeedPage:
    raw_limit = _raw_limit(limit)
    query = urllib.parse.urlencode({"limit": raw_limit, "offset": offset})
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
    return FeedPage(
        items=items[:limit],
        has_more=len(results) >= raw_limit,
        next_offset=offset + raw_limit,
    )
