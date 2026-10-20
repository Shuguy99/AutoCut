from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .models import Segment, Transcript, Word

TARGET_RATE = 16000


class TranscriptionError(RuntimeError):
    pass


_MODELS: dict[tuple[str, str, str], object] = {}


def read_pcm_wav(audio: Path | str, target_rate: int = TARGET_RATE) -> np.ndarray:
    """Читает 16-битный моно/стерео WAV в float32, приведённый к [-1, 1].

    Своя реализация вместо `faster_whisper.decode_audio`: часть сборок PyAV не
    принимает `metadata_errors`, из-за чего встроенный декодер падает с
    TypeError. Наш пайплайн и так отдаёт сюда WAV 16 кГц из ffmpeg.
    """
    with wave.open(str(audio), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError("ожидается 16-битный PCM")
        channels = handle.getnchannels()
        rate = handle.getframerate()
        if rate != target_rate:
            raise ValueError(f"ожидается {target_rate} Гц, получено {rate}")
        if channels not in (1, 2):
            raise ValueError("ожидается моно или стерео")
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)
    return np.ascontiguousarray(samples, dtype=np.float32)


def _decode_via_faster_whisper(audio: Path | str) -> np.ndarray:
    """Резервный путь: декодер faster-whisper с терпимостью к аргументам PyAV."""
    import faster_whisper.audio as fw_audio

    original_open = fw_audio.av.open

    def tolerant_open(*args, **kwargs):
        try:
            return original_open(*args, **kwargs)
        except TypeError:
            for key in ("metadata_errors", "metadata_encoding"):
                kwargs.pop(key, None)
            return original_open(*args, **kwargs)

    fw_audio.av.open = tolerant_open
    try:
        return fw_audio.decode_audio(str(audio))
    finally:
        fw_audio.av.open = original_open


def prepare_audio(audio: Path | str) -> object:
    """Готовит вход для модели: numpy-массив, если это наш WAV, иначе путь."""
    try:
        return read_pcm_wav(audio)
    except Exception:
        pass
    try:
        return _decode_via_faster_whisper(audio)
    except Exception:
        return str(audio)


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
            prepare_audio(audio),
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
