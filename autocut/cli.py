"""Командная строка AutoCut: run, trending, web, app."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import load_config
from .downloader import (
    DownloadError,
    NotAPlaylistError,
    get_trending,
    is_url,
    list_playlist,
)
from .media import MediaError
from .models import JobOptions
from .pipeline import PipelineError, run_pipeline
from .render import RenderError
from .transcribe import TranscriptionError


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--clips", type=int, default=5, help="сколько клипов сделать"
    )
    parser.add_argument("--min", dest="min_duration", type=float, default=20)
    parser.add_argument("--max", dest="max_duration", type=float, default=60)
    parser.add_argument(
        "--target", dest="target_duration", type=float, default=30
    )
    parser.add_argument(
        "--format", dest="layout", choices=["blur", "crop"], default="blur"
    )
    parser.add_argument(
        "--crop-focus", choices=["center", "left", "right"], default="center",
        help="куда смещать кадр при кропе: центр, левее или правее",
    )
    parser.add_argument(
        "--model", default=None,
        help="модель Whisper (tiny/base/small/medium)",
    )
    parser.add_argument("--language", default=None, help="язык речи (ru/en/...)")
    parser.add_argument("--proxy", default=None)
    parser.add_argument("--cookies", default=None)
    parser.add_argument("--output", default=None, help="папка результатов")
    parser.add_argument("--config", default=None, help="путь к config.yaml")
    parser.add_argument(
        "--no-subtitles", dest="subtitles", action="store_false",
        help="не вжигать субтитры в клипы",
    )
    parser.add_argument(
        "--variation", choices=["off", "subtle", "strong"], default="subtle",
        help="вариативность стиля и кадрирования клипов",
    )
    parser.add_argument(
        "--style",
        choices=["auto", "clean", "bold", "karaoke", "minimal"],
        default="auto", help="стиль субтитров (auto — чередовать)",
    )
    parser.add_argument(
        "--caption-mode", choices=["phrase", "word"], default="phrase",
        help="показывать фразы или подсвечивать слова",
    )
    parser.add_argument(
        "--watermark", default=None, help="водяной знак, например @nick",
    )
    parser.add_argument(
        "--no-hook", dest="hook", action="store_false",
        help="не показывать хук в первые секунды",
    )
    parser.add_argument(
        "--no-end-card", dest="end_card", action="store_false",
        help="не показывать финальную плашку",
    )
    parser.add_argument(
        "--no-loudnorm", dest="loudnorm", action="store_false",
        help="не нормализовать громкость под TikTok",
    )
    parser.add_argument(
        "--no-safe-zones", dest="safe_zones", action="store_false",
        help="не поднимать субтитры над интерфейсом TikTok",
    )
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--ascii-slug", action="store_true")
    parser.add_argument(
        "--json", action="store_true", help="вывести результат в JSON"
    )


def build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер команд run/trending/web/app."""
    parser = argparse.ArgumentParser(
        prog="autocut",
        description="Ссылка (YouTube, RuTube, …) или файл → вертикальные клипы",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="обработать ссылку или файл")
    run_parser.add_argument("source")
    _add_common(run_parser)
    run_parser.add_argument(
        "--playlist-limit",
        type=int,
        default=1,
        metavar="N",
        help="сколько видео из плейлиста обработать (1–50)",
    )

    trending = sub.add_parser(
        "trending", help="взять верхнее видео из ленты популярного YouTube"
    )
    trending.add_argument("--region", default="RU")
    _add_common(trending)

    web = sub.add_parser("web", help="запустить веб-интерфейс")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--config", default=None)
    web.add_argument("--output", default=None)

    app = sub.add_parser(
        "app", help="открыть веб-интерфейс в отдельном окне приложения"
    )
    app.add_argument("--host", default="127.0.0.1")
    app.add_argument(
        "--port", type=int, default=0,
        help="0 — выбрать свободный порт автоматически",
    )
    app.add_argument("--config", default=None)
    app.add_argument("--output", default=None)
    app.add_argument(
        "--browser", choices=["auto", "chrome", "firefox", "default"],
        default="auto", help="чем открыть окно приложения",
    )
    return parser


def options_from_args(args: argparse.Namespace) -> JobOptions:
    """Превращает аргументы argparse в валидированные `JobOptions`."""
    return JobOptions(
        clips=args.clips,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        target_duration=args.target_duration,
        layout=args.layout,
        crop_focus=args.crop_focus,
        subtitles=args.subtitles,
        variation=args.variation,
        style=args.style,
        caption_mode=args.caption_mode,
        hook=args.hook,
        end_card=args.end_card,
        watermark=args.watermark,
        loudnorm=args.loudnorm,
        safe_zones=args.safe_zones,
        proxy=args.proxy,
        cookies=args.cookies,
        model=args.model,
        language=args.language,
    )


def _validation_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors():
            location = ".".join(str(item) for item in error.get("loc", ()))
            parts.append(f"{location}: {error.get('msg', '')}".strip(": "))
        return "; ".join(parts) or str(exc)
    return str(exc)


def _config_from_args(args: argparse.Namespace):
    return load_config(
        Path(args.config) if args.config else None,
        output_dir=args.output,
        keep_work=True if getattr(args, "keep_work", False) else None,
        ascii_slug=True if getattr(args, "ascii_slug", False) else None,
    )


def _print_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("\nГотово:", result["result_dir"])
    for clip in result["clips"]:
        if "file" not in clip:
            print(f"  {clip['index']:02d}. ОШИБКА: {clip.get('error', '')}")
            continue
        print(
            f"  {clip['index']:02d}. {clip['start']:7.1f}–{clip['end']:7.1f} с"
            f"  score {clip['score']:.2f}  {clip['file']}"
        )


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
    results = []
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
        results.append(result)
        if not args.json:
            _print_result(result, False)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))

    done = len(playlist.items) - failures
    print(
        f"\nОбработано {done} из {len(playlist.items)}", file=sys.stderr
    )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    playlist_limit = getattr(args, "playlist_limit", 1)
    if not 1 <= playlist_limit <= 50:
        parser.error("--playlist-limit должен быть от 1 до 50")

    if args.command == "web":
        import uvicorn

        from .web.app import create_app

        try:
            config = _config_from_args(args)
        except ValueError as exc:
            parser.error(_validation_message(exc))
        uvicorn.run(create_app(config), host=args.host, port=args.port)
        return 0

    if args.command == "app":
        from .desktop import run_desktop_app

        try:
            config = _config_from_args(args)
        except ValueError as exc:
            parser.error(_validation_message(exc))
        return run_desktop_app(
            config, host=args.host, port=args.port, browser=args.browser
        )

    try:
        config = _config_from_args(args)
        options = options_from_args(args)
    except (ValidationError, ValueError) as exc:
        parser.error(_validation_message(exc))

    def progress(stage: str, percent: float, message: str) -> None:
        print(f"[{stage}] {percent:5.1f}% {message}", file=sys.stderr)

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
    _print_result(result, args.json)
    return 0


def main_app(argv: list[str] | None = None) -> int:
    """Точка входа ``autocut-app``: сразу открывает настольное окно."""
    return main(["app", *(sys.argv[1:] if argv is None else argv)])
