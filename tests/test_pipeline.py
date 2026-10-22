from pathlib import Path

import json

import numpy as np
import pytest

from autocut.config import Config
from autocut.models import JobOptions, Segment, Transcript, Word
from autocut.pipeline import CancelledError, PipelineError, _focus_pan, run_pipeline


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


def test_pipeline_without_subtitles(
    sample_video: Path, config: Config, fake_transcript
):
    options = JobOptions(
        clips=1, min_duration=2, max_duration=4, target_duration=3,
        subtitles=False, hook=False, end_card=False,
    )
    result = run_pipeline(str(sample_video), options, config)
    result_dir = Path(result["result_dir"])
    clip = result["clips"][0]
    assert clip["subtitle"] is None
    assert Path(clip["file"]).exists()
    assert not list((result_dir / "clips").glob("*.ass"))


def test_pipeline_without_audio(
    sample_video: Path, config: Config, monkeypatch
):
    from autocut.media import MediaInfo

    monkeypatch.setattr(
        "autocut.pipeline.probe",
        lambda path: MediaInfo(
            duration=6.0, width=640, height=360, fps=30.0, has_audio=False
        ),
    )

    def no_transcribe(*args, **kwargs):
        raise AssertionError("без аудио транскрипция не нужна")

    monkeypatch.setattr("autocut.pipeline.transcribe", no_transcribe)
    options = JobOptions(
        clips=1, min_duration=2, max_duration=4, target_duration=3,
        hook=False, end_card=False,
    )
    result = run_pipeline(str(sample_video), options, config)
    result_dir = Path(result["result_dir"])
    assert Path(result["clips"][0]["file"]).exists()
    assert result["clips"][0]["subtitle"] is None
    assert (result_dir / "transcript.json").exists()


def test_transcript_cache_key_includes_model_and_language(tmp_path: Path):
    from autocut.pipeline import _cached_transcript
    from autocut.storage import save_transcript

    transcript = Transcript(language="ru", words=[], segments=[], text="")
    cache = tmp_path / "cache"
    cache.mkdir()
    _, path = _cached_transcript(cache, "video/../id", "small", "ru")
    save_transcript(path, transcript)

    found, _ = _cached_transcript(cache, "video/../id", "small", "ru")
    assert found is not None
    other, _ = _cached_transcript(cache, "video/../id", "base", "ru")
    assert other is None
    assert path.parent == cache
    assert ".." not in path.name


def test_manual_ranges_skip_auto_analysis(
    sample_video: Path, config: Config, fake_transcript, monkeypatch
):
    def boom(*args, **kwargs):
        raise AssertionError("автоанализ не должен запускаться")

    monkeypatch.setattr("autocut.pipeline.detect_scenes", boom)
    monkeypatch.setattr("autocut.pipeline.compute_rms_windows", boom)
    options = JobOptions(
        clips=2, min_duration=1, max_duration=10,
        ranges=[(0.5, 2.0), (3.0, 5.0)],
    )
    result = run_pipeline(str(sample_video), options, config)
    assert [
        (clip["start"], clip["end"]) for clip in result["clips"]
    ] == [(0.5, 2.0), (3.0, 5.0)]


def test_manual_range_outside_video_fails(
    sample_video: Path, config: Config, fake_transcript
):
    options = JobOptions(clips=1, ranges=[(0.0, 99.0)])
    with pytest.raises(PipelineError, match="выходит"):
        run_pipeline(str(sample_video), options, config)


def test_pipeline_writes_variants_publish_and_diversity(
    sample_video: Path, config: Config, monkeypatch
):
    tokens = [
        "первый", "текст", "про", "деньги", "и", "успех.",
        "второй", "текст", "про", "спорт", "и", "тренировки.",
    ]
    words = [
        Word(index * 0.5, index * 0.5 + 0.4, token)
        for index, token in enumerate(tokens)
    ]
    transcript = Transcript(
        language="ru", words=words,
        segments=[Segment(0.0, 6.0, " ".join(tokens))],
        text=" ".join(tokens),
    )
    monkeypatch.setattr(
        "autocut.pipeline.transcribe", lambda *args, **kwargs: transcript
    )
    options = JobOptions(
        clips=2, min_duration=2, max_duration=4, target_duration=3,
        variation="strong", style="auto", watermark="@nick",
    )
    result = run_pipeline(str(sample_video), options, config)
    result_dir = Path(result["result_dir"])
    assert len(result["clips"]) == 2

    publish = json.loads((result_dir / "publish.json").read_text("utf-8"))
    diversity = json.loads((result_dir / "diversity.json").read_text("utf-8"))
    metadata = json.loads((result_dir / "metadata.json").read_text("utf-8"))
    assert len(publish["clips"]) == 2
    assert diversity["score"] > 0
    assert len(metadata["variants"]) == 2

    clip = result["clips"][0]
    assert clip["variant"]["watermark"] == "@nick"
    assert clip["publish"]["title"]
    assert Path(clip["publish_file"]).exists()
    ass = Path(clip["subtitle"]).read_text(encoding="utf-8")
    assert "Watermark" in ass
    assert "Hook" in ass
    assert "EndCard" in ass


def test_focus_pan_bias():
    assert _focus_pan(0.0, "center") == 0.0
    assert _focus_pan(0.0, "left") == -0.75
    assert _focus_pan(0.0, "right") == 0.75
    assert _focus_pan(0.5, "right") == 1.0
    assert _focus_pan(-0.5, "left") == -1.0
