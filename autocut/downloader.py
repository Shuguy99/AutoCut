"""Скачивание видео через yt-dlp и подготовка локальных файлов."""

from __future__ import annotations

import hashlib
from pathlib import Path

from yt_dlp import YoutubeDL

from .media import probe
from .models import PlaylistInfo, PlaylistItem, SourceInfo

MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts",
}


class DownloadError(RuntimeError):
    pass


class NotAPlaylistError(DownloadError):
    pass


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _safe_duration(value) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def _opts(**extra) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "playlistend": 10,
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
    }
    opts.update(extra)
    return opts


def download(
    url: str,
    dest_dir: Path,
    proxy: str | None = None,
    cookies: str | Path | None = None,
    max_height: int = 1080,
) -> SourceInfo:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = _opts(
        outtmpl=str(dest_dir / "source.%(ext)s"),
        format=f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b",
    )
    if proxy:
        opts["proxy"] = proxy
    if cookies:
        opts["cookiefile"] = str(cookies)

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise DownloadError(f"не удалось скачать видео: {exc}") from exc

    if not info:
        raise DownloadError("yt-dlp не вернул метаданные видео")

    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise DownloadError("плейлист не содержит видео")
        info = entries[0]

    files = [
        path
        for path in dest_dir.glob("source.*")
        if path.is_file() and not path.name.endswith(".part")
    ]
    media_files = [path for path in files if path.suffix.lower() in MEDIA_SUFFIXES]
    if not media_files:
        raise DownloadError("скачивание завершилось, но видеофайл не найден")
    media_files.sort(
        key=lambda path: (path.suffix.lower() == ".mp4", path.stat().st_size),
        reverse=True,
    )
    source_path = media_files[0]

    duration = _safe_duration(info.get("duration"))
    if duration is None:
        duration = probe(source_path).duration

    return SourceInfo(
        video_id=str(info.get("id") or "video"),
        title=str(info.get("title") or "Без названия"),
        channel=str(info.get("channel") or info.get("uploader") or "unknown"),
        duration=duration,
        webpage_url=str(info.get("webpage_url") or url),
        source_path=source_path,
        view_count=info.get("view_count"),
    )


def prepare_local(path: str | Path, dest_dir: Path | None = None) -> SourceInfo:
    """Проверяет локальный файл и собирает метаданные.

    ``dest_dir`` оставлен для совместимости: локальный файл обрабатывается
    на месте и не копируется в рабочую папку.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise DownloadError(f"файл не найден: {source}")
    media = probe(source)
    digest = hashlib.sha1(
        f"{source}:{source.stat().st_mtime}".encode("utf-8")
    ).hexdigest()[:10]
    return SourceInfo(
        video_id=f"local_{digest}",
        title=source.stem,
        channel="local",
        duration=media.duration,
        webpage_url=source.as_uri(),
        source_path=source,
        view_count=None,
    )


def get_trending(
    region: str = "RU",
    proxy: str | None = None,
    cookies: str | Path | None = None,
) -> str:
    """Возвращает ссылку на верхнее видео ленты популярного YouTube."""
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    opts = _opts(extract_flat=True, format=None, noplaylist=False)
    if proxy:
        opts["proxy"] = proxy
    if cookies:
        opts["cookiefile"] = str(cookies)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise DownloadError(
            f"не удалось получить ленту популярного: {exc}"
        ) from exc
    entries = info.get("entries") or []
    if not entries:
        raise DownloadError("лента популярного пуста или недоступна")
    entry = entries[0]
    link = entry.get("webpage_url") or entry.get("url")
    if link and link.startswith("http"):
        return link
    video_id = entry.get("id")
    if not video_id:
        raise DownloadError("не удалось определить видео из ленты")
    return f"https://www.youtube.com/watch?v={video_id}"


def list_playlist(
    url: str,
    limit: int = 30,
    proxy: str | None = None,
    cookies: str | Path | None = None,
) -> PlaylistInfo:
    """Возвращает первые ``limit`` видео плейлиста без скачивания.

    Используется flat-извлечение yt-dlp: быстро, но длительность и превью
    могут отсутствовать.
    """
    limit = max(1, int(limit))
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
        duration = _safe_duration(entry.get("duration"))
        items.append(
            PlaylistItem(
                video_id=str(video_id),
                title=str(entry.get("title") or "Без названия"),
                channel=str(
                    entry.get("channel")
                    or entry.get("uploader")
                    or playlist_channel
                ),
                duration=duration,
                url=str(link),
                thumbnail=entry.get("thumbnail"),
            )
        )

    if not items:
        raise NotAPlaylistError("в плейлисте нет доступных видео")
    filled = sum(1 for entry in entries if entry)
    return PlaylistInfo(
        title=playlist_title,
        items=items,
        truncated=filled >= limit,
    )
