"""Вариативность клипов: стили, хуки, брендинг и проверка похожести.

Модуль не пытается «обмануть» алгоритмы платформы. Он делает клипы из одной
пачки визуально и текстово разными, чтобы пользователь не публиковал несколько
почти одинаковых роликов подряд.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import asdict, dataclass

from .models import JobOptions

STYLE_NAMES = ("clean", "bold", "karaoke", "minimal")

_FILLERS = {
    "а", "вот", "вообще", "значит", "и", "как", "короче", "ну", "просто",
    "смотри", "слушай", "так", "типа", "э", "эм",
}

_STOPWORDS = {
    "about", "after", "again", "also", "because", "been", "before", "being",
    "бы", "был", "была", "были", "быть", "весь", "вот", "все", "всё", "где",
    "для", "его", "если", "есть", "ещё", "еще", "или", "как", "когда", "кто",
    "ли", "мне", "может", "мы", "над", "надо", "наш", "не", "него", "нее",
    "нет", "ни", "них", "но", "ну", "о", "об", "один", "она", "они", "оно",
    "при", "про", "с", "сам", "сво", "себе", "так", "там", "те", "тем", "то",
    "того", "тоже", "той", "только", "том", "ты", "у", "уже", "чего", "чей",
    "чем", "что", "чтобы", "эта", "эти", "это", "этот", "я",
}

_END_CARDS = (
    "Ещё больше в профиле",
    "Продолжение в профиле",
    "Подпишись, чтобы не пропустить",
    "Смотри другие клипы в профиле",
)


@dataclass(frozen=True)
class Grade:
    """Параметры цветокоррекции для ffmpeg ``eq``."""

    contrast: float = 1.0
    saturation: float = 1.0
    brightness: float = 0.0
    gamma: float = 1.0

    @property
    def enabled(self) -> bool:
        return (
            abs(self.contrast - 1.0) > 1e-3
            or abs(self.saturation - 1.0) > 1e-3
            or abs(self.brightness) > 1e-4
            or abs(self.gamma - 1.0) > 1e-3
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ClipVariant:
    """Индивидуальные параметры одного клипа."""

    index: int
    style: str
    zoom: float
    pan_x: float
    pan_y: float
    grade: Grade
    hook: str | None
    end_card: str | None
    watermark: str | None

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "style": self.style,
            "zoom": round(self.zoom, 4),
            "pan_x": round(self.pan_x, 4),
            "pan_y": round(self.pan_y, 4),
            "grade": self.grade.to_dict(),
            "hook": self.hook,
            "end_card": self.end_card,
            "watermark": self.watermark,
        }


def _rng(seed: str, index: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{index}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _normalize_word(value: str) -> str:
    return re.sub(r"[^\wа-яё]", "", value.lower(), flags=re.IGNORECASE)


def _pick_style(
    requested: str, variation: str, index: int, rng: random.Random,
    previous: str | None,
) -> str:
    if requested != "auto":
        return requested
    if variation == "off":
        return "clean"
    choice = STYLE_NAMES[rng.randrange(len(STYLE_NAMES))]
    if previous is not None and choice == previous:
        choice = STYLE_NAMES[(STYLE_NAMES.index(choice) + 1) % len(STYLE_NAMES)]
    return choice


def extract_hook(
    text: str, max_words: int = 8, max_chars: int = 48
) -> str | None:
    """Берёт короткую фразу из начала клипа для верхней плашки."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return None
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    hook = sentences[0].strip()
    if len(hook) < 12 and len(sentences) > 1:
        hook = f"{hook} {sentences[1]}".strip()

    words = hook.split()
    while words and _normalize_word(words[0]) in _FILLERS:
        words.pop(0)
    if len(words) < 2:
        return None

    truncated = False
    if len(words) > max_words:
        words = words[:max_words]
        truncated = True
    value = " ".join(words).strip(" ,;:—-")
    if len(value) > max_chars:
        clipped = []
        for word in words:
            candidate = " ".join([*clipped, word])
            if len(candidate) > max_chars:
                break
            clipped.append(word)
        if clipped:
            value = " ".join(clipped)
        else:
            value = value[:max_chars].rstrip()
        truncated = True
    if truncated:
        value = value.rstrip(".,!?…:;—-") + "…"
    return value or None


def _end_card(watermark: str | None, rng: random.Random) -> str:
    text = rng.choice(_END_CARDS)
    if watermark:
        return f"{text}\n{watermark}"
    return text


