# HTTP API

Сервер поднимается командой `autocut web` (по умолчанию `http://127.0.0.1:8000`)
или `autocut app` (порт выбирается автоматически). Все ответы — JSON, кроме
статики и файлов результатов. Аутентификации нет: сервис рассчитан на localhost.

## Эндпоинты

### `GET /`

HTML-интерфейс.

### `GET /health`, `GET /api/health`

```json
{"status": "ok"}
```

### `GET /api/feed`

Лента рекомендаций RuTube.

| Параметр | Тип | По умолчанию | Ограничение |
|---|---|---|---|
| `offset` | int | 0 | ≥ 0 |
| `limit` | int | 12 | 1–24 |

```json
{
  "items": [{
    "id": "8c31b60faaca8547a2c1ec265fae39e8",
    "title": "Название",
    "channel": "Канал",
    "duration": 600.0,
    "views": 12345,
    "thumbnail": "https://...",
    "url": "https://rutube.ru/video/.../",
    "created_at": "2026-10-01T10:00:00"
  }],
  "next_offset": 50,
  "has_more": true
}
```

В ленту попадают только ролики длительностью 2–60 минут; удалённые, прямые
эфиры и записи без длительности отбрасываются. `next_offset` — курсор для
следующей страницы, `has_more` — признак, что сырая страница была заполнена.

Ошибки: `422` — неверные параметры, `502` — RuTube недоступен.

### `POST /api/playlist`

Список видео плейлиста без скачивания (flat-извлечение yt-dlp).

```json
{
  "url": "https://rutube.ru/plst/308547/",
  "limit": 30,
  "proxy": "socks5://127.0.0.1:1080"
}
```

| Поле | Тип | По умолчанию | Ограничение |
|---|---|---|---|
| `url` | string | — | непустая строка, обрезается |
| `limit` | int | 30 | 1–50 |
| `proxy` | string \| null | `null` | берётся из конфига, если не задан |

```json
{
  "title": "Плейлист",
  "items": [{
    "video_id": "v1",
    "title": "Первое",
    "channel": "Канал",
    "duration": 120.0,
    "url": "https://rutube.ru/video/v1/",
    "thumbnail": "https://..."
  }],
  "truncated": true
}
```

`duration` может быть `null`, если сайт не отдал её в flat-режиме.
Ошибки: `400` — это не плейлист, `422` — пустой `url`/неверный `limit`,
`502` — сеть или yt-dlp.

### `POST /api/upload`

Загрузить локальное видео из веб-интерфейса (drag&drop или выбор файла).

`multipart/form-data`, поле `file`. Допустимы медиаформаты, которые понимает
ffmpeg; размер — до 4 ГиБ. Файл сохраняется в `<work_dir>/uploads/` с коротким
случайным префиксом.

```json
{"path": "/abs/work/uploads/8f3a1c0b2d4e_video.mp4", "name": "video.mp4", "size": 12345678}
```

Ошибки: `400` — пустой файл или неизвестное расширение, `413` — файл больше
4 ГиБ. Полученный `path` можно передать в `POST /api/jobs` как `source`.

### `POST /api/jobs`

Создать одну задачу.

```json
{
  "source": "https://rutube.ru/video/.../",
  "options": {
    "clips": 5,
    "preset": "custom",
    "min_duration": 20,
    "max_duration": 60,
    "target_duration": 30,
    "layout": "blur",
    "crop_focus": "center",
    "ranges": [[12, 42], [65, 100]],
    "subtitles": true,
    "variation": "subtle",
    "style": "auto",
    "caption_mode": "phrase",
    "hook": true,
    "end_card": true,
    "watermark": "@nick",
    "loudnorm": true,
    "safe_zones": true,
    "proxy": null
  }
}
```

`source` обрезается; пустая строка → `422`. Все поля `options`
необязательны, значения по умолчанию — в `JobOptions`.

| Поле | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `preset` | `custom`/`podcast`/`talking_head`/`cinematic`/`shorts` | `custom` | готовый набор оформления |
| `layout` | `blur`/`crop` | `blur` | фон или кроп 9:16 |
| `crop_focus` | `center`/`left`/`right` | `center` | смещение кропа |
| `ranges` | `[[start,end], …]` \| null | `null` | ручные диапазоны; отключает автоанализ |
| `variation` | `off`/`subtle`/`strong` | `subtle` | сила различий между клипами |
| `style` | `auto`/`clean`/`bold`/`karaoke`/`minimal` | `auto` | стиль субтитров |
| `caption_mode` | `phrase`/`word` | `phrase` | фразы или подсветка слов |
| `hook` | bool | `true` | хук в начале клипа |
| `end_card` | bool | `true` | финальная плашка |
| `watermark` | string \| null | `null` | водяной знак (до 40 символов) |
| `loudnorm` | bool | `true` | громкость −14 LUFS |
| `safe_zones` | bool | `true` | отступ под интерфейс TikTok |

