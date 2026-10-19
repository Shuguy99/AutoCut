import numpy as np

from autocut.models import Word
from autocut.scoring import find_highlights, sentence_boundaries


def _speech(duration: float, step: float = 0.5) -> list[Word]:
    return [
        Word(t, t + 0.45, "слово")
        for t in np.arange(0, duration, step)
    ]


def test_sentence_boundaries_includes_punctuation_and_pauses():
    words = [
        Word(0.0, 0.4, "привет"),
        Word(0.5, 0.9, "мир."),
        Word(2.0, 2.4, "как"),
        Word(2.5, 2.9, "дела?"),
    ]
    bounds = sentence_boundaries(words)
    assert 0.9 in bounds
    assert 2.9 in bounds


def test_highlights_find_loud_region():
    duration = 120.0
    rms = np.full(240, 0.03, dtype=np.float32)
    rms[100:160] = 0.8
    words = _speech(duration)
    clips = find_highlights(
        duration, rms, words, [], count=2,
        min_duration=20, max_duration=40, target_duration=30,
    )
    assert len(clips) == 2
    assert clips[0].start <= 55
    assert clips[0].end >= 75
    assert all(20 <= c.end - c.start <= 40 for c in clips)
    assert clips[0].score > clips[1].score


def test_highlights_do_not_overlap_heavily():
    duration = 90.0
    rms = np.ones(180, dtype=np.float32)
    clips = find_highlights(
        duration, rms, [], [], count=3,
        min_duration=20, max_duration=30, target_duration=25,
    )
    for index, first in enumerate(clips):
        for second in clips[index + 1:]:
            overlap = min(first.end, second.end) - max(first.start, second.start)
            assert overlap <= 0.3 * min(
                first.end - first.start, second.end - second.start
            )


def test_short_video_returns_single_clip():
    clips = find_highlights(
        10.0, np.ones(20), [], [], count=5,
        min_duration=20, max_duration=60, target_duration=30,
    )
    assert len(clips) == 1
    assert clips[0].start == 0
    assert clips[0].end == 10.0


def test_empty_transcript_still_returns_clips():
    clips = find_highlights(
        60.0, np.ones(120), [], [], count=2,
        min_duration=10, max_duration=30, target_duration=20,
    )
    assert clips
    assert all(c.parts["speech"] == 0 for c in clips)
