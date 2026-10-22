import json
from pathlib import Path

from autocut.models import Segment, Transcript, Word
from autocut.storage import (
    create_result_dir,
    load_transcript,
    save_transcript,
    slugify,
    write_srt,
)


def test_slugify_keeps_cyrillic():
    assert slugify("Привет, мир!") == "привет-мир"


def test_slugify_ascii_only_transliterates():
    assert slugify("Привет мир", ascii_only=True) == "privet-mir"


def test_slugify_empty_fallback():
    assert slugify("!!!") == "video"


def test_result_dir_unique(tmp_path: Path):
    first = create_result_dir(tmp_path, "Канал", "abc123", "Моё видео")
    second = create_result_dir(tmp_path, "Канал", "abc123", "Моё видео")
    assert first.name == "abc123_моё-видео"
    assert second.name == "abc123_моё-видео_2"
    assert (first / "clips").is_dir()


def test_result_dir_does_not_reuse_dir_without_clips(tmp_path: Path):
    existing = tmp_path / "канал" / "abc123_моё-видео"
    existing.mkdir(parents=True)
    created = create_result_dir(tmp_path, "Канал", "abc123", "Моё видео")
    assert created.name == "abc123_моё-видео_2"
    assert (created / "clips").is_dir()


def test_write_srt_creates_parent(tmp_path: Path):
    transcript = Transcript(
        language="ru",
        words=[Word(0.0, 0.5, "привет")],
        segments=[],
        text="привет",
    )
    path = tmp_path / "nested" / "out.srt"
    write_srt(transcript, path)
    assert path.exists()


def test_transcript_roundtrip(tmp_path: Path):
    transcript = Transcript(
        language="ru",
        words=[Word(0.0, 0.5, "привет")],
        segments=[Segment(0.0, 1.0, "привет мир")],
        text="привет мир",
    )
    path = tmp_path / "transcript.json"
    save_transcript(path, transcript)
    loaded = load_transcript(path)
    assert loaded.language == "ru"
    assert loaded.words[0].text == "привет"
    assert json.loads(path.read_text(encoding="utf-8"))["text"] == "привет мир"


def test_write_srt(tmp_path: Path):
    transcript = Transcript(
        language="ru",
        words=[
            Word(0.0, 0.4, "привет"),
            Word(0.5, 0.9, "мир."),
            Word(1.2, 1.6, "как"),
            Word(1.7, 2.0, "дела?"),
        ],
        segments=[],
        text="привет мир. как дела?",
    )
    path = tmp_path / "out.srt"
    write_srt(transcript, path)
    content = path.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:00,900" in content
    assert "привет мир." in content
