# Архитектура

## Поток данных

```
источник (URL / локальный файл)
  └─ downloader ──► work/<job_id>/source.*
       └─ media ───► audio.wav, RMS-окна, смены сцен
            └─ transcribe (faster-whisper) ──► Transcript (words, segments)
                 └─ scoring ──► ClipCandidate[] (start, end, score, parts)
                      └─ subtitles ──► Cue[] ──► clip_NN.ass
                           └─ render ──► clip_NN.mp4 + clip_NN.jpg
                                └─ storage ──► output/<канал>/<id>_<title>/
```

Каждый модуль имеет один контракт и не знает деталей соседей:

| Модуль | Ответственность |
|---|---|
| `autocut/config.py` | defaults → `config.yaml` → env → CLI-флаги |
| `autocut/models.py` | dataclass-модели и `JobOptions` (pydantic) |
| `autocut/downloader.py` | yt-dlp, локальные файлы, плейлисты, `trending` |
| `autocut/feed.py` | лента рекомендаций RuTube (JSON API) |
| `autocut/media.py` | ffprobe/ffmpeg: метаданные, аудио, сцены, превью, выбор энкодера |
| `autocut/transcribe.py` | faster-whisper, WAV-декодер, кэш моделей |
| `autocut/scoring.py` | оценка кандидатов и NMS |
| `autocut/subtitles.py` | группировка слов, ASS/SRT |
| `autocut/render.py` | вертикальный кадр и вжигание субтитров |
| `autocut/storage.py` | slug, уникальные папки, JSON/SRT |
| `autocut/pipeline.py` | оркестрация одного job, прогресс, отмена |
| `autocut/jobs.py` | in-memory очередь, один worker-поток |
| `autocut/web/app.py` | FastAPI: API, SSE, статика, отдача файлов |
| `autocut/desktop.py` | uvicorn в потоке + окно приложения |

`pipeline.py` не содержит вызовов ffmpeg/yt-dlp напрямую — только через модули.

## Жизненный цикл задачи

1. `JobManager.submit()` создаёт `Job` и кладёт её в очередь (не более `max_queue`
   ожидающих; в вебе — 20).
2. Единственный worker берёт задачу, ставит `running` и передаёт в
   `run_pipeline()` функцию `progress(stage, percent, message)`.
3. `run_pipeline()` пишет `job.log`, проходит этапы
   `download → analyze → transcribe → score → render → done`.
4. Результат и ошибка сохраняются в `Job`; SSE-поток отдаёт изменения
   веб-интерфейсу. При отмене проверяется `is_cancelled()` между этапами и
   между клипами.
5. `shutdown()` закрывает менеджер: новые задачи не принимаются, worker
   завершается после текущей.

## Кэш транскриптов

`work/cache/transcripts/<video_id>_<model>_<language>.json`.

Ключ включает модель и язык: смена `--model base` или `--language en` не
подхватывает чужой кэш. Локальные файлы получают `video_id` из SHA-1 пути и
mtime, поэтому изменение файла инвалидирует кэш.

## Оценка фрагментов

```
score = 0.40 * energy + 0.25 * speech + 0.15 * scenes
      + 0.10 * hooks  + 0.10 * completeness
```

- `energy` — RMS по окнам 0.5 с, нормализованный по 10/90 перцентилям;
- `speech` — доля окна, покрытая словами Whisper;
- `scenes` — число смен сцены (до 3 учитывается полностью);
- `hooks` — слова-хуки ru/en на 100 символов;
- `completeness` — близость границ к границе предложения.

Кандидаты перебираются с шагом 1 с, границы притягиваются к границам фраз,
пересечение более 30 % отбрасывается (NMS).

## Субтитры и рендер

- Слова группируются по 3–5, ≤ 42 символа в строке, ≤ 2 строки, 0.8–4 с.
- ASS: `PlayRes 1080×1920`, Liberation Sans 48, обводка 4, `MarginV=230`.
- Тайминги обрезаются по границам клипа и сдвигаются в 0.
- `blur`: размытый фон + исходник по центру; `crop`: заполнение и центральный кроп.
- Энкодер выбирается коротким тестом: `libx264 → VAAPI → NVENC →
  libopenh264 → mpeg4`. H.264, AAC 128 kbps 48 kHz, 30 fps, `+faststart`.

## Отказоустойчивость

- Ошибка одного клипа не валит задачу: клип получает `error`, остальные
  сохраняются.
- Если не отрендерился ни один клип, папка результата удаляется, задача
  завершается ошибкой.
- Видео без аудиодорожки обрабатывается без транскрипции и субтитров.
- При `keep_work: false` рабочая папка удаляется; лог копируется в результат.
- Отмена — best-effort: текущий вызов ffmpeg/Whisper не прерывается, но
  следующие шаги не запускаются.

## Ограничения

- Один worker: задачи выполняются последовательно, параллелизм не
  поддерживается намеренно (Whisper и ffmpeg и так загружают CPU/GPU).
- Очередь и статусы хранятся в памяти и теряются при перезапуске.
- YouTube может быть недоступен без прокси; RuTube используется как источник
  ленты и альтернативный сайт yt-dlp.
- Авто-рефрейминг по лицам не реализован: только `blur` и `crop`.
