# AutoCut

Локальный конвейер: ссылка (YouTube, RuTube, …) или файл → вертикальные клипы
1080×1920 с субтитрами.

Что делает:

1. скачивает видео по ссылке через yt-dlp (YouTube, RuTube и другие
   поддерживаемые сайты) или берёт локальный файл;
2. находит N самых «живых» фрагментов длиной 20–60 секунд по громкости, речи и
   сменам сцен, выравнивая границы по целым словам;
3. распознаёт речь через faster-whisper и вжигает небольшие субтитры снизу
   (отключается `--no-subtitles` или галочкой в вебе);
4. делает клипы из одной пачки разными: чередует стили субтитров, выбирает
   более сильный хук, добавляет финальную плашку и водяной знак, слегка меняет
   кадрирование и цветокоррекцию; кроп можно сместить влево или вправо;
5. умеет резать точно заданные вручную диапазоны (`--range 12-42`) без
   автоанализа, если нужные моменты уже известны;
6. нормализует громкость до −14 LUFS и проверяет текстовую похожесть клипов;
7. сохраняет клипы, `diversity.json` и черновики подписей `publish.json` по
   папкам на каждое исходное видео.

Вариативность не заменяет содержательную переработку чужого видео и не
гарантирует отсутствие ограничений TikTok. Честный чек-лист —
[docs/uniqueness.md](docs/uniqueness.md).

Один движок используется из CLI, веб-интерфейса и настольного приложения.
Подробности — в [docs/](docs/README.md).

## Установка

Нужны `ffmpeg`/`ffprobe` (8.x) и Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,whisper]"
```

Стек распознавания речи вынесен в extra `whisper` (ctranslate2/onnxruntime/av —
тяжёлые). Без него приложение запускается, но субтитры не сделает.

Первый запуск Whisper скачает модель (~500 МБ для `small`) в
`~/.cache/huggingface/hub`. Если загрузка падает с `CAS Client Error` /
`File reconstruction error` (сбой Xet-бэкенда Hugging Face), повторите с
отключённым Xet:

```bash
HF_HUB_DISABLE_XET=1 .venv/bin/autocut run ./video.mp4
```

Кодек: H.264. Энкодер выбирается автоматически (libx264 → VAAPI → NVENC →
libopenh264 → mpeg4), потому что в Fedora-сборке `ffmpeg-free` нет libx264.
Для лучшего качества поставьте полный ffmpeg из RPM Fusion.

## Настольное приложение

```bash
.venv/bin/autocut app
```

Открывает интерфейс в отдельном окне: pywebview (если установлен extra `app`),
иначе Chrome/Chromium в режиме `--app`, иначе обычный браузер. Порт выбирается
свободный; после закрытия окна сервер останавливается.

```bash
.venv/bin/pip install -e ".[app]"     # нативное окно (нужен GTK/WebKit)
.venv/bin/autocut app --port 8765
.venv/bin/autocut app --browser chrome
```

Подробнее: [docs/desktop.md](docs/desktop.md).

## Веб

```bash
.venv/bin/autocut web
```

Откройте http://127.0.0.1:8000, вставьте ссылку (YouTube, RuTube, …), путь к
локальному файлу или перетащите видео в область загрузки. Файл сохраняется в
`work/uploads/` и подставляется в поле источника. Готовый клип можно
посмотреть прямо в карточке задачи, не скачивая его.

Над формой показывается лента рекомендаций RuTube: превью, канал, длительность
и просмотры. Кнопка «В форму» подставляет ссылку в поле источника. В ленту
попадают только видео длительностью 2–60 минут, на странице — до 12 карточек,
кнопка «Показать ещё» догружает следующую порцию.

Режим «Плейлист» позволяет загрузить список видео, отметить нужные чекбоксами
и запустить нарезку пакетом — каждое видео обрабатывается отдельной задачей.
За один запуск можно выбрать не более 20 видео; очередь веб-приложения вмещает
20 задач. Галочка «Субтитры» отключает распознанные реплики; хук, финальная
плашка и водяной знак настраиваются отдельно в блоке «Уникальность».

HTTP API (jobs, SSE, плейлисты, отдача файлов) описан в
[docs/api.md](docs/api.md).

## CLI

```bash
.venv/bin/autocut run "https://youtu.be/..." --clips 5
.venv/bin/autocut run "https://rutube.ru/video/..." --clips 3
.venv/bin/autocut run ./video.mp4 --clips 3 --format crop
.venv/bin/autocut run ./video.mp4 --format crop --crop-focus left
.venv/bin/autocut run ./video.mp4 --range 12-42 --range 1:05-1:40
.venv/bin/autocut run ./video.mp4 --variation strong --watermark "@nick"
.venv/bin/autocut run ./video.mp4 --style karaoke --caption-mode word
.venv/bin/autocut run ./video.mp4 --no-subtitles
.venv/bin/autocut run "https://rutube.ru/plst/308547/" --playlist-limit 5
.venv/bin/autocut trending --region RU
.venv/bin/autocut web --port 8010
.venv/bin/autocut app
```

Для плейлиста укажите `--playlist-limit N` (от 1 до 50, по умолчанию 1):
CLI возьмёт первые N видео и обработает их последовательно, по одному.
`--json` печатает один JSON-объект (для плейлиста — массив результатов).

Прокси: `--proxy socks5://127.0.0.1:1080` или `AUTOCUT_PROXY`.

