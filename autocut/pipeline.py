"""Оркестрация одного задания: источник → анализ → субтитры → клипы."""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np

from .config import Config
from .downloader import download, is_url, prepare_local
from .media import compute_rms_windows, detect_scenes, extract_audio, probe
from .models import JobOptions, SourceInfo, Transcript
from .render import render_clip, render_preview
from .scoring import find_highlights
from .storage import (
    create_result_dir,
    load_transcript,
    save_transcript,
    slugify,
    write_json,
    write_srt,
)
from .subtitles import Cue, group_words, write_ass
from .transcribe import transcribe

ProgressFn = Callable[[str, float, str], None]

logger = logging.getLogger(__name__)


def _preview_time(cues: list[Cue], start: float, end: float) -> float:
    """Момент для превью: середина реплики, ближайшей к центру клипа.

    Иначе кадр может попасть в паузу между субтитрами, и превью будет без них.
    """
    length = max(0.1, end - start)
    if not cues:
        return length / 2
    center = start + length / 2
    cue = min(cues, key=lambda item: abs((item.start + item.end) / 2 - center))
    return min(max(0.0, (cue.start + cue.end) / 2 - start), length - 0.05)


class PipelineError(RuntimeError):
    pass


class CancelledError(PipelineError):
    pass


def _check_cancel(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled and is_cancelled():
        raise CancelledError("задача отменена")


def _source_dict(info: SourceInfo) -> dict:
    value = asdict(info)
    value["source_path"] = str(info.source_path)
    return value


def _cached_transcript(cache_dir: Path, video_id: str, model: str, language: str | None):
    """Читает кэш транскрипта с учётом модели и языка.

    Повреждённый файл кэша не должен ронять задание: он удаляется, а
    транскрипт пересчитывается заново.
    """
    key = "_".join(
        (
            slugify(video_id, ascii_only=True, max_len=40),
            slugify(model, ascii_only=True, max_len=30),
            slugify(language or "auto", ascii_only=True, max_len=12),
        )
    )
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None, path
    try:
        return load_transcript(path), path
    except (OSError, ValueError, TypeError, KeyError):
        logger.warning("повреждённый кэш транскрипта, пересчитываю: %s", path)
        try:
            path.unlink()
        except OSError:
            pass
        return None, path


def run_pipeline(
    source: str,
    options: JobOptions,
    config: Config,
    progress: ProgressFn | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Обрабатывает один источник и возвращает описание результата.

    Исключения не глотаются: ``JobManager`` переводит их в статус ``failed``,
    а CLI печатает понятное сообщение.
    """
    report = progress or (lambda stage, pct, msg: None)
    output_dir = Path(config.output_dir).expanduser().resolve()
    work_root = Path(config.work_dir).expanduser().resolve()
    job_id = uuid.uuid4().hex[:12]
    work_dir = work_root / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = work_root / "cache" / "transcripts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    log_path = work_dir / "job.log"
    result_dir: Path | None = None
    clips: list[dict] = []

    def emit(stage: str, percent: float, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} [{stage}] {percent:.0f}% {message}\n")
        report(stage, percent, message)

    try:
        proxy = options.proxy or config.proxy
        cookies = options.cookies or (
            str(config.cookies) if config.cookies else None
        )
        model = options.model or config.model
        language = options.language or config.language

        emit("download", 2, "подготовка источника")
        if is_url(source):
            info = download(
                source, work_dir, proxy=proxy, cookies=cookies,
                max_height=config.max_height,
            )
        else:
            info = prepare_local(source)
        _check_cancel(is_cancelled)

        emit("analyze", 20, "чтение метаданных")
        media = probe(info.source_path)
        duration = media.duration or info.duration
        if duration <= 0:
            raise PipelineError("не удалось определить длительность видео")
        scenes = detect_scenes(info.source_path)
        if media.has_audio:
            audio = extract_audio(info.source_path, work_dir / "audio.wav")
            rms = compute_rms_windows(audio)
        else:
            emit(
                "analyze", 25,
                "аудиодорожка отсутствует — клипы будут без субтитров",
            )
            audio = None
            rms = np.zeros(1, dtype=np.float32)
        _check_cancel(is_cancelled)

        emit("transcribe", 40, "распознавание речи")
        transcript: Transcript | None = None
        cache_path: Path | None = None
        if audio is not None:
            transcript, cache_path = _cached_transcript(
                cache_dir, info.video_id, model, language
            )
        if transcript is None:
            if audio is None:
                transcript = Transcript(
                    language=language or "unknown",
                    words=[], segments=[], text="",
                )
            else:
                transcript = transcribe(
                    audio, model_name=model, device=config.device,
                    compute_type=config.compute_type, language=language,
                )
                if cache_path is not None:
                    save_transcript(cache_path, transcript)
        _check_cancel(is_cancelled)

        emit("score", 65, "поиск интересных фрагментов")
        candidates = find_highlights(
            duration, rms, transcript.words, scenes,
            count=options.clips,
            min_duration=options.min_duration,
            max_duration=options.max_duration,
            target_duration=options.target_duration,
        )
        if not candidates:
            raise PipelineError("не удалось найти подходящие фрагменты")
        _check_cancel(is_cancelled)

        result_dir = create_result_dir(
            output_dir, info.channel, info.video_id, info.title,
            ascii_slug=config.ascii_slug,
        )
        cliplist = [
            (index + 1, candidate)
            for index, candidate in enumerate(candidates)
        ]
        for index, candidate in cliplist:
            _check_cancel(is_cancelled)
            emit(
                "render", 65 + 30 * (index - 1) / len(cliplist),
                f"рендер клипа {index} из {len(cliplist)}",
            )
            try:
                cues: list[Cue] = []
                ass_path: Path | None = None
                if options.subtitles and transcript.words:
                    clip_words = [
                        word for word in transcript.words
                        if word.end > candidate.start
                        and word.start < candidate.end
                    ]
                    cues = group_words(clip_words)
                    ass_path = work_dir / f"clip_{index:02d}.ass"
                    write_ass(cues, ass_path, candidate.start, candidate.end)
                filename = (
                    f"clip_{index:02d}_score-{candidate.score:.2f}.mp4"
                )
                out_path = result_dir / "clips" / filename
                render_clip(
                    info.source_path, candidate.start, candidate.end,
                    ass_path, out_path, layout=options.layout,
                )
                preview = render_preview(
                    out_path, result_dir / "clips" / f"clip_{index:02d}.jpg",
                    at=_preview_time(cues, candidate.start, candidate.end),
                )
                final_ass: str | None = None
                if ass_path is not None:
                    copied = result_dir / "clips" / f"clip_{index:02d}.ass"
                    shutil.copy2(ass_path, copied)
                    final_ass = str(copied)
                clips.append({
                    "index": index,
                    "file": str(out_path),
                    "preview": str(preview),
                    "subtitle": final_ass,
                    "start": candidate.start,
                    "end": candidate.end,
                    "duration": round(candidate.end - candidate.start, 3),
                    "score": candidate.score,
                    "parts": candidate.parts,
                    "text": " ".join(
                        word.text for word in transcript.words
                        if word.end > candidate.start
                        and word.start < candidate.end
                    ),
                })
            except CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                emit("render", 65, f"клип {index} не удался: {exc}")
                clips.append({
                    "index": index,
                    "start": candidate.start,
                    "end": candidate.end,
                    "duration": round(candidate.end - candidate.start, 3),
                    "score": candidate.score,
                    "parts": candidate.parts,
                    "error": str(exc),
                })

        if not any("file" in clip for clip in clips):
            raise PipelineError("ни один клип не удалось отрендерить")

        save_transcript(result_dir / "transcript.json", transcript)
        write_srt(transcript, result_dir / "transcript.srt")
        write_json(result_dir / "source.json", {
            "source": _source_dict(info),
            "options": options.model_dump(),
        })
        write_json(result_dir / "metadata.json", {
            "source": _source_dict(info),
            "options": options.model_dump(),
            "duration": duration,
            "language": transcript.language,
            "clips": clips,
        })
        shutil.copy2(log_path, result_dir / "job.log")
        emit("done", 100, "готово")
        return {
            "result_dir": str(result_dir),
            "source": _source_dict(info),
            "clips": clips,
            "duration": duration,
        }
    except CancelledError:
        emit("cancelled", 0, "задача отменена")
        raise
    except Exception as exc:
        emit("failed", 0, str(exc))
        raise
    finally:
        if result_dir is not None and not any("file" in clip for clip in clips):
            shutil.rmtree(result_dir, ignore_errors=True)
        if not config.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)
