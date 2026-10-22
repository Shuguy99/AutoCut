"""Модели данных AutoCut: транскрипт, источники и параметры задачи."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    words: list[Word]
    segments: list[Segment]
    text: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        return cls(
            language=data.get("language", "unknown"),
            words=[Word(**w) for w in data.get("words", [])],
            segments=[Segment(**s) for s in data.get("segments", [])],
            text=data.get("text", ""),
        )


@dataclass
class ClipCandidate:
    start: float
    end: float
    score: float
    parts: dict[str, float] = field(default_factory=dict)


@dataclass
class SourceInfo:
    video_id: str
    title: str
    channel: str
    duration: float
    webpage_url: str
    source_path: Path
    view_count: int | None = None


@dataclass
class PlaylistItem:
    video_id: str
    title: str
    channel: str
    duration: float | None
    url: str
    thumbnail: str | None = None


@dataclass
class PlaylistInfo:
    title: str
    items: list[PlaylistItem]
    truncated: bool = False


class JobOptions(BaseModel):
    """Параметры одной задачи нарезки."""

    clips: int = Field(5, ge=1, le=50)
    preset: Literal[
        "custom", "podcast", "talking_head", "cinematic", "shorts"
    ] = "custom"
    min_duration: float = Field(20, ge=1, le=120)
    max_duration: float = Field(60, ge=1, le=180)
    target_duration: float = Field(30, ge=1, le=120)
    ranges: list[tuple[float, float]] | None = Field(
        default=None, max_length=50
    )
    layout: Literal["blur", "crop"] = "blur"
    crop_focus: Literal["center", "left", "right"] = "center"
    subtitles: bool = True
    variation: Literal["off", "subtle", "strong"] = "subtle"
    style: Literal["auto", "clean", "bold", "karaoke", "minimal"] = "auto"
    caption_mode: Literal["phrase", "word"] = "phrase"
    hook: bool = True
    end_card: bool = True
    watermark: str | None = Field(default=None, max_length=40)
    loudnorm: bool = True
    safe_zones: bool = True
    proxy: str | None = None
    cookies: str | None = None
    model: str | None = None
    language: str | None = None

    @field_validator("ranges")
    @classmethod
    def _clean_ranges(
        cls, value: list[tuple[float, float]] | None
    ) -> list[tuple[float, float]] | None:
        if value is None:
            return None
        cleaned: list[tuple[float, float]] = []
        for item in value:
            try:
                start, end = item
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "диапазон должен быть парой start-end"
                ) from exc
            try:
                start, end = float(start), float(end)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "начало и конец диапазона должны быть числами"
                ) from exc
            if start < 0 or end <= start:
                raise ValueError(
                    f"некорректный диапазон {start:g}–{end:g}"
                )
            length = end - start
            if length < 1 or length > 300:
                raise ValueError(
                    "длина ручного диапазона должна быть от 1 до 300 секунд"
                )
            cleaned.append((start, end))
        return cleaned or None

    @field_validator("watermark")
    @classmethod
    def _clean_watermark(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def _validate(self) -> "JobOptions":
        if self.min_duration > self.max_duration:
            raise ValueError("min_duration не может быть больше max_duration")
        self.target_duration = min(
            max(self.target_duration, self.min_duration), self.max_duration
        )
        return self
