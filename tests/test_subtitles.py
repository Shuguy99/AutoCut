from pathlib import Path

from autocut.models import Word
from autocut.subtitles import build_ass, group_words, to_srt, write_ass


def _words(text: str, start: float = 0.0, step: float = 0.4) -> list[Word]:
    return [
        Word(start + i * step, start + i * step + 0.35, token)
        for i, token in enumerate(text.split())
    ]


def test_group_words_respects_limits():
    cues = group_words(_words("один два три четыре пять шесть семь"), max_words=3)
    assert cues
    assert all(len(c.text.replace("\n", " ").split()) <= 3 for c in cues)


def test_group_words_breaks_on_sentence_end():
    cues = group_words(_words("привет мир. как дела?"))
    assert len(cues) == 2
    assert cues[0].text.endswith(".")
    assert cues[1].text.endswith("?")


def test_group_words_wraps_two_lines():
    text = "очень длинное предложение из многих слов которое надо перенести"
    cues = group_words(_words(text), max_chars=20, max_words=10)
    assert all(len(c.text.splitlines()) <= 2 for c in cues)
    assert all(len(line) <= 20 for c in cues for line in c.text.splitlines())


def test_ass_shifts_and_formats():
    cues = group_words(_words("привет мир", start=10.0), max_words=5)
    ass = build_ass(cues, clip_start=10.0, clip_end=20.0)
    assert "PlayResX: 1080" in ass
    assert "Liberation Sans" in ass
    assert "Dialogue: 0,0:00:00.00," in ass


def test_ass_drops_cues_outside_clip():
    cues = group_words(_words("привет мир", start=30.0))
    ass = build_ass(cues, clip_start=0.0, clip_end=10.0)
    assert "Dialogue:" not in ass


def test_write_ass(tmp_path: Path):
    cues = group_words(_words("привет мир"))
    path = write_ass(cues, tmp_path / "subs.ass", 0.0, 5.0)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("[Script Info]")


def test_to_srt():
    cues = group_words(_words("привет мир"))
    srt = to_srt(cues)
    assert "00:00:00,000 -->" in srt
    assert "привет мир" in srt