## Результат

```
output/<канал>/<video_id>_<название>/
  clips/clip_01_score-0.87.mp4
  clips/clip_01.ass        # субтитры и/или плашки
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

## Настройки

`config.example.yaml` → скопируйте в `config.yaml` (передайте `--config`) или
используйте переменные `AUTOCUT_OUTPUT`, `AUTOCUT_WORKDIR`, `AUTOCUT_MODEL`,
`AUTOCUT_PROXY`, `AUTOCUT_COOKIES`, `AUTOCUT_DEVICE`,
`AUTOCUT_COMPUTE_TYPE`, `AUTOCUT_LANGUAGE`, `AUTOCUT_MAX_HEIGHT`,
`AUTOCUT_ASCII_SLUG`, `AUTOCUT_KEEP_WORK`.

Полная таблица и диапазоны — в
[docs/configuration.md](docs/configuration.md).

## Документация

- [docs/README.md](docs/README.md) — индекс;
- [docs/architecture.md](docs/architecture.md) — модули и поток данных;
- [docs/api.md](docs/api.md) — HTTP API и SSE;
- [docs/configuration.md](docs/configuration.md) — конфиг и параметры;
- [docs/uniqueness.md](docs/uniqueness.md) — вариативность и публикация;
- [docs/desktop.md](docs/desktop.md) — настольное окно;
- [docs/development.md](docs/development.md) — тесты и отладка;
- [docs/troubleshooting.md](docs/troubleshooting.md) — типовые ошибки.

## Тесты

```bash
.venv/bin/python -m pytest
```

Сеть не нужна: yt-dlp и Whisper подменяются, видео генерируется ffmpeg.

## Ограничения

- Скачивание идёт через yt-dlp: кроме YouTube поддерживаются RuTube и другие
  сайты из списка yt-dlp. С этой машины YouTube блокируется, RuTube работает.
- Лента берётся из рекомендаций RuTube, а не из редакционного чарта; порядок
  внутри страницы сортируется по просмотрам. Показываются только ролики
  длительностью 2–60 минут.
- Для плейлистов длительность из flat-списка может быть неизвестна — в списке
  показывается «—», на обработку это не влияет.
- В веб-интерфейсе за пакет можно выбрать не более 20 видео, очередь
  приложения — 20 задач; CLI обрабатывает видео плейлиста последовательно.
- `trending` работает только с лентой популярного YouTube.
- Речь распознаётся локально на CPU; `small` — компромисс скорости и качества.
- Авто-рефрейминг по лицам не реализован: только `blur` и `crop`. Для
  вертикального кропа можно выбрать `--crop-focus center|left|right`.
- Вариативность меняет оформление и кадрирование, но не заменяет
  содержательную переработку чужого видео и не гарантирует отсутствие
  ограничений TikTok.
- Права на исходное видео — ответственность пользователя.
