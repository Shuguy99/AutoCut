from pathlib import Path

from autocut.media import probe
from autocut.models import Word
from autocut.render import render_clip, render_preview
from autocut.subtitles import group_words, write_ass
from autocut.variation import Grade


def test_render_blur_clip(sample_video: Path, tmp_path: Path):
    cues = group_words(
        [Word(0.2, 0.6, "привет"), Word(0.7, 1.1, "мир")],
        max_words=5,
    )
    ass = write_ass(cues, tmp_path / "subs.ass", 0.0, 3.0)
    out = render_clip(
        sample_video, 0.0, 3.0, ass, tmp_path / "clip.mp4", layout="blur"
    )
    info = probe(out)
    assert info.width == 1080
    assert info.height == 1920
    assert 2.5 <= info.duration <= 3.5
    assert info.has_audio is True
    assert out.stat().st_size > 10_000


def test_render_crop_clip(sample_video: Path, tmp_path: Path):
    cues = []
    ass = write_ass(cues, tmp_path / "empty.ass", 0.0, 2.0)
    out = render_clip(
        sample_video, 1.0, 3.0, ass, tmp_path / "crop.mp4", layout="crop"
    )
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)


def test_render_preview(sample_video: Path, tmp_path: Path):
    out = render_preview(sample_video, tmp_path / "preview.jpg")
    assert out.exists() and out.stat().st_size > 1000


def test_render_with_zoom_grade_and_pan(sample_video: Path, tmp_path: Path):
    cues = group_words([Word(0.2, 0.8, "тест")])
    ass = write_ass(cues, tmp_path / "subs.ass", 0.0, 3.0)
    out = render_clip(
        sample_video, 0.0, 3.0, ass, tmp_path / "styled.mp4",
        layout="crop",
        zoom=1.05,
        pan=(0.12, -0.08),
        grade=Grade(contrast=1.05, saturation=1.08, brightness=0.01),
        loudnorm=False,
    )
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert 2.5 <= info.duration <= 3.5
    assert out.stat().st_size > 10_000
