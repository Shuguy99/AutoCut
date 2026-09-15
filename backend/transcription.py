from __future__ import annotations

import json
from typing import Any

from config import WHISPER_DEVICE, WHISPER_LANGUAGE, WHISPER_MODEL

_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type="auto")
    return _MODEL


def transcribe(video_path: str, transcript_path: str, language: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    model = _get_model()
    kwargs = {"beam_size": 5, "vad_filter": True, "word_timestamps": True}
    lang = (language or "").strip() or WHISPER_LANGUAGE
    if lang:
        kwargs["language"] = lang
    segments_iter, _info = model.transcribe(video_path, **kwargs)
    segments = []
    for seg in segments_iter:
        if job_id is not None:
            from jobs import raise_if_cancelled
            raise_if_cancelled(job_id)
        words = [
            {"w": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
            for w in (seg.words or [])
        ]
        segments.append(
            {
                "id": seg.id,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "words": words,
            }
        )

    with open(transcript_path, "w", encoding="utf-8") as fh:
        json.dump({"segments": segments, "language": _info.language}, fh, ensure_ascii=False)

    return {"segments": segments, "language": _info.language}


def load_transcript(transcript_path: str) -> dict[str, Any]:
    with open(transcript_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


_CUE_MAX_WORDS = 6
_CUE_MAX_SEC = 4.5
_CUE_MAX_CHARS = 60


def make_srt(segments: list[dict[str, Any]], offset: float = 0.0) -> str:
    """Субтитры по словам: короткие реплики, а не «простыни» whisper-сегментов.

    Если у сегмента есть word-таймкоды — используем их; иначе равномерно
    размазываем текст по длительности сегмента.
    """
    boxes: list[tuple[float, float, str]] = []
    for seg in segments:
        words = seg.get("words") or []
        if words:
            boxes.extend((w["start"], w["end"], w["w"]) for w in words)
            continue
        tokens = (seg.get("text") or "").split()
        if not tokens:
            continue
        span = max(0.1, seg["end"] - seg["start"])
        step = span / len(tokens)
        boxes.extend(
            (seg["start"] + i * step, seg["start"] + (i + 1) * step, t)
            for i, t in enumerate(tokens)
        )

    cues: list[tuple[float, float, str]] = []
    cur: list[str] = []
    cur_start = cur_end = 0.0
    for start, end, w in boxes:
        if not cur:
            cur_start, cur_end, cur = start, end, [w]
            continue
        if len(cur) >= _CUE_MAX_WORDS or end - cur_start > _CUE_MAX_SEC or len(" ".join(cur)) >= _CUE_MAX_CHARS:
            cues.append((cur_start, cur_end, " ".join(cur)))
            cur_start, cur_end, cur = start, end, [w]
        else:
            cur_end, cur.append(w)
    if cur:
        cues.append((cur_start, cur_end, " ".join(cur)))

    blocks = []
    for i, (start, end, text) in enumerate(cues, start=1):
        start, end = start - offset, end - offset
        if end <= 0:
            continue
        start = max(0.0, start)
        blocks.append(f"{i}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{text}\n")
    return "\n".join(blocks)


def _fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"