import sys
import types
from pathlib import Path

import pytest

from autocut import transcribe as module


class FakeWord:
    def __init__(self, start, end, word):
        self.start, self.end, self.word = start, end, word


class FakeSegment:
    def __init__(self):
        self.start, self.end, self.text = 0.0, 1.0, "привет мир"
        self.words = [
            FakeWord(0.0, 0.4, " привет"),
            FakeWord(0.5, 0.9, " мир"),
        ]


class FakeInfo:
    language = "ru"


class FakeModel:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio, **kwargs):
        return [FakeSegment()], FakeInfo()


def test_transcribe_maps_words(monkeypatch, tmp_path: Path):
    fake = types.SimpleNamespace(WhisperModel=FakeModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    module.clear_model_cache()
    result = module.transcribe(tmp_path / "audio.wav", model_name="tiny")
    assert result.language == "ru"
    assert [w.text for w in result.words] == ["привет", "мир"]
    assert result.words[0].start == 0.0
    assert result.text == "привет мир"


def test_read_pcm_wav_returns_normalized_float(tmp_path: Path):
    import array
    import wave as wave_module

    path = tmp_path / "tone.wav"
    samples = array.array("h", [0, 16384, -16384, 32767, -32768] * 100)
    with wave_module.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(samples.tobytes())

    result = module.read_pcm_wav(path)
    assert result.dtype == "float32"
    assert result.size == 500
    assert float(result.max()) <= 1.0
    assert float(result.min()) >= -1.0


def test_read_pcm_wav_rejects_other_formats(tmp_path: Path):
    import array
    import wave as wave_module

    path = tmp_path / "mono8.wav"
    samples = array.array("b", [0, 1, -1] * 100)
    with wave_module.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(16000)
        handle.writeframes(samples.tobytes())

    with pytest.raises(ValueError):
        module.read_pcm_wav(path)


def test_prepare_audio_falls_back_to_path(tmp_path: Path):
    missing = tmp_path / "nope.wav"
    assert module.prepare_audio(missing) == str(missing)


def test_transcribe_wraps_import_error(monkeypatch, tmp_path: Path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    module.clear_model_cache()
    with pytest.raises(module.TranscriptionError):
        module.transcribe(tmp_path / "audio.wav")
