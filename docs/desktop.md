# Настольное приложение

Веб-интерфейс можно открыть не во вкладке браузера, а в отдельном окне без
адресной строки.

## Быстрый запуск

```bash
.venv/bin/autocut app
# или, если установлен entry point:
.venv/bin/autocut-app
```

Команда:

1. поднимает uvicorn на `127.0.0.1` и свободном порту (по умолчанию `--port 0`);
2. ждёт ответа `/api/health`;
3. открывает окно одним из способов ниже;
4. останавливает сервер после закрытия окна.

Порт можно зафиксировать:

```bash
autocut app --port 8765
```

## Способы открытия

Порядок в режиме `auto`:

1. **pywebview** — нативное окно, если установлен extra `app`:

   ```bash
   .venv/bin/pip install -e ".[app]"
   ```

   На Linux pywebview требует GTK/WebKit (пакеты `python3-gobject`,
   `webkit2gtk`). Если их нет, способ пропускается.

2. **Chrome/Chromium/Edge/Brave** в режиме `--app`. Открывается отдельное окно
   без вкладок и адресной строки, с временным профилем
   `autocut-chrome-*`, который удаляется после закрытия. Поддерживаются
   `google-chrome`, `google-chrome-stable`, `chromium`, `chromium-browser`,
   `microsoft-edge`, `brave-browser`.

3. **Браузер по умолчанию** (`webbrowser.open`). В этом режиме сервер живёт до
   `Ctrl+C`, потому что закрытие вкладки не отслеживается.

Явный выбор:

```bash
autocut app --browser chrome
autocut app --browser firefox     # отдельное окно Firefox, ждём Ctrl+C
autocut app --browser default
```

## Отличия от `autocut web`

| | `autocut web` | `autocut app` |
|---|---|---|
| окно | вкладка браузера | отдельное окно приложения |
| порт | 8000 по умолчанию | свободный (0) |
| остановка | `Ctrl+C` | закрытие окна или `Ctrl+C` |
| зависимости | базовые | опционально pywebview; иначе Chrome/браузер |

## Ярлык в меню приложений

Можно создать `.desktop`-файл (замените путь на свой):

```ini
[Desktop Entry]
Type=Application
Name=AutoCut
Comment=Клипы из видео
Exec=/home/user/AutoCut/.venv/bin/autocut app
Icon=video-x-generic
Terminal=false
Categories=AudioVideo;Video;
```

Сохраните как `~/.local/share/applications/autocut.desktop` и обновите кэш:

```bash
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

## Ограничения

- Окно показывает локальный веб-интерфейс; это не нативная переработка UI.
- На headless-сервере без `DISPLAY` откроется только браузер по умолчанию
  (или ничего); сервер при этом продолжит работать до `Ctrl+C`.
- Приложение не устанавливается в систему само: это команда в venv.
