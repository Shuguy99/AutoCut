from __future__ import annotations

from pathlib import Path

from .models import Segment, Transcript, Word


class TranscriptionError(RuntimeError):
    pass


_MODELS: dict[tuple[str, str, str], object] = {}


def clear_model_cache() -> None:
    _MODELS.clear()


def _get_model(model_name: str, device: str, compute_type: str):
    key = (model_name, device, compute_type)
    if key not in _MODELS:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "faster-whisper не установлен; выполните pip install faster-whisper"
            ) from exc
        try:
            _MODELS[key] = WhisperModel(
                model_name, device=device, compute_type=compute_type
            )
        except Exception as exc:
            raise TranscriptionError(
                f"не удалось загрузить модель Whisper '{model_name}': {exc}"
            ) from exc
    return _MODELS[key]


def transcribe(
    audio: Path | str,
    model_name: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
) -> Transcript:
    model = _get_model(model_name, device, compute_type)
    try:
        raw_segments, info = model.transcribe(
            str(audio),
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
            language=language,
        )
        segments: list[Segment] = []
        words: list[Word] = []
        texts: list[str] = []
        for segment in raw_segments:
            text = (segment.text or "").strip()
            if not text:
                continue
            segments.append(
                Segment(float(segment.start), float(segment.end), text)
            )
            texts.append(text)
            for word in segment.words or []:
                token = (word.word or "").strip()
                if token:
                    words.append(
                        Word(float(word.start), float(word.end), token)
                    )
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"ошибка распознавания речи: {exc}") from exc

    return Transcript(
        language=getattr(info, "language", None) or "unknown",
        words=words,
        segments=segments,
        text=" ".join(texts).strip(),
    )
