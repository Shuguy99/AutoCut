"""Оценка фрагментов: энергия, речь, сцены, хуки и завершённость фраз."""

from __future__ import annotations

import numpy as np

from .models import ClipCandidate, Word

HOOK_WORDS = {
    "почему", "секрет", "ошибка", "главное", "правда", "никогда", "всегда",
    "шок", "важно", "причина", "способ", "результат", "деньги", "бесплатно",
    "быстро", "лучше", "хуже", "интересно", "представь", "смотри", "внимание",
    "why", "secret", "mistake", "never", "always", "shocking", "important",
    "reason", "how", "best", "worst", "free", "money", "fast", "result",
    "imagine", "look", "truth",
}


def sentence_boundaries(words: list[Word]) -> list[float]:
    bounds = {0.0}
    for index, word in enumerate(words):
        if word.text.rstrip().endswith((".", "!", "?", "…")):
            bounds.add(round(word.end, 3))
        if index + 1 < len(words):
            gap = words[index + 1].start - word.end
            if gap > 0.6:
                bounds.add(round(word.end, 3))
    return sorted(bounds)


def _snap(value: float, boundaries: list[float], max_shift: float) -> float:
    if not boundaries:
        return value
    nearest = min(boundaries, key=lambda b: abs(b - value))
    return nearest if abs(nearest - value) <= max_shift else value


def _window_words(words: list[Word], start: float, end: float) -> list[Word]:
    return [w for w in words if w.end > start and w.start < end]


def _word_key(value: str) -> str:
    return value.strip(".,!?…:;\"'()[]«»—–-").lower()


def _jaccard(first: set[str], second: set[str]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _candidate_text_set(words: list[Word], start: float, end: float) -> set[str]:
    return {
        _word_key(word.text)
        for word in _window_words(words, start, end)
        if len(_word_key(word.text)) >= 3
    }


def _speech_coverage(words: list[Word], start: float, end: float) -> float:
    if end <= start:
        return 0.0
    covered = sum(
        max(0.0, min(w.end, end) - max(w.start, start)) for w in words
    )
    return min(1.0, covered / (end - start))


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low = float(np.percentile(values, 10))
    high = float(np.percentile(values, 90))
    if high - low < 1e-9:
        return [0.5 for _ in values]
    return [float(np.clip((v - low) / (high - low), 0.0, 1.0)) for v in values]


def _overlap_ratio(first: ClipCandidate, second: ClipCandidate) -> float:
    """Доля пересечения относительно более короткого окна."""
    inter = max(0.0, min(first.end, second.end) - max(first.start, second.start))
    shortest = min(first.end - first.start, second.end - second.start)
    return inter / shortest if shortest > 0 else 0.0


def _window_energy(rms: np.ndarray, start: float, end: float, duration: float) -> float:
    if rms.size == 0 or duration <= 0:
        return 0.0
    size = rms.size
    low = max(0, int(start / duration * size))
    high = min(size, int(end / duration * size) + 1)
    window = rms[low:high]
    return float(window.mean()) if window.size else 0.0


def find_highlights(
    duration: float,
    rms: np.ndarray,
    words: list[Word],
    scene_times: list[float],
    count: int = 5,
    min_duration: float = 20,
    max_duration: float = 60,
    target_duration: float = 30,
    step: float = 1.0,
    max_text_overlap: float | None = None,
) -> list[ClipCandidate]:
    """Возвращает до ``count`` непересекающихся кандидатов по убыванию score.

    ``max_text_overlap`` дополнительно отбрасывает кандидаты, слишком похожие
    по словам на уже выбранные (Jaccard-похожесть выше порога).
    """
    duration = max(0.1, float(duration))
    if duration <= min_duration:
        return [ClipCandidate(0.0, duration, 1.0, {
            "energy": 1.0, "speech": 0.0, "scenes": 0.0,
            "hooks": 0.0, "completeness": 1.0,
        })]

    target = min(max(float(target_duration), min_duration), max_duration)
    target = min(target, duration)
    boundaries = sorted(set(sentence_boundaries(words) + [duration]))

    starts = list(np.arange(0.0, max(0.01, duration - target) + 1e-6, step))
    if not starts or starts[-1] < duration - target - 1e-6:
        starts.append(max(0.0, duration - target))

    candidates: list[ClipCandidate] = []
    seen: set[tuple[int, int]] = set()
    for raw_start in starts:
        start = _snap(float(raw_start), boundaries, 3.0)
        end = _snap(float(raw_start) + target, boundaries, 4.0)
        if end - start < min_duration:
            end = min(duration, start + min_duration)
        if end - start > max_duration:
            end = start + max_duration
        if end > duration:
            end = duration
            start = max(0.0, end - target)
        if end - start < 1.0:
            continue
        key = (round(start, 2), round(end, 2))
        if key in seen:
            continue
        seen.add(key)

        window_words = _window_words(words, start, end)
        hook_hits = sum(
            1 for w in window_words
            if w.text.strip(".,!?…:;\"'()").lower() in HOOK_WORDS
        )
        scenes = sum(1 for t in scene_times if start <= t < end)
        boundary_hits = sum(
            1 for b in boundaries if start - 1.5 <= b <= start + 1.5
        ) + sum(1 for b in boundaries if end - 1.5 <= b <= end + 1.5)
        candidates.append(
            ClipCandidate(
                start=round(start, 3),
                end=round(end, 3),
                score=0.0,
                parts={
                    "energy": _window_energy(rms, start, end, duration),
                    "speech": _speech_coverage(window_words, start, end),
                    "scenes": min(1.0, scenes / 3.0),
                    "hooks": min(1.0, hook_hits / 6.0),
                    "completeness": 1.0 if boundary_hits >= 2 else (
                        0.5 if boundary_hits == 1 else 0.0
                    ),
                },
            )
        )

    energies = _normalize([c.parts["energy"] for c in candidates])
    for candidate, energy in zip(candidates, energies):
        candidate.parts["energy"] = energy
        candidate.score = round(
            0.40 * energy
            + 0.25 * candidate.parts["speech"]
            + 0.15 * candidate.parts["scenes"]
            + 0.10 * candidate.parts["hooks"]
            + 0.10 * candidate.parts["completeness"],
            4,
        )

    selected: list[ClipCandidate] = []
    selected_sets: list[set[str]] = []
    for candidate in sorted(candidates, key=lambda c: c.score, reverse=True):
        if not all(
            _overlap_ratio(candidate, other) <= 0.3 for other in selected
        ):
            continue
        if max_text_overlap is not None:
            current_set = _candidate_text_set(
                words, candidate.start, candidate.end
            )
            if current_set and any(
                _jaccard(current_set, other) > max_text_overlap
                for other in selected_sets if other
            ):
                continue
        selected.append(candidate)
        if max_text_overlap is not None:
            selected_sets.append(
                _candidate_text_set(words, candidate.start, candidate.end)
            )
        if len(selected) >= count:
            break
    return selected
