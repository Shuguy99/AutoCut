from autocut.cli import build_parser, options_from_args
from autocut.models import JobOptions


def test_run_defaults():
    args = build_parser().parse_args(["run", "video.mp4"])
    assert args.source == "video.mp4"
    assert args.clips == 5
    assert args.min_duration == 20
    assert args.max_duration == 60
    assert args.layout == "blur"
    assert args.subtitles is True


def test_run_no_subtitles_flag():
    args = build_parser().parse_args(["run", "video.mp4", "--no-subtitles"])
    assert args.subtitles is False
    assert options_from_args(args).subtitles is False


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
