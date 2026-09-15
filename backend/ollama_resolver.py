from __future__ import annotations

import threading
import time

import httpx

from config import OLLAMA_BASE_URL, OLLAMA_MODEL

_LOCK = threading.Lock()
_CACHE_TS = 0.0
_CACHE_MODEL: str | None = None
TTL_SECONDS = 60.0

_PREFERRED_SIZES = ("7b", "8b", "9b", "14b", "13b", "3b", "32b", "70b", "1.5b", "0.5b")


def _ollama_native() -> str:
    return OLLAMA_BASE_URL.rstrip("/").rsplit("/v1", 1)[0]


def available_models(timeout: float = 3.0) -> list[str]:
    """Модели, которые реально скачаны в Ollama (/api/tags)."""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(_ollama_native() + "/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def resolve_model(timeout: float = 3.0) -> str:
    """Вернуть модель для скоринга: предпочтительную, либо ближайший фолбэк из скачанных.

    Кэшируется на TTL_SECONDS, чтобы не дёргать /api/tags на каждый батч.
    """
    global _CACHE_TS, _CACHE_MODEL
    now = time.monotonic()
    with _LOCK:
        if _CACHE_MODEL and now - _CACHE_TS < TTL_SECONDS:
            return _CACHE_MODEL
    models = available_models(timeout)
    chosen = _pick(models, OLLAMA_MODEL)
    with _LOCK:
        _CACHE_TS, _CACHE_MODEL = now, chosen
    return chosen


def _pick(models: list[str], preferred: str) -> str:
    if not models:
        return preferred
    if preferred in models:
        return preferred
    family = preferred.split(":")[0]  # qwen2.5 → ищем qwen2.5:*
    same_family = [m for m in models if m.startswith(family + ":")]
    if same_family:
        return _best(same_family)
    instruct = [m for m in models if "instruct" in m]
    if instruct:
        return _best(instruct)
    return models[0]


def _best(models: list[str]) -> str:
    def rank(m: str) -> int:
        low = m.lower()
        for i, size in enumerate(_PREFERRED_SIZES):
            if size in low:
                return i
        return 99

    return min(models, key=rank)