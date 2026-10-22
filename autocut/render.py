"""Рендер вертикальных клипов и превью через ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .media import FFMPEG, Encoder, detect_h264_encoder, make_preview
from .variation import Grade


class RenderError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        raise RenderError(
            f"ffmpeg не смог отрендерить клип:\n{proc.stderr[-3000:]}"
        )


def _even(value: float) -> int:
    number = max(2, int(round(value)))
    return number if number % 2 == 0 else number + 1


def _grade_filter(grade: Grade | None) -> str:
    if grade is None or not grade.enabled:
        return ""
    return (
        f",eq=contrast={grade.contrast:.4f}:saturation={grade.saturation:.4f}"
        f":brightness={grade.brightness:.4f}:gamma={grade.gamma:.4f}"
    )


def _pan_expr(axis: str, target: int, pan: float) -> str:
    factor = max(0.0, min(1.0, 0.5 + 0.5 * pan))
    return f"({axis}-{target})*{factor:.4f}"


def _zoom_geometry(
    width: int, height: int, zoom: float
) -> tuple[int, int]:
    zoom = max(1.0, min(1.15, float(zoom or 1.0)))
    return _even(width * zoom), _even(height * zoom)


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
    zoom: float = 1.0,
    pan: tuple[float, float] = (0.0, 0.0),
    grade: Grade | None = None,
    loudnorm: bool = True,
) -> Path:
    """Рендерит клип с вариативным кадрированием и цветокоррекцией.

    ``ass_path=None`` — без вжигания субтитров и плашек. ``zoom``/``pan``
    задают лёгкий кроп-зум, ``grade`` — цветокоррекцию, ``loudnorm`` —
    приведение громкости к уровню TikTok.
    """
    source = Path(source).resolve()
    out_path = Path(out_path).resolve()
    resolved_ass = Path(ass_path).resolve() if ass_path else None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, end - start)
    subs = resolved_ass.name if resolved_ass else None
    encoder = encoder or detect_h264_encoder()
    hw_upload = ",format=nv12,hwupload" if encoder.hwupload else ""
    burn = f",subtitles=filename={subs}" if subs else ""
    zoom_w, zoom_h = _zoom_geometry(width, height, zoom)
    pan_x = max(-1.0, min(1.0, float(pan[0] if pan else 0.0)))
    pan_y = max(
        -1.0, min(1.0, float(pan[1]) if pan and len(pan) > 1 else 0.0)
    )
    x_expr = _pan_expr("iw", width, pan_x)
    y_expr = _pan_expr("ih", height, pan_y)
    grade_filter = _grade_filter(grade)

    cmd = [
        FFMPEG, "-y", "-v", "error",
        *encoder.input_args,
        "-ss", f"{max(0.0, start):.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(source),
    ]

    if layout == "crop":
        video_filter = (
            f"scale={zoom_w}:{zoom_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:{x_expr}:{y_expr}"
            f"{grade_filter}{burn}{hw_upload}"
        )
        cmd += ["-vf", video_filter, "-map", "0:v", "-map", "0:a?"]
    else:
        complex_filter = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={zoom_w}:{zoom_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:{x_expr}:{y_expr},gblur=sigma=30[bgv];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fgv];"
            f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2[comp];"
            f"[comp]scale={zoom_w}:{zoom_h},"
            f"crop={width}:{height}:{x_expr}:{y_expr}"
            f"{grade_filter}{burn}{hw_upload}[v]"
        )
        cmd += ["-filter_complex", complex_filter, "-map", "[v]", "-map", "0:a?"]

    if loudnorm:
        cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
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
