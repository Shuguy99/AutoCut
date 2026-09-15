from __future__ import annotations

import logging
from typing import Any

from pathlib import Path

import jobs
from config import (
    DEFAULT_BURN_SUBTITLES,
    DEFAULT_CLIP_MAX_SEC,
    DEFAULT_CLIP_MIN_SEC,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_CLIPS,
    DEFAULT_MIN_SCORE,
    WHISPER_LANGUAGE,
)
from cutter import build_montage, cut_clip, extract_thumbnail, probe_duration
from scorer import merge_into_chunks, score_chunks
from transcription import load_transcript, make_srt, transcribe

log = logging.getLogger("autocut.pipeline")

PAD_BEFORE = 0.5
PAD_AFTER = 1.2
MERGE_GAP = 4.0


def run_pipeline(job: dict[str, Any], options: dict[str, Any]) -> None:
    job_id = job["id"]
    language = _resolve_language(options)
    jobs.update(job_id, status="processing", stage="transcribe", progress=5, stage_detail="Распознаю речь (Whisper)")
    log.info("job %s: transcribe start", job_id)
    transcript = transcribe(job["video_path"], job["transcript_path"], language, job_id=job_id)
    segments = transcript["segments"]
    log.info("job %s: transcribed %d segments (lang=%s)", job_id, len(segments), transcript["language"])
    run_from_transcript(job, options, transcript)


def reprocess_pipeline(job: dict[str, Any], options: dict[str, Any]) -> None:
    """Пере-нарезать джоб, переиспользуя сохранённую транскрипцию."""
    if not job["video_path"] or not Path(job["video_path"]).exists():
        raise RuntimeError("Исходное видео не найдено на диске — перезагрузи файл")
    if not Path(job["transcript_path"]).exists():
        raise RuntimeError("Транскрипция не найдена — повтори нарезку заново")
    transcript = load_transcript(job["transcript_path"])
    clips_dir = Path(job["clips_dir"])
    for f in clips_dir.glob("clip_*"):
        if f.is_file():
            f.unlink(missing_ok=True)
    log.info("job %s: reprocess from transcript (lang=%s)", job["id"], transcript.get("language"))
    jobs.update(job["id"], status="processing", stage="score", progress=30)
    run_from_transcript(job, options, transcript)


