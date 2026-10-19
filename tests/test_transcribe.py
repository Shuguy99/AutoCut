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


def test_transcribe_wraps_import_error(monkeypatch, tmp_path: Path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    module.clear_model_cache()
    with pytest.raises(module.TranscriptionError):
        module.transcribe(tmp_path / "audio.wav")
