"""Tests for Stremio addon URL ordering."""
from types import SimpleNamespace

import py_stremio.components.addons as addons
from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.stremio import stremio_client
from py_stremio.components.stremio.stremio_client import search_all_addons_for_streams


class FakeAddon:
    def __init__(self, url: str, calls: list[str], has_streams: bool = True):
        self.url = url
        self.name = url
        self.calls = calls
        self.has_streams = has_streams
        self.api_key = None

    def get_url(self, api_key: str | None = None) -> str:
        return self.url

    def get_streams(self, type_: str, id_: str) -> list[SimpleNamespace]:
        self.calls.append(self.url)
        if not self.has_streams:
            return []
        return [SimpleNamespace(name=f"stream:{self.url}", url=f"download:{self.url}")]


class FakeManager:
    def __init__(self, addons: list[FakeAddon]):
        self.addons = addons

    def search_all_addons_and_collect_working(self, type_: str, id_: str):
        all_streams = []
        working_urls = []
        for addon in self.addons:
            streams = addon.get_streams(type_, id_)
            if streams:
                all_streams.extend(streams)
                working_urls.append(addon.get_url())
        return all_streams, working_urls


def test_search_tries_working_urls_before_remaining_addons(monkeypatch):
    calls = []

    def create_addon_manager_from_urls(urls: list[str]) -> FakeManager:
        return FakeManager([FakeAddon(url, calls) for url in urls])

    def create_addon_manager() -> FakeManager:
        return FakeManager([
            FakeAddon("https://saved-addon", calls),
            FakeAddon("https://new-addon", calls),
        ])

    monkeypatch.setattr(addons, "create_addon_manager_from_urls", create_addon_manager_from_urls)
    monkeypatch.setattr(addons, "create_addon_manager", create_addon_manager)

    streams, working_urls = search_all_addons_for_streams(
        "series",
        "tt123:1:1",
        working_addons=["https://saved-addon/manifest.json"],
    )

    assert calls == ["https://saved-addon", "https://new-addon"]
    assert [stream.name for stream in streams] == [
        "stream:https://saved-addon",
        "stream:https://new-addon",
    ]
    assert working_urls == ["https://saved-addon", "https://new-addon"]


def test_search_continues_to_remaining_addons_when_working_url_has_no_streams(monkeypatch):
    calls = []

    def create_addon_manager_from_urls(urls: list[str]) -> FakeManager:
        return FakeManager([
            FakeAddon(url, calls, has_streams=url != "https://dead-addon")
            for url in urls
        ])

    def create_addon_manager() -> FakeManager:
        return FakeManager([
            FakeAddon("https://dead-addon", calls),
            FakeAddon("https://fallback-addon", calls),
        ])

    monkeypatch.setattr(addons, "create_addon_manager_from_urls", create_addon_manager_from_urls)
    monkeypatch.setattr(addons, "create_addon_manager", create_addon_manager)

    streams, working_urls = search_all_addons_for_streams(
        "movie",
        "tt123",
        working_addons=["https://dead-addon"],
    )

    assert calls == ["https://dead-addon", "https://fallback-addon"]
    assert [stream.name for stream in streams] == ["stream:https://fallback-addon"]
    assert working_urls == ["https://fallback-addon"]


def test_search_and_download_returns_successful_stream_addon_url(monkeypatch, tmp_path):
    streams = [
        StreamInfo(
            name="Comet 1080p",
            url="https://dl.test/episode.mp4",
            title="Bob's.Burgers.S13E13",
            addon_name="Comet",
            addon_url="https://comet.feels.legal",
        ),
    ]

    monkeypatch.setattr(stremio_client, "_resolve_imdb_id", lambda title, imdb_id, season: "tt123")
    monkeypatch.setattr(
        stremio_client,
        "search_all_addons_for_streams",
        lambda id_type, stremio_id, working_addons: (streams, ["https://comet.feels.legal", "https://stream-only-addon"]),
    )
    monkeypatch.setattr(stremio_client.settings, "DRY_RUN", False)
    monkeypatch.setattr(stremio_client, "download_stream_to_file", lambda download_url, filename, **kwargs: None)

    result = stremio_client.search_and_download(
        "Bob's Burgers",
        imdb_id="tt123",
        season=13,
        episode=13,
        folder_path=str(tmp_path),
    )

    assert result["success"] is True
    assert result["successful_url"] == "https://comet.feels.legal"
    assert result["working_urls"] == ["https://comet.feels.legal", "https://stream-only-addon"]


