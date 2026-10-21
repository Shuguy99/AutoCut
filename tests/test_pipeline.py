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


def test_pipeline_without_subtitles(sample_video: Path, config: Config, fake_transcript):
    options = JobOptions(
        clips=1, min_duration=2, max_duration=4, target_duration=3,
        subtitles=False,
    )
    result = run_pipeline(str(sample_video), options, config)
    result_dir = Path(result["result_dir"])
    clip = result["clips"][0]
    assert clip["subtitle"] is None
    assert Path(clip["file"]).exists()
    assert Path(clip["preview"]).exists()
    assert not list((result_dir / "clips").glob("*.ass"))
    assert (result_dir / "transcript.srt").exists()


def test_preview_time_picks_cue_midpoint():
    from autocut.pipeline import _preview_time
    from autocut.subtitles import Cue

    cues = [Cue(10.0, 12.0, "a"), Cue(20.0, 24.0, "b")]
    # центр клипа 20 с ближе к середине второй реплики (22 с)
    assert _preview_time(cues, 10.0, 30.0) == pytest.approx(12.0)
    # без реплик — середина клипа
    assert _preview_time([], 10.0, 30.0) == pytest.approx(10.0)
    # момент не выходит за пределы клипа
    assert _preview_time([Cue(40.0, 44.0, "c")], 10.0, 12.0) == pytest.approx(1.95)


def test_pipeline_cancel(sample_video: Path, config: Config, fake_transcript):
    options = JobOptions(clips=1, min_duration=2, max_duration=4, target_duration=3)
    with pytest.raises(CancelledError):
        run_pipeline(
            str(sample_video), options, config,
            is_cancelled=lambda: True,
        )
