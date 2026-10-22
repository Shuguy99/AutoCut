"""Работа с ffmpeg/ffprobe: метаданные, аудио, сцены, превью."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Encoder:
    name: str
    input_args: tuple[str, ...] = ()
    hwupload: bool = False

    def output_args(self, crf: int = 20) -> list[str]:
        if self.name == "libx264":
            return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
        if self.name == "h264_vaapi":
            return ["-c:v", "h264_vaapi", "-b:v", "8M"]
        if self.name == "h264_nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(crf)]
        if self.name == "libopenh264":
            return ["-c:v", "libopenh264", "-b:v", "8M"]
        return ["-c:v", "mpeg4", "-q:v", "4"]


def _encoder_works(encoder: Encoder) -> bool:
    command = [
        FFMPEG, "-y", "-v", "error",
        *encoder.input_args,
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
        "-t", "0.4",
    ]
    if encoder.hwupload:
        command += ["-vf", "format=nv12,hwupload"]
    command += [*encoder.output_args(), "-f", "null", "-"]
    return subprocess.run(command, capture_output=True).returncode == 0


_ENCODER_CACHE: dict[str, Encoder] = {}


def detect_h264_encoder() -> Encoder:
    """Подбирает рабочий H.264-энкодер, проверяя его коротким тестом."""
    if "encoder" in _ENCODER_CACHE:
        return _ENCODER_CACHE["encoder"]
    candidates = [Encoder("libx264")]
    for device in ("/dev/dri/renderD128", "/dev/dri/renderD129"):
        if Path(device).exists():
            candidates.append(
                Encoder("h264_vaapi", ("-vaapi_device", device), True)
            )
    if shutil.which("nvidia-smi"):
        candidates.append(Encoder("h264_nvenc"))
    candidates.append(Encoder("libopenh264"))
    chosen = Encoder("mpeg4")
    for candidate in candidates:
        if _encoder_works(candidate):
            chosen = candidate
            break
    _ENCODER_CACHE["encoder"] = chosen
    return chosen


def encoder_args(crf: int = 20) -> list[str]:
    """Аргументы ffmpeg для выбранного H.264-энкодера."""
    return detect_h264_encoder().output_args(crf)


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def _run_text(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(
            f"команда завершилась с ошибкой: {' '.join(cmd)}\n"
            f"{proc.stderr[-2000:]}"
        )
    return proc.stdout


def _run_bytes(cmd: list[str]) -> bytes:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise MediaError(
            f"команда завершилась с ошибкой: {' '.join(cmd)}\n"
            f"{proc.stderr.decode('utf-8', 'replace')[-2000:]}"
        )
    return proc.stdout


def probe(path: Path | str) -> MediaInfo:
    """Читает длительность, размеры, fps и наличие аудио через ffprobe."""
    output = _run_text(
        [
            FFPROBE, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
    )
    data = json.loads(output)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError(f"в файле нет видеодорожки: {path}")
    fps_raw = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    duration = float(
        data.get("format", {}).get("duration")
        or video.get("duration")
        or 0.0
    )
    return MediaInfo(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps,
        has_audio=audio is not None,
    )


def extract_audio(video: Path | str, out_wav: Path) -> Path:
    """Извлекает моно 16 кГц PCM WAV для Whisper."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    _run_text(
        [
            FFMPEG, "-y", "-v", "error", "-i", str(video),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(out_wav),
        ]
    )
    return out_wav


def compute_rms_windows(audio: Path | str, window: float = 0.5) -> np.ndarray:
    """Считает RMS по окнам ``window`` секунд (16 кГц, моно)."""
    raw = _run_bytes(
        [
            FFMPEG, "-v", "error", "-i", str(audio),
            "-f", "s16le", "-ac", "1", "-ar", "16000", "-",
        ]
    )
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return np.zeros(1, dtype=np.float32)
    size = max(1, int(16000 * window))
    pad = (-samples.size) % size
    if pad:
        samples = np.pad(samples, (0, pad))
    frames = samples.reshape(-1, size)
    return np.sqrt(np.mean(frames * frames, axis=1) + 1e-9).astype(np.float32)


def detect_scenes(video: Path | str, threshold: float = 0.35) -> list[float]:
    """Возвращает временные точки смены сцены (может быть пустым)."""
    proc = subprocess.run(
        [
            FFMPEG, "-v", "info", "-i", str(video),
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise MediaError(
            f"не удалось определить сцены: {proc.stderr[-2000:]}"
        )
    return sorted(
        {round(float(m.group(1)), 3)
         for m in re.finditer(r"pts_time:([0-9.]+)", proc.stderr)}
    )


def make_preview(
    video: Path | str, out_path: Path, at: float | None = None
) -> Path:
    """Сохраняет один кадр; по умолчанию — середина видео."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if at is None:
        at = max(0.0, probe(video).duration / 2)
    _run_text(
        [
            FFMPEG, "-y", "-v", "error", "-ss", f"{at:.3f}",
            "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out_path),
        ]
    )
    return out_path
