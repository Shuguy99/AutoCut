from pathlib import Path

from autocut.media import (
    compute_rms_windows,
    detect_h264_encoder,
    detect_scenes,
    extract_audio,
    make_preview,
    probe,
)


def test_encoder_detection():
    encoder = detect_h264_encoder()
    assert encoder.name
    assert encoder.output_args()


def test_probe(sample_video: Path):
    info = probe(sample_video)
    assert info.width == 640
    assert info.height == 360
    assert 5.5 <= info.duration <= 6.5
    assert info.has_audio is True


def test_extract_audio_and_rms(sample_video: Path, tmp_path: Path):
    wav = extract_audio(sample_video, tmp_path / "audio.wav")
    assert wav.exists()
    rms = compute_rms_windows(wav)
    assert rms.ndim == 1
    assert len(rms) >= 10
    assert float(rms.max()) > 0.01


def test_scene_detection_returns_list(sample_video: Path):
    scenes = detect_scenes(sample_video)
    assert isinstance(scenes, list)
    assert all(t >= 0 for t in scenes)


def test_preview(sample_video: Path, tmp_path: Path):
    out = make_preview(sample_video, tmp_path / "preview.jpg")
    assert out.exists()
    assert out.stat().st_size > 1000
