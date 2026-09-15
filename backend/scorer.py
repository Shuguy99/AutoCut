from __future__ import annotations

import json
import re
import sys
from typing import Any

import httpx

from ollama_resolver import _ollama_native, resolve_model

MAX_WORDS_PER_CHUNK = 130
MAX_CHUNKS_PER_REQUEST = 15
MAX_CHUNK_SEC = 75.0  # иначе при редкой речи чанк растягивается на минуты и оценка «размазывается»


def merge_into_chunks(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    word_count = 0
    for seg in segments:
        n_words = len(seg.get("words", [])) or max(1, len(seg.get("text", "").split()))
        if cur and (
            word_count >= MAX_WORDS_PER_CHUNK
            or seg["end"] - cur[0]["start"] > MAX_CHUNK_SEC
        ):
            chunks.append(_make_chunk(cur))
            cur, word_count = [], 0
        cur.append(seg)
        word_count += n_words
    if cur:
        chunks.append(_make_chunk(cur))
    return chunks


def _make_chunk(segments: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(seg.get("text", "") for seg in segments).strip()
    return {
        "chunk_id": 0,  # filled later
        "text": text,
        "start": min(seg["start"] for seg in segments),
        "end": max(seg["end"] for seg in segments),
        "segments": segments,
    }


def score_chunks(chunks: list[dict[str, Any]], progress_cb=None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    total = len(chunks)
    for start in range(0, total, MAX_CHUNKS_PER_REQUEST):
        batch = chunks[start : start + MAX_CHUNKS_PER_REQUEST]
        for i, ch in enumerate(batch):
            ch["chunk_id"] = start + i
        scored = _call_ollama(batch)
        by_id = {int(s.get("chunk_id", -1)): s for s in scored}
        missing = [ch for ch in batch if ch["chunk_id"] not in by_id]
        # локальные модели склонны возвращать одно «главное» вхождение — добиваем пропущенные по одному
        if missing:
            by_id.update(_fill_missing(missing))
        # модель «ставит всем одинаково» — переспрашиваем один раз с требованием разброса
        if len(batch) > 3 and by_id and _scores_are_monotone(list(by_id.values())):
            print(f"[scorer] monotone scores, retrying batch {start}-{start + len(batch) - 1}", file=sys.stderr)
            again = {int(s.get("chunk_id", -1)): s for s in _call_ollama(batch, force_spread=True)}
            again_missing = [ch for ch in batch if ch["chunk_id"] not in again]
            if again_missing:
                again.update(_fill_missing(again_missing))
            if again and not _scores_are_monotone(list(again.values())):
                by_id = again
        for ch in batch:
            s = by_id.get(ch["chunk_id"], {})
            ch["score"] = _to_score(s.get("score"))
            ch["title"] = str(s.get("title") or "Хайлайт").strip()
            ch["reason"] = str(s.get("reason") or "").strip()
            results.append(ch)
        if progress_cb:
            progress_cb(min(start + len(batch), total))
    return results


def _fill_missing(chunks: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for ch in chunks:
        try:
            with httpx.Client(base_url=_ollama_native(), timeout=120.0) as client:
                resp = client.post(
                    "/api/chat",
                    json={
                        "model": resolve_model(),
                        "messages": [
                            {
                                "role": "system",
                                "content": "Оцени фрагмент расшифровки видео от 0 до 100 для отбора ярких моментов."
                                " 0 — вода, 100 — обязательный хайлайт. Верни ТОЛЬКО один JSON-объект:"
                                ' {"chunk_id": <int>, "score": <int 0-100>, "title": "<до 8 слов>",'
                                ' "reason": "<до 15 слов>"}. Ничего больше.',
                            },
                            {
                                "role": "user",
                                "content": f"Фрагмент [{ch['chunk_id']}] ({ch['start']:.1f}s-{ch['end']:.1f}s): {ch['text']}",
                            },
                        ],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1, "num_predict": 300},
                    },
                )
                resp.raise_for_status()
                data = json.loads(resp.json()["message"]["content"])
                if isinstance(data, dict) and "score" in data:
                    out[int(data.get("chunk_id", ch["chunk_id"]))] = data
        except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError) as exc:
            print(f"[scorer] fill_missing chunk {ch['chunk_id']} failed: {exc}", file=sys.stderr)
    return out


def _call_ollama(chunks: list[dict[str, Any]], force_spread: bool = False) -> list[dict[str, Any]]:
    payload_chunks = [
        {
            "chunk_id": ch["chunk_id"],
            "start": round(ch["start"], 2),
            "end": round(ch["end"], 2),
            "words": len(ch["text"].split()),
            "text": ch["text"],
        }
        for ch in chunks
    ]
    spread_hint = (
        " Не ставь всем фрагментам одинаковые оценки — растяни их по всей шкале 1-99,"
        " чтобы лучший фрагмент реально выделялся."
        if force_spread
        else ""
    )
    system = (
        "Ты — редактор, который выбирает самые интересные фрагменты расшифровки видео для коротких роликов."
        " Оцени КАЖДЫЙ фрагмент по шкале 1-99."
        " 90+ — обязательный хайлайт (яркий вывод, сюжетный поворот, сильная эмоция, шутка, важный факт);"
        " 60-89 — крепкий момент; 30-59 — обычная речь; 1-29 — вода, паузы, скучно."
        " НЕ используй 0 и НЕ используй 100. Если в фрагменте в основном музыка/тишина — это 1-20."
        " Оценки должны реально различаться и отражать важность фрагмента."
        f" Фрагментов ровно {len(chunks)}. В массиве на выходе ДОЛЖНО быть ровно {len(chunks)} объектов,"
        " по одному на каждый chunk_id от 0 до "
        f"{chunks[-1]['chunk_id']} включительно. Не пропускай ни одного."
        " Верни ТОЛЬКО валидный JSON-массив, без пояснений и без обёрток:"
        ' [{"chunk_id": <int>, "score": <int 1-99>, "title": "<до 6 слов>", "reason": "<до 10 слов>"}]'
        + spread_hint
    )
    user = (
        "Фрагменты расшифровки (время, число слов, текст). Оцени каждый от 1 до 99:\n"
        + json.dumps(payload_chunks, ensure_ascii=False)
    )

    try:
        with httpx.Client(base_url=_ollama_native(), timeout=600.0) as client:
            resp = client.post(
                "/api/chat",
                json={
                    "model": resolve_model(),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2, "num_predict": 4096},
                },
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
    except (httpx.HTTPError, KeyError, TypeError) as exc:
        print(f"[scorer] Ollama request failed: {exc}", file=sys.stderr)
        return [{"chunk_id": ch["chunk_id"], "score": 1} for ch in chunks]

    return _parse_response(content, chunks)


def _parse_response(content: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Разбирает ответ Ollama в список оценок (без ретрая; вернёт score=1 при невозможности)."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = _recover_json(content)
        if data is None:
            print(f"[scorer] Ollama returned non-JSON, falling back: {content[:300]!r}", file=sys.stderr)
            return [{"chunk_id": ch["chunk_id"], "score": 1} for ch in chunks]

    if isinstance(data, dict):
        for key in ("data", "chunks", "scores", "highlights", "clips", "segments"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            # одиночный объект вместо массива — mini-LLM любит так делать
            data = [data]
    if not isinstance(data, list):
        data = []
    return data


def _scores_are_monotone(entries: list[dict[str, Any]]) -> bool:
    """True, если модель почти не различает фрагменты (все оценки близки)."""
    vals = sorted(_to_score(e.get("score")) for e in entries)
    if len(vals) < 3:
        return False
    return (vals[-1] - vals[0]) <= 5


def _recover_json(content: str) -> list[dict[str, Any]] | None:
    """Вытаскивает записи из повреждённого JSON (обрезанный массив и т.п.)."""
    matches = re.findall(r"\{[^{}]*\}", content, flags=re.S)
    entries: list[dict[str, Any]] = []
    for m in matches:
        try:
            obj = json.loads(m)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and ("chunk_id" in obj or "score" in obj):
            entries.append(obj)
    return entries or None


def _to_score(value: Any) -> int:
    try:
        return max(1, min(99, int(float(str(value).replace(",", ".")))))
    except (TypeError, ValueError):
        return 1