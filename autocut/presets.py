"""Готовые пресеты оформления и нарезки."""

from __future__ import annotations

from .models import JobOptions

PRESETS: dict[str, dict] = {
    "podcast": {
        "layout": "blur",
        "crop_focus": "center",
        "variation": "subtle",
        "style": "clean",
        "caption_mode": "word",
        "min_duration": 15,
        "max_duration": 45,
        "target_duration": 25,
        "hook": True,
        "end_card": True,
        "loudnorm": True,
        "safe_zones": True,
    },
    "talking_head": {
        "layout": "crop",
        "crop_focus": "center",
        "variation": "subtle",
        "style": "bold",
        "caption_mode": "phrase",
        "min_duration": 10,
        "max_duration": 30,
        "target_duration": 20,
        "hook": True,
        "end_card": True,
        "loudnorm": True,
        "safe_zones": True,
    },
    "cinematic": {
        "layout": "crop",
        "crop_focus": "center",
        "variation": "strong",
        "style": "minimal",
        "caption_mode": "phrase",
        "min_duration": 20,
        "max_duration": 60,
        "target_duration": 35,
        "hook": True,
        "end_card": True,
        "loudnorm": True,
        "safe_zones": True,
    },
    "shorts": {
        "layout": "blur",
        "crop_focus": "center",
        "variation": "strong",
        "style": "karaoke",
        "caption_mode": "word",
        "min_duration": 8,
        "max_duration": 25,
        "target_duration": 15,
        "hook": True,
        "end_card": True,
        "loudnorm": True,
        "safe_zones": True,
    },
}


def apply_preset(options: JobOptions) -> JobOptions:
    """Возвращает копию опций с параметрами выбранного пресета.

    Пресет меняет только оформление, длительности, хук, плашку, loudnorm и
    safe zones. Водяной знак, ручные диапазоны, прокси и модель сохраняются.
    """
    values = PRESETS.get(options.preset)
    if not values:
        return options
    return options.model_copy(update=values)