def _grade(variation: str, rng: random.Random) -> Grade:
    if variation == "strong":
        return Grade(
            contrast=round(rng.uniform(1.04, 1.08), 3),
            saturation=round(rng.uniform(1.06, 1.12), 3),
            brightness=round(rng.uniform(-0.01, 0.01), 4),
            gamma=round(rng.uniform(0.97, 1.03), 3),
        )
    if variation == "subtle":
        return Grade(
            contrast=round(rng.uniform(1.02, 1.04), 3),
            saturation=round(rng.uniform(1.02, 1.05), 3),
            brightness=round(rng.uniform(-0.005, 0.005), 4),
            gamma=round(rng.uniform(0.99, 1.01), 3),
        )
    return Grade()


def build_variants(
    source_id: str,
    job_id: str,
    options: JobOptions,
    texts: list[str],
) -> list[ClipVariant]:
    """Создаёт варианты оформления для каждого клипа.

    Результат детерминирован для пары ``source_id`` + ``job_id``: повторный
    запуск с тем же job id даст те же стили, а новый запуск — новые.
    """
    variants: list[ClipVariant] = []
    previous: str | None = None
    seed = f"{source_id}:{job_id}"
    watermark = (options.watermark or "").strip() or None

    for index, text in enumerate(texts, start=1):
        rng = _rng(seed, index)
        style = _pick_style(
            options.style, options.variation, index, rng, previous
        )
        previous = style

        if options.variation == "off":
            zoom = 1.0
            pan_x = 0.0
            pan_y = 0.0
        elif options.variation == "strong":
            zoom = round(1.03 + rng.random() * 0.04, 4)
            pan_x = round(rng.uniform(-0.10, 0.10), 4)
            pan_y = round(rng.uniform(-0.05, 0.05), 4)
        else:
            zoom = round(1.0 + rng.random() * 0.025, 4)
            pan_x = round(rng.uniform(-0.04, 0.04), 4)
            pan_y = round(rng.uniform(-0.02, 0.02), 4)

        variants.append(
            ClipVariant(
                index=index,
                style=style,
                zoom=zoom,
                pan_x=pan_x,
                pan_y=pan_y,
                grade=_grade(options.variation, rng),
                hook=extract_hook(text) if options.hook else None,
                end_card=(
                    _end_card(watermark, rng) if options.end_card else None
                ),
                watermark=watermark,
            )
        )
    return variants


def _keywords(text: str, limit: int = 3) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", (text or "").lower())
    result: list[str] = []
    for word in words:
        if word in _STOPWORDS or word.isdigit() or word in result:
            continue
        result.append(word)
        if len(result) >= limit:
            break
    return result


def build_publish(
    text: str,
    variant: ClipVariant,
    channel: str,
    index: int,
) -> dict:
    """Готовит черновик подписи для ручной публикации в TikTok."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    title = variant.hook or clean[:70].rstrip()
    if not title:
        title = f"Клип {index}"
    description = clean[:220].rstrip()
    if len(clean) > 220:
        description += "…"
    tags = [f"#{word}" for word in _keywords(clean)]
    return {
        "index": index,
        "title": title,
        "description": description,
        "hashtags": tags,
        "channel": channel,
        "note": (
            "Добавьте 1–2 хештега по теме и проверьте права на исходное "
            "видео перед публикацией."
        ),
    }


def _text_set(text: str) -> set[str]:
    return {
        word for word in (_normalize_word(item) for item in (text or "").split())
        if len(word) >= 3
    }


def text_similarity(first: str, second: str) -> float:
    """Jaccard-похожесть двух расшифровок (0…1)."""
    left = _text_set(first)
    right = _text_set(second)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def diversity_report(texts: list[str]) -> dict:
    """Считает, насколько клипы пачки отличаются по тексту."""
    pairs = []
    max_similarity = 0.0
    for first in range(len(texts)):
        for second in range(first + 1, len(texts)):
            similarity = text_similarity(texts[first], texts[second])
            max_similarity = max(max_similarity, similarity)
            if similarity >= 0.45:
                pairs.append({
                    "a": first + 1,
                    "b": second + 1,
                    "similarity": round(similarity, 3),
                })
    pairs.sort(key=lambda item: item["similarity"], reverse=True)
    return {
        "score": round(1.0 - max_similarity, 3) if texts else 1.0,
        "max_similarity": round(max_similarity, 3),
        "ok": max_similarity < 0.6,
        "pairs": pairs,
    }