def test_search_and_download_marks_all_invalid_video_streams_permanent(monkeypatch, tmp_path):
    streams = [
        StreamInfo(name="Comet 1080p", url="https://dl.test/error1.mp4", title="Bob's.Burgers.S13E13"),
        StreamInfo(name="Torrentio 720p", url="https://dl.test/error2.mp4", title="Bob's.Burgers.S13E13"),
    ]

    monkeypatch.setattr(stremio_client, "_resolve_imdb_id", lambda title, imdb_id, season: "tt123")
    monkeypatch.setattr(
        stremio_client,
        "search_all_addons_for_streams",
        lambda id_type, stremio_id, working_addons: (streams, ["https://comet.feels.legal"]),
    )
    monkeypatch.setattr(stremio_client.settings, "DRY_RUN", False)

    def fake_download(download_url, filename, **kwargs):
        raise stremio_client.InvalidVideoDownloadError("Resolved stream is only 42 bytes")

    monkeypatch.setattr(stremio_client, "download_stream_to_file", fake_download)

    result = stremio_client.search_and_download(
        "Bob's Burgers",
        imdb_id="tt123",
        season=13,
        episode=13,
        folder_path=str(tmp_path),
    )

    assert result["success"] is False
    assert result["permanent_failure"] is True
    assert "only 42 bytes" in result["error"]


def test_search_and_download_marks_filtered_streams_as_no_downloadable_streams(monkeypatch, tmp_path):
    streams = [
        StreamInfo(
            name="[RD] GuIndex WEB-DL",
            url="https://guindex.test/wrong-content",
            title="Na.Mira.2022.1080p.WEB-DL.x264.DUAL",
            filename="Na.Mira.2022.1080p.WEB-DL.x264.DUAL 2.24 GB E05 - starck_filmes",
            addon_name="Guindex",
            addon_url="https://guindex-stremio.vercel.app",
        )
    ]

    monkeypatch.setattr(stremio_client, "_resolve_imdb_id", lambda title, imdb_id, season: "tt22074164")
    monkeypatch.setattr(
        stremio_client,
        "search_all_addons_for_streams",
        lambda id_type, stremio_id, working_addons: (streams, ["https://guindex-stremio.vercel.app"]),
    )
    monkeypatch.setattr(stremio_client.settings, "DRY_RUN", False)

    result = stremio_client.search_and_download(
        "Jury Duty Presents",
        imdb_id="tt22074164",
        season=2,
        episode=5,
        folder_path=str(tmp_path),
    )

    assert result["success"] is False
    assert result["permanent_failure"] is True
    assert result["working_urls"] == []
    assert result["error"] == "No downloadable streams found after filtering"


def test_search_and_download_falls_back_to_remaining_addons_when_cached_server_fails(monkeypatch, tmp_path):
    cached_stream = StreamInfo(
        name="Cached 1080p",
        url="https://cached.test/error.mp4",
        title="Bob's.Burgers.S13E13",
        addon_name="CachedAddon",
        addon_url="https://cached-addon",
    )
    fallback_stream = StreamInfo(
        name="Fallback 1080p",
        url="https://fallback.test/episode.mp4",
        title="Bob's.Burgers.S13E13",
        addon_name="FallbackAddon",
        addon_url="https://fallback-addon",
    )
    search_calls = []
    download_calls = []

    monkeypatch.setattr(stremio_client, "_resolve_imdb_id", lambda title, imdb_id, season: "tt123")
    monkeypatch.setattr(
        stremio_client,
        "search_working_addons_for_streams",
        lambda id_type, stremio_id, working_addons: (
            search_calls.append(("cached", working_addons)) or ([cached_stream], ["https://cached-addon"])
        ),
    )
    monkeypatch.setattr(
        stremio_client,
        "search_remaining_addons_for_streams",
        lambda id_type, stremio_id, excluded_addons: (
            search_calls.append(("remaining", excluded_addons)) or ([fallback_stream], ["https://fallback-addon"])
        ),
    )
    monkeypatch.setattr(stremio_client.settings, "DRY_RUN", False)

    def fake_download(download_url, filename, **kwargs):
        download_calls.append(download_url)
        if "cached" in download_url:
            raise RuntimeError("cached server failed")

    monkeypatch.setattr(stremio_client, "download_stream_to_file", fake_download)

    result = stremio_client.search_and_download(
        "Bob's Burgers",
        imdb_id="tt123",
        season=13,
        episode=13,
        folder_path=str(tmp_path),
        working_addons=["https://cached-addon"],
    )

    assert result["success"] is True
    assert result["successful_url"] == "https://fallback-addon"
    assert result["working_urls"] == ["https://cached-addon", "https://fallback-addon"]
    assert search_calls == [
        ("cached", ["https://cached-addon"]),
        ("remaining", ["https://cached-addon"]),
    ]
    assert download_calls == ["https://cached.test/error.mp4", "https://fallback.test/episode.mp4"]


def test_retry_with_real_debrid_without_info_hash_returns_none(monkeypatch, tmp_path):
    calls = []

    def fake_resolve_torrent_with_debrid(info_hash, file_idx):
        calls.append((info_hash, file_idx))
        return "https://rd.test/video.mkv"

    monkeypatch.setattr(
        stremio_client,
        "resolve_torrent_with_debrid",
        fake_resolve_torrent_with_debrid,
    )

    result = stremio_client._retry_with_real_debrid(
        StreamInfo(name="No hash stream", url="https://dl.test/file.mkv"),
        str(tmp_path / "file.mkv"),
        [],
    )

    assert result is None
    assert calls == []
