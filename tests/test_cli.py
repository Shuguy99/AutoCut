import pytest

from autocut import cli
from autocut.cli import build_parser, options_from_args
from autocut.models import JobOptions, PlaylistInfo, PlaylistItem


def test_run_defaults():
    args = build_parser().parse_args(["run", "video.mp4"])
    assert args.source == "video.mp4"
    assert args.clips == 5
    assert args.min_duration == 20
    assert args.max_duration == 60
    assert args.layout == "blur"


def test_job_options_from_args():
    args = build_parser().parse_args([
        "run", "video.mp4", "--clips", "3", "--min", "15", "--max", "45",
        "--target", "25", "--format", "crop", "--proxy", "socks5://x:1",
    ])
    options = options_from_args(args)
    assert isinstance(options, JobOptions)
    assert options.clips == 3
    assert options.layout == "crop"
    assert options.target_duration == 25


def test_web_defaults():
    args = build_parser().parse_args(["web"])
    assert args.host == "127.0.0.1"
    assert args.port == 8000


def test_no_subtitles_flag():
    args = build_parser().parse_args(["run", "video.mp4", "--no-subtitles"])
    assert args.subtitles is False
    assert options_from_args(args).subtitles is False


def test_uniqueness_defaults():
    options = options_from_args(
        build_parser().parse_args(["run", "video.mp4"])
    )
    assert options.variation == "subtle"
    assert options.style == "auto"
    assert options.caption_mode == "phrase"
    assert options.hook is True
    assert options.end_card is True
    assert options.loudnorm is True
    assert options.safe_zones is True
    assert options.watermark is None


def test_uniqueness_flags():
    args = build_parser().parse_args([
        "run", "video.mp4",
        "--variation", "strong",
        "--style", "karaoke",
        "--caption-mode", "word",
        "--watermark", " @nick ",
        "--no-hook",
        "--no-end-card",
        "--no-loudnorm",
        "--no-safe-zones",
    ])
    options = options_from_args(args)
    assert options.variation == "strong"
    assert options.style == "karaoke"
    assert options.caption_mode == "word"
    assert options.watermark == "@nick"
    assert options.hook is False
    assert options.end_card is False
    assert options.loudnorm is False
    assert options.safe_zones is False


def test_app_defaults():
    args = build_parser().parse_args(["app"])
    assert args.host == "127.0.0.1"
    assert args.port == 0
    assert args.browser == "auto"


def test_invalid_clips_are_reported_without_traceback(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "video.mp4", "--clips", "0", "--output", str(tmp_path)])
    assert exc.value.code == 2


def test_invalid_duration_range_is_reported_without_traceback(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "run", "video.mp4", "--min", "70", "--max", "30",
            "--output", str(tmp_path),
        ])
    assert exc.value.code == 2


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
