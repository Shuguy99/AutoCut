# Конфигурация

## Приоритет

```
значения по умолчанию
  └─ config.yaml (если передан --config или файл существует)
       └─ переменные окружения AUTOCUT_*
            └─ флаги CLI (--output, --keep-work, --ascii-slug)
```

`load_config()` не ищет `config.yaml` автоматически: передайте его явно:

```bash
autocut run video.mp4 --config ./config.yaml
autocut web --config ./config.yaml
autocut app --config ./config.yaml
```

Пример — `config.example.yaml` в корне репозитория.

## Параметры

| Ключ YAML | Переменная | По умолчанию | Смысл |
|---|---|---|---|
| `output_dir` | `AUTOCUT_OUTPUT` | `output` | папка готовых клипов |
| `work_dir` | `AUTOCUT_WORKDIR` | `work` | временные файлы и кэш |
| `model` | `AUTOCUT_MODEL` | `small` | модель Whisper |
| `device` | `AUTOCUT_DEVICE` | `cpu` | `cpu` или `cuda` |
| `compute_type` | `AUTOCUT_COMPUTE_TYPE` | `int8` | `int8`, `float16`, `float32` |
| `proxy` | `AUTOCUT_PROXY` | `null` | прокси для yt-dlp |
| `cookies` | `AUTOCUT_COOKIES` | `null` | путь к cookies.txt |
| `ascii_slug` | `AUTOCUT_ASCII_SLUG` | `false` | только ASCII в именах папок |
| `keep_work` | `AUTOCUT_KEEP_WORK` | `false` | не удалять `work/<job_id>` |
| `language` | `AUTOCUT_LANGUAGE` | `null` | язык речи (`ru`, `en`, …) |
| `max_height` | `AUTOCUT_MAX_HEIGHT` | `1080` | максимальная высота скачивания |

Булевы значения: `1/true/yes/on` (регистр не важен).
`max_height` должен быть целым числом ≥ 240.
Пути `~` раскрываются; относительные пути считаются от текущей рабочей папки.

## Параметры задачи (`JobOptions`)

Используются в CLI, веб-форме и API.

| Поле | Тип | По умолчанию | Диапазон | Смысл |
|---|---|---|---|---|
| `clips` | int | 5 | 1–50 | сколько клипов сделать |
| `min_duration` | float | 20 | 1–120 | минимальная длина клипа, с |
| `max_duration` | float | 60 | 1–180 | максимальная длина клипа, с |
| `target_duration` | float | 30 | 1–120 | целевая длина; зажимается в min–max |
| `layout` | `blur`/`crop` | `blur` | — | фон или центральный кроп |
| `subtitles` | bool | `true` | — | вжигать ли ASS |
| `variation` | `off`/`subtle`/`strong` | `subtle` | — | различия стиля и кадрирования |
| `style` | `auto`/`clean`/`bold`/`karaoke`/`minimal` | `auto` | — | стиль субтитров |
| `caption_mode` | `phrase`/`word` | `phrase` | — | фразы или подсветка слов |
| `hook` | bool | `true` | — | хук в начале клипа |
| `end_card` | bool | `true` | — | финальная плашка |
| `watermark` | string \| null | `null` | до 40 символов | водяной знак |
| `loudnorm` | bool | `true` | — | громкость −14 LUFS |
| `safe_zones` | bool | `true` | — | отступ под интерфейс TikTok |
| `proxy` | string \| null | `null` | — | переопределяет `config.proxy` |
| `cookies` | string \| null | `null` | — | переопределяет `config.cookies` |
| `model` | string \| null | `null` | — | переопределяет `config.model` |
| `language` | string \| null | `null` | — | переопределяет `config.language` |

Валидатор `JobOptions` поднимает `ValidationError`, если
`min_duration > max_duration`; CLI печатает понятное сообщение и выходит с
кодом 2, API отвечает `422`.

## CLI-флаги

```
--clips N          --min SECONDS      --max SECONDS
--target SECONDS   --format blur|crop --no-subtitles
--variation MODE   --style STYLE      --caption-mode MODE
--watermark TEXT   --no-hook          --no-end-card
--no-loudnorm      --no-safe-zones
--model NAME       --language LANG    --proxy URL
--cookies FILE     --output DIR       --config FILE
--keep-work        --ascii-slug       --json
```

`--variation`: `off`, `subtle`, `strong` (по умолчанию `subtle`).
`--style`: `auto`, `clean`, `bold`, `karaoke`, `minimal` (по умолчанию `auto`).
`--caption-mode`: `phrase` или `word` (по умолчанию `phrase`).

Для `run` дополнительно:

```
--playlist-limit N   # 1–50, по умолчанию 1
```

`--playlist-limit > 1` включает последовательную обработку плейлиста; для
локального файла флаг игнорируется.

## Переменные, влияющие на Whisper/Hugging Face

| Переменная | Зачем |
|---|---|
| `HF_HUB_DISABLE_XET=1` | обойти сбой Xet-бэкенда при скачивании модели |
| `HF_HOME` | перенести кэш моделей |

## Куда пишутся результаты

```
<output_dir>/<channel-slug>/<video_id>_<title-slug>[_2]/
  clips/clip_01_score-0.87.mp4
  clips/clip_01.ass          # если есть субтитры или плашки
  clips/clip_01.jpg
  clips/clip_01_publish.json
  transcript.srt
  transcript.json
  publish.json
  diversity.json
  metadata.json
  source.json
  job.log
```

Существующая папка не перезаписывается: добавляется `_2`, `_3`, …
Кэш транскриптов: `<work_dir>/cache/transcripts/`.

Подробнее про вариативность, `diversity.json` и публикацию — в
[uniqueness.md](uniqueness.md).
