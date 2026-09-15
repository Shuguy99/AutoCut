from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TARGET_W, TARGET_H = 1080, 1920


def probe_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr}")
    return float(json.loads(out.stdout)["format"]["duration"])


def probe_dimensions(video_path: str) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr}")
    st = json.loads(out.stdout)["streams"][0]
    return int(st["width"]), int(st["height"])


def extract_thumbnail(video_path: str, at_sec: float, out_path: str) -> str:
    cmd = [
        "ffmpeg", "-y", "-ss", f"{max(0.0, at_sec):.3f}", "-i", video_path,
        "-frames:v", "1", "-q:v", "4", out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


def cut_clip(
    video_path: str,
    start: float,
    end: float,
    out_path: str,
    srt_path: str | None = None,
    aspect: str | None = None,
) -> None:
    """aspect: None | '9_16_blur' | '9_16_crop'."""
    duration = end - start
    cwd = str(Path(srt_path).parent) if srt_path else None
    if aspect:
        _cut_with_filter(video_path, start, duration, out_path, srt_path, aspect, cwd)
    elif srt_path:
        srt_name = Path(srt_path).name
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}", "-i", video_path,
            "-filter_complex", f"[0:v]subtitles={srt_name}:force_style='{_sub_style(720)}'[v]",
            "-map", "[v]", "-map", "0:a",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero", out_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True, cwd=cwd)
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}", "-i", video_path,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero", out_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)


def _cut_with_filter(
    video_path: str,
    start: float,
    duration: float,
    out_path: str,
    srt_path: str | None,
    aspect: str,
    cwd: str | None,
) -> None:
    w, h = probe_dimensions(video_path)
    srt_part = ""
    if srt_path:
        srt_part = f",subtitles={Path(srt_path).name}:force_style='{_sub_style(TARGET_H)}'"

    if aspect == "9_16_blur":
        fg_h = 2 * max(1, round(h * TARGET_W / w / 2))
        fg_w = TARGET_W if fg_h <= TARGET_H else 2 * max(1, round(w * TARGET_H / h / 2))
        y = max(0, (TARGET_H - fg_h) // 2)
        x = max(0, (TARGET_W - fg_w) // 2)
        fc = (
            f"[0:v]split=2[bg0][fg0];"
            f"[bg0]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},boxblur=22:4[bg];"
            f"[fg0]scale={fg_w}:{fg_h}[fg];"
            f"[bg][fg]overlay=x={x}:y={y},format=yuv420p,setsar=1{srt_part}[v]"
        )
    else:  # 9_16_crop
        fc = (
            f"[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},format=yuv420p,setsar=1{srt_part}[v]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-i", video_path,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero", out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True, cwd=cwd)


def _sub_style(target_height: int) -> str:
    size = max(12, round(target_height / 88))
    margin = max(16, round(target_height / 52))
    return (
        f"FontName=Arial,FontSize={size},MarginV={margin},"
        "OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1"
    )


def build_montage(clip_paths: list[str], out_path: str) -> float:
    if not clip_paths:
        raise RuntimeError("no clips to concat")
    clip_dir = Path(clip_paths[0]).parent
    list_file = clip_dir / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as fh:
        for p in clip_paths:
            fh.write(f"file '{Path(p).name}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat_list.txt",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True, cwd=str(clip_dir))
    list_file.unlink(missing_ok=True)
    return probe_duration(out_path)


def ffmpeg_available() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        return out.returncode == 0
    except FileNotFoundError:
        return False