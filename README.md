# AutoCut

Локальный конвейер: ссылка (YouTube, RuTube, …) или файл → вертикальные клипы 1080×1920 с субтитрами.

Что делает:

1. скачивает видео по ссылке через yt-dlp (YouTube, RuTube и другие поддерживаемые сайты) или берёт локальный файл;
2. находит N самых «живых» фрагментов длиной 20–60 секунд по громкости, речи и сменам сцен;
3. распознаёт речь через faster-whisper и вжигает небольшие субтитры снизу (отключается `--no-subtitles`);
4. сохраняет клипы по папкам на каждое исходное видео.

## Установка

Нужны `ffmpeg`/`ffprobe` (8.x) и Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,whisper]"
```

Стек распознавания речи вынесен в extra `whisper` (ctranslate2/onnxruntime/av — тяжёлые).
Без него приложение запускается, но субтитры не сделает.

Первый запуск Whisper скачает модель (~500 МБ для `small`) в `~/.cache/huggingface/hub`.
Если загрузка падает с `CAS Client Error` / `File reconstruction error` (сбой Xet-бэкенда
Hugging Face), повторите с отключённым Xet:

```bash
HF_HUB_DISABLE_XET=1 .venv/bin/autocut run ./video.mp4
```

Кодек: H.264. Энкодер выбирается автоматически (libx264 → VAAPI → NVENC → libopenh264 →
mpeg4), потому что в Fedora-сборке `ffmpeg-free` нет libx264. Для лучшего качества
поставьте полный ffmpeg из RPM Fusion.

## Веб

```bash
.venv/bin/autocut web
```

Откройте http://127.0.0.1:8000, вставьте ссылку (YouTube, RuTube, …) или путь к локальному файлу.
Галочка «Субтитры» снимается, если клипы нужны без вжигаемых субтитров.

## CLI

```bash
.venv/bin/autocut run "https://youtu.be/..." --clips 5
.venv/bin/autocut run "https://rutube.ru/video/..." --clips 3
.venv/bin/autocut run ./video.mp4 --clips 3 --format crop
.venv/bin/autocut run ./video.mp4 --no-subtitles
.venv/bin/autocut trending --region RU
```

Прокси: `--proxy socks5://127.0.0.1:1080` или `AUTOCUT_PROXY`.

## Результат

```
output/<канал>/<video_id>_<название>/
  clips/clip_01_score-0.87.mp4
  clips/clip_01.ass        # только при включённых субтитрах
  clips/clip_01.jpg
  transcript.srt
  transcript.json
  metadata.json
  source.json
  job.log
```

## Настройки

`config.example.yaml` → скопируйте в `config.yaml` или используйте переменные
`AUTOCUT_OUTPUT`, `AUTOCUT_WORKDIR`, `AUTOCUT_MODEL`, `AUTOCUT_PROXY`,
`AUTOCUT_COOKIES`, `AUTOCUT_DEVICE`, `AUTOCUT_COMPUTE_TYPE`.

## Ограничения

- Скачивание идёт через yt-dlp: кроме YouTube поддерживаются RuTube и другие сайты из списка yt-dlp. С этой машины YouTube блокируется, RuTube работает.
- `trending` работает только с лентой популярного YouTube.
- Речь распознаётся локально на CPU; `small` — компромисс скорости и качества.
- Права на исходное видео — ответственность пользователя.
