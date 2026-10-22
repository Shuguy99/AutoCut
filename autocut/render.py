"""Рендер вертикальных клипов и превью через ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .media import FFMPEG, Encoder, detect_h264_encoder, make_preview


class RenderError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        raise RenderError(
            f"ffmpeg не смог отрендерить клип:\n{proc.stderr[-3000:]}"
        )


def render_clip(
    source: Path | str,
    start: float,
    end: float,
    ass_path: Path | None,
    out_path: Path,
    layout: str = "blur",
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    crf: int = 20,
    encoder: Encoder | None = None,
) -> Path:
    """Рендерит клип; ``ass_path=None`` — без вжигания субтитров."""
    source = Path(source).resolve()
    out_path = Path(out_path).resolve()
    resolved_ass = Path(ass_path).resolve() if ass_path else None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, end - start)
    subs = resolved_ass.name if resolved_ass else None
    encoder = encoder or detect_h264_encoder()
    hw_upload = ",format=nv12,hwupload" if encoder.hwupload else ""
    burn = f",subtitles=filename={subs}" if subs else ""

    cmd = [
        FFMPEG, "-y", "-v", "error",
        *encoder.input_args,
        "-ss", f"{max(0.0, start):.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(source),
    ]

    if layout == "crop":
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}{burn}{hw_upload}"
        )
        cmd += ["-vf", video_filter, "-map", "0:v", "-map", "0:a?"]
    else:
        complex_filter = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma=30[bgv];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fgv];"
            f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2{burn}{hw_upload}[v]"
        )
        cmd += ["-filter_complex", complex_filter, "-map", "[v]", "-map", "0:a?"]

    cmd += encoder.output_args(crf)
    if not encoder.hwupload:
        cmd += ["-pix_fmt", "yuv420p"]
    cmd += [
        "-r", str(fps),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart", str(out_path),
    ]
    _run(cmd, cwd=resolved_ass.parent if resolved_ass else out_path.parent)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RenderError("ffmpeg завершился без ошибки, но файл не создан")
    return out_path


def render_preview(
    video: Path | str, out_path: Path, at: float | None = None
) -> Path:
    return make_preview(video, out_path, at=at)
