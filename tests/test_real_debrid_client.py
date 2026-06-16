"""Tests for RealDebrid torrent resolution helpers."""

from types import SimpleNamespace

from py_stremio.components.debrid import real_debrid_client
from py_stremio.components.debrid.real_debrid_client import _real_debrid_file_selection


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_real_debrid_file_selection_maps_zero_based_stremio_idx_to_rd_file_id():
    files = [
        {"id": 1, "path": "/episode5.mkv"},
        {"id": 2, "path": "/episode6.mkv"},
        {"id": 3, "path": "/episode7.mkv"},
    ]

    assert _real_debrid_file_selection(files, 0) == "1"
    assert _real_debrid_file_selection(files, 2) == "3"


def test_real_debrid_file_selection_selects_all_when_no_file_idx():
    assert _real_debrid_file_selection([{"id": 1}], None) == "all"


def test_real_debrid_file_selection_falls_back_to_all_for_missing_file_list():
    assert _real_debrid_file_selection([], 0) == "all"


def test_resolve_torrent_reports_select_files_failure_without_crashing(monkeypatch):
    reported = []
    posts = []

    monkeypatch.setattr(real_debrid_client.settings, "REAL_DEBRID_API_KEY", "test-key")
    monkeypatch.setattr(real_debrid_client.time, "sleep", lambda _seconds: None)

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("data")))
        if url.endswith("/torrents/addMagnet"):
            return FakeResponse(201, {"id": "torrent-id"})
        if "/torrents/selectFiles/" in url:
            return FakeResponse(400, text='{"error":"bad_files_selection"}')
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        if url.endswith("/torrents/info/torrent-id"):
            return FakeResponse(200, {"files": [{"id": 1, "path": "/episode.mkv"}]})
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(real_debrid_client.httpx, "post", fake_post)
    monkeypatch.setattr(real_debrid_client.httpx, "get", fake_get)
    monkeypatch.setattr(
        "py_stremio.components.errors.report_error",
        lambda context, exception=None, url=None: reported.append((context, str(exception), url)),
    )

    result = real_debrid_client.resolve_torrent_with_debrid("abc123", file_idx=0)

    assert result is None
    assert posts[1][1] == {"files": "1"}
    assert reported == [
        (
            "realdebrid_select(abc123)",
            '{"error":"bad_files_selection"}',
            "https://api.real-debrid.com/rest/1.0/torrents/selectFiles/torrent-id",
        )
    ]
