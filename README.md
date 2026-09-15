# AutoCut — автонарезка хайлайтов с субтитрами

Локальный инструмент: **перетащил видео → получил нарезку самых интересных моментов**. Всё работает офлайн, без платных API моделей.

## Как работает

```
загрузка видео
   → faster-whisper распознаёт речь (с таймкодами)
   → qwen2.5 (Ollama, локально) оценивает фрагменты 0–100
   → ffmpeg режет лучшие моменты в клипы
   → субтитры выжигаются прямо в кадр
   → склеивается общий ролик highlights.mp4
```

## Стек

- **Frontend:** React + Vite + TypeScript (drag&drop, прогресс, галерея клипов)
- **Backend:** FastAPI (Python 3.11+), in-memory джобы, без БД
- **AI:** faster-whisper + Ollama (любая OpenAI-совместимая модель в `/v1`)
- **Видео:** ffmpeg / ffprobe

## Требования

- Python 3.11+
- Node.js 20+
- [ffmpeg](https://ffmpeg.org/download.html) в PATH
- [Ollama](https://ollama.com/download) с моделью (по умолчанию `qwen2.5:7b-instruct`):
  ```
  ollama pull qwen2.5:7b-instruct
  ```

## Запуск

```bash
# бэкенд
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows
.venv\Scripts\python -m uvicorn main:app --port 8000

# фронтенд (в другом терминале)
cd frontend
npm install
npm run dev        # → http://localhost:5173
```

Или одной командой: `.\start.ps1` (Windows; поставит окружения при первом запуске и поднимет всё сам).

## Настройка (env-переменные)

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Адрес Ollama |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Модель |
| `WHISPER_MODEL` | `small` | Faster-Whisper (`tiny`/`base`/`small`/`medium`) |
| `WHISPER_LANGUAGE` | пусто (авто) | Задать язык, напр. `en`, `ru` |
| `AUTOCUT_DATA_DIR` | `./data` | Куда складывать результаты |

## Что умеет UI

- Порог «интересности» (0–100): выше порога — больше клипов, но строже
- Максимум клипов
- **Формат клипов:** вертикальный 9:16 с блюр-фоном (Shorts/Reels), 9:16 с обрезкой или исходный
- Переключатель «сжечь субтитры в кадр»
- По каждому клипу: балл, заголовок, причина, превью и скачивание
- Общий ролик-монтаж со всеми хайлайтами

## Структура

```
autocut/
  backend/
    main.py          # FastAPI: upload / process / job status / файлы
    pipeline.py      # оркестрация: транскрипция → скоринг → нарезка → монтаж
    transcription.py # faster-whisper + генерация SRT
    scorer.py        # оценка фрагментов через Ollama
    cutter.py        # ffmpeg: нарезка, субтитры, превью, конкат
    jobs.py          # in-memory хранилище джобов
    config.py        # env-конфигурация
  frontend/          # React + Vite
  data/              # загрузки и результаты (создаётся автоматически)
```

## API

```
GET  /api/health                     # готовность ffmpeg / Ollama
POST /api/upload                     # multipart file → { job_id }
POST /api/process/{job_id}           # старт pipeline с options
GET  /api/jobs/{job_id}              # статус + прогресс + результат
GET  /api/jobs/{job_id}/clips/<file> # скачать клип / млнтаж
GET  /api/jobs/{job_id}/thumbs/<file> # превью
```

## Известное

- Первый запуск скачивает модель Whisper (small ≈ 500 МБ).
- Качество распознавания зависит от модели Whisper — для коротких роликов `medium` заметно точнее.
- Капчу не решает, ссылки не скачивает — работает только с локальными файлами.