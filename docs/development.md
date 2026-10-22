# Разработка

## Окружение

Нужны Python 3.11+, `ffmpeg` и `ffprobe` (проверено на 8.x).

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,whisper]"
```

Для нативного окна: `.venv/bin/pip install -e ".[app]"`.

## Тесты

```bash
.venv/bin/python -m pytest
```

Что покрыто:

- `test_config.py` — приоритет YAML/env, булевы значения, `max_height`;
- `test_media.py`, `test_scoring.py`, `test_subtitles.py` — анализ и субтитры;
- `test_variation.py` — стили, хуки, подписи и diversity-отчёт;
- `test_downloader.py` — yt-dlp-заглушки, плейлисты, битые поля;
- `test_pipeline.py` — полный цикл на синтетическом видео, кэш, отсутствие
  аудио, отключённые субтитры, варианты и publish-файлы;
- `test_jobs.py` — очередь, отмена, shutdown;
- `test_api.py` — FastAPI через `TestClient`, валидация, path traversal;
- `test_desktop.py` — выбор порта, URL, запуск/остановка сервера.

Интеграционные тесты генерируют видео через ffmpeg (`tests/conftest.py`), сеть
не используется: `YoutubeDL` и `transcribe` подменяются.

Один тест:

```bash
.venv/bin/python -m pytest tests/test_api.py -k feed -vv
```

## Структура

```
autocut/            пакет
  web/static/       HTML/CSS/JS без сборщика
tests/              pytest
docs/               эта документация
docs/superpowers/   история проектных решений
work/               временные файлы (не коммитится)
output/             результаты (не коммитится)
```

## Соглашения

- Python 3.11+, `from __future__ import annotations`, type hints.
- Ошибки — отдельные исключения (`DownloadError`, `TranscriptionError`,
  `RenderError`, `MediaError`, `PipelineError`), не голый `RuntimeError`.
- Пользовательские сообщения — по-русски; логи и имена — по-английски.
- В `pipeline.py` не должно быть прямых вызовов ffmpeg/yt-dlp.
- Новое поведение сопровождается тестом; UI проверяется вручную или через
  `TestClient`.

## Ручная проверка веба

```bash
.venv/bin/autocut web --port 8010
curl -s http://127.0.0.1:8010/api/health
curl -s "http://127.0.0.1:8010/api/feed?limit=3"
curl -s -X POST http://127.0.0.1:8010/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"source":"./video.mp4","options":{"clips":1}}'
```

`autocut app` проверяется отдельно: окно должно открыться после ответа
`/api/health`, а сервер — остановиться после закрытия окна (`Ctrl+C` в режиме
обычного браузера).

## Отладка ffmpeg

`render.py` показывает последние 3000 символов stderr. Чтобы увидеть команду
целиком, запустите её вручную из вывода ошибки. Проверка энкодеров:

```bash
ffmpeg -hide_banner -encoders | grep -E "264|mpeg4"
```

## Кэш и очистка

```bash
rm -rf work/cache/transcripts   # пересоздать транскрипты
rm -rf work/*                   # рабочие файлы (осторожно: активные задачи)
```

Результаты лежат в `output/` и не удаляются автоматически.
