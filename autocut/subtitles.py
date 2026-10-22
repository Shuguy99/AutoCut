"""Группировка слов в реплики и генерация ASS/SRT."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

from .models import Word

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@dataclass
class Cue:
    start: float
    end: float
    text: str


def wrap_text(text: str, max_chars: int = 42, max_lines: int = 2) -> list[str]:
    lines = textwrap.wrap(
        text, width=max_chars, break_long_words=False, break_on_hyphens=False
    )
    return lines[:max_lines]


def group_words(
    words: list[Word],
    max_chars: int = 42,
    max_lines: int = 2,
    max_words: int = 5,
    max_duration: float = 4.0,
    pause: float = 0.6,
) -> list[Cue]:
    """Собирает слова в короткие реплики по пунктуации и паузам."""
    cues: list[Cue] = []
    current: list[Word] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(word.text for word in current).strip()
        lines = wrap_text(text, max_chars=max_chars, max_lines=max_lines)
        if lines:
            start = current[0].start
            end = max(current[-1].end, start + 0.8)
            cues.append(Cue(start, end, "\n".join(lines)))
        current.clear()

    for word in words:
        if current:
            gap = word.start - current[-1].end
            candidate = " ".join(w.text for w in current) + " " + word.text
            too_long = len(candidate) > max_chars * max_lines
            too_many = len(current) >= max_words
            too_slow = current[-1].end - current[0].start >= max_duration
            if gap > pause or too_long or too_many or too_slow:
                flush()
        current.append(word)
        if word.text.endswith((".", "!", "?", "…")) and len(current) >= 2:
            flush()
    flush()

    for index, cue in enumerate(cues[:-1]):
        next_start = cues[index + 1].start
        if cue.end > next_start:
            cue.end = max(cue.start + 0.3, next_start)
    return cues


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_escape(text: str) -> str:
    value = text.replace("\\", "").replace("{", "").replace("}", "")
    return value.replace("\n", r"\N")


def build_ass(
    cues: list[Cue],
    clip_start: float,
    clip_end: float,
    font: str = "Liberation Sans",
    font_size: int = 48,
    margin_v: int = 230,
) -> str:
    """Собирает ASS с таймингами, сдвинутыми к началу клипа."""
    header = ASS_HEADER.format(font=font, size=font_size, margin=margin_v)
    events: list[str] = []
    for cue in cues:
        start = max(cue.start, clip_start)
        end = min(cue.end, clip_end)
        if end - start <= 0.05:
            continue
        events.append(
            f"Dialogue: 0,{_ass_time(start - clip_start)},"
            f"{_ass_time(end - clip_start)},Default,,0,0,0,,"
            f"{_ass_escape(cue.text)}"
        )
    return header + "\n".join(events) + "\n"


def write_ass(
    cues: list[Cue],
    path: Path,
    clip_start: float,
    clip_end: float,
    **kwargs,
) -> Path:
    """Пишет ASS-файл и создаёт родительскую папку."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_ass(cues, clip_start, clip_end, **kwargs), encoding="utf-8"
    )
    return path


def _srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    """Преобразует реплики в SRT (для отладки и внешних редакторов)."""
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        text = cue.text.replace("\n", " ")
        blocks.append(
            f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{text}\n"
        )
    return "\n".join(blocks)
