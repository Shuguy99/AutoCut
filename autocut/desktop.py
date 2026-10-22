"""Настольная оболочка для веб-интерфейса AutoCut.

Запускает uvicorn в фоновом потоке и открывает интерфейс в отдельном окне:

1. ``pywebview``, если установлен extra ``app``;
2. Chrome/Chromium/Edge в режиме ``--app`` (окно без адресной строки);
3. обычный браузер как запасной вариант.

Сервер всегда слушает только локальный адрес по умолчанию и останавливается
после закрытия окна.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from .config import Config
from .web.app import create_app

CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "brave-browser",
)


def pick_port(host: str = "127.0.0.1") -> int:
    """Возвращает свободный TCP-порт на указанном интерфейсе."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def app_url(host: str, port: int) -> str:
    """URL, по которому браузер открывает интерфейс."""
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    return f"http://{display_host}:{port}/"


def wait_for_server(url: str, timeout: float = 20.0) -> bool:
    """Ждёт, пока ``/api/health`` начнёт отвечать 200."""
    deadline = time.monotonic() + timeout
    health = url.rstrip("/") + "/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.15)
    return False


def find_chrome() -> str | None:
    """Ищет Chromium-браузер, умеющий режим ``--app``."""
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _open_chrome(path: str, url: str) -> bool:
    """Открывает отдельное окно Chrome. Возвращает False, если не вышло."""
    profile = Path(tempfile.mkdtemp(prefix="autocut-chrome-"))
    command = [
        path,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-features=Translate",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        shutil.rmtree(profile, ignore_errors=True)
        return False
    # Быстрый ненулевой выход означает, что окно не открылось.
    time.sleep(0.8)
    if process.poll() not in (None, 0):
        shutil.rmtree(profile, ignore_errors=True)
        return False
    # Если окно закрыли, процесс завершается; профиль можно удалить.
    try:
        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return True


def _open_pywebview(url: str) -> bool:
    """Пробует открыть окно через pywebview (extra ``app``)."""
    try:
        import webview  # type: ignore
    except ImportError:
        return False
    try:
        webview.create_window("AutoCut", url, width=1280, height=900)
        webview.start()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"pywebview недоступен: {exc}", file=sys.stderr)
        return False


def _open_default_browser(url: str) -> None:
    try:
        opened = webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось открыть браузер: {exc}", file=sys.stderr)
        opened = False
    if not opened:
        print(f"Откройте вручную: {url}")


def run_desktop_app(
    config: Config,
    host: str = "127.0.0.1",
    port: int = 0,
    browser: str = "auto",
) -> int:
    """Запускает сервер и окно приложения; возвращает код выхода."""
    import uvicorn

    if port <= 0:
        port = pick_port(host)
    url = app_url(host, port)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config),
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not wait_for_server(url):
        print(
            f"Сервер не запустился за 20 секунд. Проверьте порт {port}.",
            file=sys.stderr,
        )
        server.should_exit = True
        thread.join(timeout=3)
        return 1

    print(f"AutoCut запущен: {url}", file=sys.stderr)
    print("Закройте окно приложения, чтобы остановить сервер.", file=sys.stderr)

    try:
        if browser == "chrome":
            chrome = find_chrome()
            if chrome is None or not _open_chrome(chrome, url):
                _open_default_browser(url)
                _wait_for_interrupt()
        elif browser == "firefox":
            if shutil.which("firefox"):
                try:
                    subprocess.Popen(["firefox", "--new-window", url])
                except OSError as exc:
                    print(f"Не удалось открыть Firefox: {exc}", file=sys.stderr)
                    _open_default_browser(url)
                _wait_for_interrupt()
            else:
                _open_default_browser(url)
                _wait_for_interrupt()
        elif browser == "default":
            _open_default_browser(url)
            _wait_for_interrupt()
        else:  # auto
            if _open_pywebview(url):
                pass
            else:
                chrome = find_chrome()
                if chrome and _open_chrome(chrome, url):
                    pass
                else:
                    _open_default_browser(url)
                    _wait_for_interrupt()
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


def _wait_for_interrupt() -> None:
    """Держит процесс живым, пока пользователь не нажмёт Ctrl+C."""
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        return