def run_from_transcript(job: dict[str, Any], options: dict[str, Any], transcript: dict[str, Any]) -> None:
    job_id = job["id"]
    video_path = job["video_path"]
    clips_dir = job["clips_dir"]
    jobs.raise_if_cancelled(job_id)
    min_score = int(options.get("min_score", DEFAULT_MIN_SCORE))
    clip_min = float(options.get("clip_min_sec", DEFAULT_CLIP_MIN_SEC))
    clip_max = float(options.get("clip_max_sec", DEFAULT_CLIP_MAX_SEC))
    max_clips = int(options.get("max_clips", DEFAULT_MAX_CLIPS))
    burn_subs = bool(options.get("burn_subtitles", DEFAULT_BURN_SUBTITLES))
    aspect = options.get("aspect") or "original"
    if aspect not in ("original", "9_16_blur", "9_16_crop"):
        aspect = "original"

    segments = transcript["segments"]
    if not segments:
        raise RuntimeError("В транскрипции нет сегментов")

    chunks = merge_into_chunks(segments)
    if not chunks:
        raise RuntimeError("В видео не удалось распознать речь — чистая музыка или нет звуковой дорожки")
    jobs.raise_if_cancelled(job_id)

    total_chunks = len(chunks)
    jobs.update(
        job_id, stage="score", progress=35,
        stage_detail=f"Оценка интересности: 0/{total_chunks}",
    )

    def _score_progress(done: int) -> None:
        jobs.update(
            job_id,
            progress=35 + int(25 * done / total_chunks) if total_chunks else 60,
            stage_detail=f"Оценка интересности: {min(done, total_chunks)}/{total_chunks}",
        )
        jobs.raise_if_cancelled(job_id)

    chunks = score_chunks(chunks, progress_cb=_score_progress)
    log.info("job %s: scored %d chunks", job_id, len(chunks))
    jobs.update(job_id, progress=60)
    jobs.raise_if_cancelled(job_id)

    selected = sorted(
        [c for c in chunks if c["score"] >= min_score],
        key=lambda c: c["score"],
        reverse=True,
    )[:max_clips]
    if not selected:
        scored = [c for c in chunks if c["score"] > 0]
        if scored:
            selected = sorted(scored, key=lambda c: c["score"], reverse=True)[:max_clips]
    selected.sort(key=lambda c: c["start"])

    total_duration = probe_duration(video_path)
    clips = _assemble_clips(selected, segments, total_duration, clip_min, clip_max)
    log.info("job %s: %d clips after assembly (min_score=%s)", job_id, len(clips), min_score)

    if not clips:
        jobs.update(
            job_id, stage="score", progress=65,
            status="error",
            error=(
                f"Не найдено моментов с оценкой >= {min_score}. "
                "Попробуй снизить порог (иногда выходят неоднозначные видео)."
            ),
        )
        return

    jobs.update(job_id, stage="cut", progress=70, stage_detail=f"Нарезаю клипы: 0/{len(clips)}")
    log.info("job %s: cutting %d clips (aspect=%s, burn_subs=%s)", job_id, len(clips), aspect, burn_subs)
    clip_paths = []
    for i, clip in enumerate(clips):
        jobs.raise_if_cancelled(job_id)
        base = Path(clips_dir) / f"clip_{i:02d}"
        clip_file = str(base.with_suffix(".mp4"))
        thumb_file = str(base.with_suffix(".jpg"))
        srt_file: str | None = None
        if burn_subs and clip["segments"]:
            srt_file = Path_open_write(base.with_suffix(".srt"), make_srt(clip["segments"], offset=clip["start"]))
        cut_clip(video_path, clip["start"], clip["end"], clip_file, srt_file, aspect)
        extract_thumbnail(video_path, clip["start"], thumb_file)
        clip["file"] = clip_file
        clip["filename"] = Path(clip_file).name
        clip["thumb"] = Path(thumb_file).name
        clip_paths.append(clip_file)
        jobs.update(job_id, progress=70 + int(10 * (i + 1) / len(clips)), stage_detail=f"Нарезаю клипы: {i+1}/{len(clips)}")

    jobs.update(job_id, stage="montage", progress=85, stage_detail="Собираю монтаж")
    montage_duration = 0.0
    if clip_paths:
        jobs.raise_if_cancelled(job_id)
        montage_duration = build_montage(clip_paths, job["montage_path"])
        log.info("job %s: montage built (%.1fs)", job_id, montage_duration)
    jobs.raise_if_cancelled(job_id)

    result = {
        "clips": [
            {
                "id": i,
                "title": clip["title"],
                "start": round(clip["start"], 2),
                "end": round(clip["end"], 2),
                "duration": round(clip["end"] - clip["start"], 2),
                "score": clip["score"],
                "reason": clip["reason"],
                "segment_count": len(clip["segments"]),
                "filename": clip["filename"],
                "thumb": clip["thumb"],
            }
            for i, clip in enumerate(clips)
        ],
        "montage_duration": round(montage_duration, 2),
        "chunk_count": len(chunks),
        "language": transcript.get("language"),
        "options": {
            "min_score": min_score, "clip_min_sec": clip_min, "clip_max_sec": clip_max,
            "burn_subtitles": burn_subs, "aspect": aspect,
        },
    }
    jobs.update(job_id, status="completed", stage="done", progress=100, result=result)
    log.info("job %s: completed with %d clips", job_id, len(clips))


def _resolve_language(options: dict[str, Any]) -> str | None:
    language = (options.get("language") or WHISPER_LANGUAGE or DEFAULT_LANGUAGE).strip()
    if not language or language.lower() == "auto":
        return None
    return language


def _assemble_clips(
    selected: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    total_duration: float,
    clip_min: float,
    clip_max: float,
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for ch in selected:
        if groups and ch["start"] - groups[-1][-1]["end"] <= MERGE_GAP:
            groups[-1].append(ch)
        else:
            groups.append([ch])

    clips = []
    for group in groups:
        start = max(0.0, group[0]["start"] - PAD_BEFORE)
        end = min(total_duration, group[-1]["end"] + PAD_AFTER)
        if end - start > clip_max:
            # слишком длинная сцена: центрируем клип на самом ярком окне, а не берём «начало»
            top = max(group, key=lambda c: c["score"])
            mid = (top["start"] + top["end"]) / 2
            start = min(max(0.0, mid - clip_max / 2), max(0.0, total_duration - clip_max))
            end = start + clip_max
        if end - start < clip_min:
            start = max(0.0, start)
            end = min(total_duration, start + clip_min)
        if end - start < clip_min or end <= start:
            # у конца видео не хватает длины под клип — пропускаем
            continue
        top = max(group, key=lambda c: c["score"])
        title = " · ".join(dict.fromkeys([ch["title"] for ch in group]))
        clip_segments = [
            {
                "start": s["start"], "end": s["end"],
                "words": s.get("words", []), "text": s.get("text", ""),
                "clip_id": -1,
            }
            for s in segments
            if s["start"] < end and s["end"] > start
        ]
        clips.append({
            "start": start, "end": end, "score": top["score"],
            "title": title, "reason": top["reason"], "segments": clip_segments,
        })
    return clips


def Path_open_write(path: Path, content: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return str(path)