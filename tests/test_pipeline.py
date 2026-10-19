from pathlib import Path

import numpy as np
import pytest

from autocut.config import Config
from autocut.models import JobOptions, Segment, Transcript, Word
from autocut.pipeline import CancelledError, run_pipeline


@pytest.fixture
def fake_transcript(monkeypatch):
    words = [
        Word(float(t), float(t) + 0.4, "слово")
        for t in np.arange(0, 6, 0.5)
    ]
    transcript = Transcript(
        language="ru",
        words=words,
        segments=[Segment(0.0, 6.0, "тестовый текст")],
        text="тестовый текст",
    )
    monkeypatch.setattr(
        "autocut.pipeline.transcribe", lambda *a, **k: transcript
    )
    return transcript


def test_pipeline_local_file(sample_video: Path, config: Config, fake_transcript):
    events = []
    options = JobOptions(
        clips=1, min_duration=2, max_duration=4, target_duration=3,
        layout="blur",
    )
    result = run_pipeline(
        str(sample_video), options, config,
        progress=lambda stage, pct, msg: events.append((stage, pct)),
    )
    result_dir = Path(result["result_dir"])
    assert result_dir.is_dir()
    assert (result_dir / "metadata.json").exists()
    assert (result_dir / "transcript.json").exists()
    assert (result_dir / "transcript.srt").exists()
    assert (result_dir / "source.json").exists()
    assert (result_dir / "job.log").exists()
    assert len(result["clips"]) == 1
    clip = result["clips"][0]
    assert Path(clip["file"]).exists()
    assert Path(clip["preview"]).exists()
    assert Path(clip["subtitle"]).exists()
    assert events[-1][0] == "done"
    assert events[-1][1] == 100


def test_pipeline_cancel(sample_video: Path, config: Config, fake_transcript):
    options = JobOptions(clips=1, min_duration=2, max_duration=4, target_duration=3)
    with pytest.raises(CancelledError):
        run_pipeline(
            str(sample_video), options, config,
            is_cancelled=lambda: True,
        )
