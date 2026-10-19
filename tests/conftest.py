from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from autocut.config import Config
from autocut.media import detect_h264_encoder


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    out = tmp_path / "sample.mp4"
    encoder = detect_h264_encoder()
    command = [
        "ffmpeg", "-y",
        *encoder.input_args,
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "6",
    ]
    if encoder.hwupload:
        command += ["-vf", "format=nv12,hwupload"]
    else:
        command += ["-pix_fmt", "yuv420p"]
    command += [
        *encoder.output_args(),
        "-c:a", "aac", "-shortest", str(out),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return out


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(output_dir=tmp_path / "output", work_dir=tmp_path / "work")
