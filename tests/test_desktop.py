import socket

from autocut import desktop
from autocut.config import Config
from autocut.desktop import app_url, pick_port


def test_pick_port_returns_free_port():
    port = pick_port("127.0.0.1")
    assert 0 < port < 65536
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


def test_app_url_maps_wildcard_host_to_loopback():
    assert app_url("127.0.0.1", 8765) == "http://127.0.0.1:8765/"
    assert app_url("0.0.0.0", 8000) == "http://127.0.0.1:8000/"
    assert app_url("::1", 8000) == "http://[::1]:8000/"


def test_desktop_app_starts_and_stops_server(config: Config, monkeypatch):
    opened = {}

    def fake_open(url):
        opened["url"] = url
        return True

    monkeypatch.setattr(desktop, "_open_pywebview", fake_open)
    code = desktop.run_desktop_app(config, port=0, browser="auto")
    assert code == 0
    assert opened["url"].startswith("http://127.0.0.1:")
