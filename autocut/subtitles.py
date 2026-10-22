"""Группировка слов в реплики и генерация ASS/SRT."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, replace
from pathlib import Path

from .models import Word


@dataclass(frozen=True)
class StylePreset:
    """Оформление субтитров и текстовых плашек."""

    name: str
    font: str = "Liberation Sans"
    font_size: int = 48
    primary: str = "#FFFFFF"
    secondary: str = "#4DE2C5"
    outline: str = "#000000"
    back: str = "#000000"
    bold: bool = True
    uppercase: bool = False
    margin_v: int = 230
    alignment: int = 2
    karaoke: bool = False


STYLES: dict[str, StylePreset] = {
    "clean": StylePreset("clean"),
    "bold": StylePreset(
        "bold", font="DejaVu Sans", font_size=60, primary="#FFE14D",
        secondary="#FFFFFF", bold=True, uppercase=True, margin_v=320,
    ),
    "karaoke": StylePreset(
        "karaoke", font="DejaVu Sans", font_size=56, primary="#FFFFFF",
        secondary="#4DE2C5", bold=True, margin_v=320, karaoke=True,
    ),
    "minimal": StylePreset(
        "minimal", font="Liberation Sans", font_size=44, bold=False,
        margin_v=280,
    ),
}

HOOK_STYLE = StylePreset(
    "hook", font="DejaVu Sans", font_size=64, primary="#FFFFFF",
    outline="#000000", bold=True, uppercase=False, alignment=8,
    margin_v=170,
)
END_CARD_STYLE = StylePreset(
    "end_card", font="DejaVu Sans", font_size=52, primary="#FFE14D",
    outline="#000000", bold=True, uppercase=False, alignment=5, margin_v=0,
)
WATERMARK_STYLE = StylePreset(
    "watermark", font="DejaVu Sans", font_size=32, primary="#FFFFFF",
    outline="#000000", bold=True, uppercase=False, alignment=7,
    margin_v=70,
)


@dataclass
class Cue:
    start: float
    end: float
    text: str


def get_style(name: str | None) -> StylePreset:
    """Возвращает пресет по имени, неизвестное имя — clean."""
    return STYLES.get(name or "clean", STYLES["clean"])


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


def _ass_color(value: str, alpha: int = 0) -> str:
    value = value.lstrip("#")
    if len(value) != 6:
        value = "FFFFFF"
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"&H{alpha:02X}{blue:02X}{green:02X}{red:02X}"


def _ass_escape(text: str) -> str:
    value = text.replace("\\", "").replace("{", "").replace("}", "")
    return value.replace("\n", r"\N")


def _style_line(
    name: str,
    preset: StylePreset,
    *,
    margin_v: int | None = None,
    alignment: int | None = None,
    margin_l: int = 60,
    margin_r: int = 60,
    alpha: int = 0,
) -> str:
    bold = -1 if preset.bold else 0
    primary = _ass_color(preset.primary, alpha)
    secondary = _ass_color(preset.secondary, alpha)
    outline = _ass_color(preset.outline, alpha)
    back = _ass_color(preset.back, min(255, alpha + 128))
    return (
        f"Style: {name},{preset.font},{preset.font_size},{primary},"
        f"{secondary},{outline},{back},{bold},0,0,0,100,100,0,0,1,4,1,"
        f"{alignment if alignment is not None else preset.alignment},"
        f"{margin_l},{margin_r},"
        f"{margin_v if margin_v is not None else preset.margin_v},1"
    )


def _header(
    preset: StylePreset, *, safe_zones: bool
) -> str:
    caption_margin = max(preset.margin_v, 310) if safe_zones else preset.margin_v
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        _style_line("Default", preset, margin_v=caption_margin),
        _style_line("Hook", HOOK_STYLE),
        _style_line("EndCard", END_CARD_STYLE),
        _style_line("Watermark", WATERMARK_STYLE, margin_l=40, margin_r=40,
                    alpha=0x60),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ]
    return "\n".join(lines) + "\n"


def _phrase_events(
    cues: list[Cue],
    clip_start: float,
    clip_end: float,
    preset: StylePreset,
) -> list[tuple[float, str]]:
    events: list[tuple[float, str]] = []
    for cue in cues:
        start = max(cue.start, clip_start)
        end = min(cue.end, clip_end)
        if end - start <= 0.05:
            continue
        text = cue.text.upper() if preset.uppercase else cue.text
        events.append((
            start - clip_start,
            f"Dialogue: 0,{_ass_time(start - clip_start)},"
            f"{_ass_time(end - clip_start)},Default,,0,0,0,,"
            f"{_ass_escape(text)}",
        ))
    return events


def _word_groups(words: list[Word], max_words: int = 3) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current:
            gap = word.start - current[-1].end
            if (
                gap > 0.45
                or len(current) >= max_words
                or current[-1].text.endswith((".", "!", "?", "…"))
            ):
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _word_events(
    words: list[Word],
    clip_start: float,
    clip_end: float,
    preset: StylePreset,
) -> list[tuple[float, str]]:
    events: list[tuple[float, str]] = []
    active_color = _ass_color(preset.secondary)
    base_color = _ass_color(preset.primary)

    for group in _word_groups(words):
        for index, word in enumerate(group):
            start = max(word.start, clip_start)
            next_start = (
                group[index + 1].start if index + 1 < len(group)
                else word.end + 0.12
            )
            end = min(next_start, clip_end)
            if end - start <= 0.05:
                continue
            parts = []
            for position, item in enumerate(group):
                text = item.text.upper() if preset.uppercase else item.text
                escaped = _ass_escape(text)
                if position == index:
                    parts.append(
                        f"{{\\c{active_color}&}}{escaped}"
                        f"{{\\c{base_color}&}}"
                    )
                else:
                    parts.append(escaped)
            events.append((
                start - clip_start,
                f"Dialogue: 0,{_ass_time(start - clip_start)},"
                f"{_ass_time(end - clip_start)},Default,,0,0,0,,"
                f"{' '.join(parts)}",
            ))
    return events


def _overlay_event(
    start: float,
    end: float,
    style: str,
    text: str,
    fade: str = "",
) -> tuple[float, str] | None:
    if end - start <= 0.1 or not text.strip():
        return None
    prefix = f"{{{fade}}}" if fade else ""
    return (
        start,
        f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,"
        f"{prefix}{_ass_escape(text)}",
    )


def build_ass(
    cues: list[Cue],
    clip_start: float,
    clip_end: float,
    font: str | None = None,
    font_size: int | None = None,
    margin_v: int | None = None,
    style: StylePreset | None = None,
    hook: str | None = None,
    end_card: str | None = None,
    watermark: str | None = None,
    safe_zones: bool = False,
    words: list[Word] | None = None,
    caption_mode: str = "phrase",
) -> str:
    """Собирает ASS с субтитрами, хуком, концовкой и водяным знаком.

    Тайминги сдвигаются к началу клипа. ``words`` нужен для режима
    ``caption_mode="word"``; без него используется обычная группировка.
    """
    preset = style or STYLES["clean"]
    if font is not None or font_size is not None or margin_v is not None:
        preset = replace(
            preset,
            font=font or preset.font,
            font_size=font_size or preset.font_size,
            margin_v=margin_v if margin_v is not None else preset.margin_v,
        )
    duration = max(0.0, clip_end - clip_start)
    events: list[tuple[float, str]] = []

    if caption_mode == "word" and words:
        events.extend(_word_events(words, clip_start, clip_end, preset))
    else:
        events.extend(_phrase_events(cues, clip_start, clip_end, preset))

    if hook:
        hook_end = min(duration * 0.6, 2.8)
        event = _overlay_event(0.0, hook_end, "Hook", hook, r"\fad(120,180)")
        if event:
            events.append(event)

    if end_card and duration > 1.2:
        start = max(0.0, duration - min(1.8, duration * 0.35))
        event = _overlay_event(
            start, duration, "EndCard", end_card, r"\fad(150,0)"
        )
        if event:
            events.append(event)

    if watermark:
        event = _overlay_event(0.0, duration, "Watermark", watermark)
        if event:
            events.append(event)

    events.sort(key=lambda item: item[0])
    body = "\n".join(line for _, line in events)
    return _header(preset, safe_zones=safe_zones) + body + "\n"


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
