from __future__ import annotations

import hashlib
from pathlib import Path

from yt_dlp import YoutubeDL

from .media import probe
from .models import SourceInfo


class DownloadError(RuntimeError):
    pass


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


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

    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise DownloadError("плейлист не содержит видео")
        info = entries[0]

    files = sorted(dest_dir.glob("source.*"))
    if not files:
        raise DownloadError("скачивание завершилось, но файл не найден")
    files.sort(key=lambda p: p.suffix == ".mp4", reverse=True)
    source_path = files[0]

    return SourceInfo(
        video_id=str(info.get("id") or "video"),
        title=str(info.get("title") or "Без названия"),
        channel=str(info.get("channel") or info.get("uploader") or "unknown"),
        duration=float(info.get("duration") or probe(source_path).duration),
        webpage_url=str(info.get("webpage_url") or url),
        source_path=source_path,
        view_count=info.get("view_count"),
    )


def prepare_local(path: str | Path, dest_dir: Path | None = None) -> SourceInfo:
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
