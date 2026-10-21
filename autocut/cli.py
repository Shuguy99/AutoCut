from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .downloader import DownloadError, get_trending
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
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--ascii-slug", action="store_true")
    parser.add_argument(
        "--json", action="store_true", help="вывести результат в JSON"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autocut",
        description="Ссылка (YouTube, RuTube, …) или файл → вертикальные клипы",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="обработать ссылку или файл")
    run_parser.add_argument("source")
    _add_common(run_parser)

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
    return parser


def options_from_args(args: argparse.Namespace) -> JobOptions:
    return JobOptions(
        clips=args.clips,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        target_duration=args.target_duration,
        layout=args.layout,
        proxy=args.proxy,
        cookies=args.cookies,
        model=args.model,
        language=args.language,
        subtitles=args.subtitles,
    )


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "web":
        import uvicorn

        from .web.app import create_app

        config = _config_from_args(args)
        uvicorn.run(create_app(config), host=args.host, port=args.port)
        return 0

    config = _config_from_args(args)
    options = options_from_args(args)

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
        else:
            source = args.source
        result = run_pipeline(source, options, config, progress=progress)
    except (
        PipelineError, DownloadError, TranscriptionError, MediaError, RenderError
    ) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        return 130
    _print_result(result, args.json)
    return 0