Ошибка `422` — неизвестный стиль/режим, слишком длинный `watermark` или
некорректный диапазон (`end <= start`, длина вне 1–300 с, больше 50 пар).
Если `ranges` задан, поля `clips`, `min_duration`, `max_duration` и
`target_duration` не влияют на нарезку. Если `preset` не `custom`, его
значения переопределяют `layout`, `crop_focus`, `variation`, `style`,
`caption_mode`, длительности, `hook`, `end_card`, `loudnorm` и `safe_zones`.
Ошибка `429` — очередь заполнена.

Ответ — объект задачи (см. ниже) со статусом `queued`.

### `POST /api/jobs/batch`

Пакетный запуск из режима «Плейлист».

```json
{
  "sources": ["https://rutube.ru/video/a/", "https://rutube.ru/video/b/"],
  "options": {"clips": 3}
}
```

- пустые строки отбрасываются, остальные обрезаются;
- после очистки должно остаться 1–20 источников;
- все задачи ставятся атомарно: если свободных мест меньше, не ставится ни одна.

```json
{"jobs": [{"id": "...", "status": "queued"}]}
```

Ошибки: `422` — нет валидных источников или больше 20, `429` — очередь полна.

### `GET /api/jobs`

Список задач, новые сверху.

### `GET /api/jobs/{job_id}`

Одна задача. `404`, если id неизвестен.

Пример задачи:

```json
{
  "id": "8f3a1c0b2d4e",
  "source": "https://rutube.ru/video/.../",
  "options": {"clips": 5, "subtitles": true},
  "status": "running",
  "stage": "render",
  "progress": 72.0,
  "message": "рендер клипа 3 из 5",
  "result": null,
  "error": null,
  "created_at": 1761000000.0
}
```

`status`: `queued | running | done | failed | cancelled`.
`stage`: `queued | start | download | analyze | transcribe | score | render |
done | failed | cancelled`.

Для завершённой задачи `result` содержит:

```json
{
  "result_dir": "/abs/output/channel/video_id_title",
  "duration": 601.2,
  "source": {"video_id": "...", "source_path": "..."},
  "clips": [{
    "index": 1,
    "file": "/abs/.../clip_01_score-0.87.mp4",
    "preview": "/abs/.../clip_01.jpg",
    "subtitle": "/abs/.../clip_01.ass",
    "start": 12.0,
    "end": 42.0,
    "duration": 30.0,
    "score": 0.87,
    "parts": {"energy": 0.9, "speech": 0.8},
    "text": "текст фрагмента",
    "variant": {
      "style": "karaoke", "zoom": 1.04, "pan_x": 0.02,
      "grade": {"contrast": 1.03, "saturation": 1.04},
      "hook": "Первая фраза", "end_card": "Ещё в профиле",
      "watermark": "@nick"
    },
    "publish": {
      "title": "Первая фраза",
      "description": "Расшифровка…",
      "hashtags": ["#деньги", "#успех"]
    },
    "publish_file": "/abs/.../clip_01_publish.json",
    "file_url": "/files/.../clip_01_score-0.87.mp4",
    "preview_url": "/files/.../clip_01.jpg",
    "subtitle_url": "/files/.../clip_01.ass",
    "publish_url": "/files/.../clip_01_publish.json"
  }],
  "diversity": {"score": 0.72, "max_similarity": 0.28, "ok": true, "pairs": []},
  "folder_url": "/files/.../metadata.json"
}
```

`*_url` равны `null`, если файл лежит вне `output_dir`.
У неудавшегося клипа есть `error` вместо `file`/`preview`/`subtitle`.
`result.folder_url` ведёт на `metadata.json` — это единственный файл, который
удобно отдать как «папку». `diversity` и `publish` также сохраняются в
`diversity.json` и `publish.json` в папке результата.

### `DELETE /api/jobs/{job_id}`

Отмена. Для `queued` задача сразу получает `cancelled`; для `running`
устанавливается флаг, и пайплайн останавливается на следующей проверке.
`404` — задачи нет или она уже завершена.

### `GET /api/jobs/{job_id}/events`

Server-Sent Events с прогрессом. Каждое изменение задачи — событие `data:` с
тем же JSON, что `GET /api/jobs/{id}`. Поток закрывается после
`done/failed/cancelled`; раз в ~10 с отправляется комментарий `: ping`.
Неизвестный id даёт `event: error`.

### `GET /files/{path}`

Отдача файлов из `output_dir` (клипы, превью, ASS, JSON). Защита от path
traversal: итоговый путь после `resolve()` должен оставаться внутри
`output_dir`. `.ass` и `.srt` отдаются как `text/plain; charset=utf-8`, чтобы
браузер не пытался проигрывать их как аудио. Видео отдаётся с поддержкой
Range-запросов (Starlette `FileResponse`).

## Коды ошибок

| Код | Когда |
|---|---|
| `400` | URL — одиночное видео, а не плейлист |
| `404` | неизвестный job или файл |
| `422` | невалидное тело/параметры (pydantic) |
| `429` | очередь заполнена |
| `502` | ошибка yt-dlp/RuTube/сети |

## Ограничения

- Состояние задач хранится в памяти; перезапуск сервера очищает список.
- Один worker: задачи выполняются по одной.
- Максимум 20 задач в очереди веб-приложения.
- Нет CORS: интерфейс и API должны быть на одном origin.
