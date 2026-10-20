from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    clips: int = Field(5, ge=1, le=50)
    min_duration: float = Field(20, ge=1, le=120)
    max_duration: float = Field(60, ge=1, le=180)
    target_duration: float = Field(30, ge=1, le=120)
    layout: Literal["blur", "crop"] = "blur"
    proxy: str | None = None
    cookies: str | None = None
    model: str | None = None
    language: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "JobOptions":
        if self.min_duration > self.max_duration:
            raise ValueError("min_duration не может быть больше max_duration")
        self.target_duration = min(
            max(self.target_duration, self.min_duration), self.max_duration
        )
        return self
