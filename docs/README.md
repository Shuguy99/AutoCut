# Документация AutoCut

AutoCut — локальный конвейер «видео → вертикальные клипы 1080×1920 с субтитрами».
Один движок используется из CLI, веб-интерфейса и настольного окна.

| Документ | Что внутри |
|---|---|
| [architecture.md](architecture.md) | модули, поток данных, решения и ограничения |
| [api.md](api.md) | HTTP API, SSE, коды ошибок |
| [configuration.md](configuration.md) | `config.yaml`, переменные окружения, параметры задачи |
| [uniqueness.md](uniqueness.md) | вариативность клипов, публикация в TikTok и честный чек-лист |
| [desktop.md](desktop.md) | запуск как приложения, Chrome `--app`, pywebview |
| [development.md](development.md) | установка, тесты, стиль, отладка |
| [troubleshooting.md](troubleshooting.md) | типовые ошибки ffmpeg, Whisper, сети |

Быстрый старт:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,whisper]"
.venv/bin/autocut app          # настольное окно
# или
.venv/bin/autocut web          # http://127.0.0.1:8000
# или
.venv/bin/autocut run ./video.mp4 --clips 3
```

Полное описание возможностей и ограничений — в корневом [README.md](../README.md).
