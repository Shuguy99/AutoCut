from pathlib import Path

import pytest

from autocut import downloader


def test_is_url():
    assert downloader.is_url("https://youtube.com/watch?v=x")
    assert not downloader.is_url("/tmp/video.mp4")


def test_is_url_accepts_other_yt_dlp_sites():
    assert downloader.is_url("https://rutube.ru/video/8c31b60faaca8547a2c1ec265fae39e8/")
    assert downloader.is_url("https://vk.com/video-123_456")


def test_prepare_local(sample_video: Path):
    info = downloader.prepare_local(sample_video)
    assert info.source_path == sample_video.resolve()
    assert info.channel == "local"
    assert info.video_id.startswith("local_")
    assert 5.5 <= info.duration <= 6.5


def test_prepare_local_missing(tmp_path: Path):
    with pytest.raises(downloader.DownloadError):
        downloader.prepare_local(tmp_path / "nope.mp4")


class FakeYDL:
    last_opts = None

    def __init__(self, opts):
        FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        if "feed/trending" in url:
            return {
                "entries": [
                    {"id": "trend1", "webpage_url": "https://youtu.be/trend1"}
                ]
            }
        return {
            "id": "abc123", "title": "Title", "channel": "Chan",
            "duration": 10, "webpage_url": url, "view_count": 5,
            "ext": "mp4",
        }


def test_download_uses_proxy(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(downloader, "YoutubeDL", FakeYDL)
    (tmp_path / "source.mp4").write_bytes(b"fake")
    info = downloader.download(
        "https://youtu.be/abc123", tmp_path, proxy="socks5://127.0.0.1:1080"
    )
    assert info.video_id == "abc123"
    assert FakeYDL.last_opts["proxy"] == "socks5://127.0.0.1:1080"
    assert FakeYDL.last_opts["noplaylist"] is True


def test_trending(monkeypatch):
    monkeypatch.setattr(downloader, "YoutubeDL", FakeYDL)
    assert downloader.get_trending("RU") == "https://youtu.be/trend1"


class FakePlaylistYDL:
    last_opts = None

    def __init__(self, opts):
        FakePlaylistYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        return {
            "_type": "playlist",
            "title": "Сборник",
            "channel": "Канал",
            "entries": [
                {
                    "id": "v1", "title": "Первое", "duration": 120,
                    "url": "https://rutube.ru/video/v1/",
                    "thumbnail": "https://img/1.jpg",
                },
                {
                    "id": "v2", "title": "Второе", "duration": None,
                    "url": "https://rutube.ru/video/v2/",
                },
                {"id": "bad", "title": "Без ссылки"},
                None,
            ],
        }


def test_list_playlist(monkeypatch):
    monkeypatch.setattr(downloader, "YoutubeDL", FakePlaylistYDL)
    info = downloader.list_playlist("https://rutube.ru/plst/1/", limit=2)

    assert info.title == "Сборник"
    assert info.truncated is True
    assert [item.video_id for item in info.items] == ["v1", "v2"]
    assert info.items[0].channel == "Канал"
    assert info.items[0].duration == 120.0
    assert info.items[1].duration is None
    assert FakePlaylistYDL.last_opts["noplaylist"] is False
    assert FakePlaylistYDL.last_opts["extract_flat"] == "in_playlist"
    assert FakePlaylistYDL.last_opts["playlistend"] == 2


def test_list_playlist_rejects_single_video(monkeypatch):
    monkeypatch.setattr(downloader, "YoutubeDL", FakeYDL)
    with pytest.raises(downloader.NotAPlaylistError):
        downloader.list_playlist("https://youtu.be/abc123")


def test_list_playlist_error(monkeypatch):
    class BrokenYDL(FakePlaylistYDL):
        def extract_info(self, url, download=False):
            raise RuntimeError("network down")

    monkeypatch.setattr(downloader, "YoutubeDL", BrokenYDL)
    with pytest.raises(downloader.DownloadError):
        downloader.list_playlist("https://rutube.ru/plst/1/")
