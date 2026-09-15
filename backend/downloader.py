from __future__ import annotations

from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Общие настройки: десктопные заголовки (обходим бот-троттлинг), ретраи и
# параллельные фрагменты — под убитым каналом скачивание либо идёт, либо
# быстро падает с понятной ошибкой вместо вечного зависания.
_BASE_OPTS: dict = {
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "socket_timeout": 30,
    "retries": 10,
    "fragment_retries": 10,
    "extractor_retries": 3,
    "concurrent_fragment_downloads": 4,
    "http_headers": {
        "User-Agent": _CHROME_UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    },
}

# Лучшие попытки по убыванию желательности. Вторая — прогрессивный
# цельный файл (без DASH-фрагментов): при троттлинге часто работает там,
# где bestvideo+bestaudio разваливается.
_FORMAT_CHAIN = [
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
    "best[ext=mp4]/best",
]


def download_youtube(url: str, out_path: str, progress_cb=None) -> dict:
    """Скачать видео по ссылке (YouTube и др. сайты, поддерживаемые yt-dlp).

    Пробует форматы по цепочке; возвращает dict с метаданными
    (title, duration, ext…). Если все попытки не удались — поднимает ошибку.
    """
    out_path = Path(out_path)
    hook = None
    if progress_cb:

        def _hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total:
                    progress_cb(min(1.0, d.get("downloaded_bytes", 0) / total))

        hook = _hook

    last_err: Exception | None = None
    for i, fmt in enumerate(_FORMAT_CHAIN):
        opts = dict(_BASE_OPTS)
        opts["format"] = fmt
        opts["outtmpl"] = str(out_path.with_suffix("")) + ".%(ext)s"
        if hook:
            opts["progress_hooks"] = [hook]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            produced = _locate_output(out_path, info)
            if produced is None:
                raise RuntimeError(f"Видео не было сохранено (попытка {i + 1})")
            if produced != out_path:
                produced.rename(out_path)
            return {
                "title": info.get("title"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "ext": info.get("ext"),
                "format_attempt": i + 1,
            }
        except DownloadError as exc:
            last_err = exc
            print(f"[downloader] attempt {i + 1} failed: {exc}")

    raise RuntimeError(f"Не удалось скачать видео (все форматы): {last_err}")


def _locate_output(out_path: Path, info: dict) -> Path | None:
    if out_path.exists():
        return out_path
    ext = Path(info.get("_filename") or "").suffix or ".mp4"
    candidate = out_path.with_suffix(ext)
    if candidate.exists():
        return candidate
    # yt-dlp может оставить файл с вставкой формата (например .f609.mp4)
    valid_suffixes = (".mp4", ".webm", ".mkv", ".mov", ".m4v")
    for p in sorted(out_path.parent.glob(out_path.stem + ".*")):
        if p.suffix.lower() in valid_suffixes and p.stat().st_size > 0:
            return p
    return None