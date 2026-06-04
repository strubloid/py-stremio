"""Tests for addon URL validation."""

from urllib.parse import unquote

import httpx
import pytest

from py_stremio.components.addon_validator import (
    check_addon_url,
    update_addons_file,
    validate_all_addons,
    validate_and_update,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

MANIFEST_OK = {
    "id": "org.test.addon",
    "name": "TestAddon",
    "resources": ["stream", "catalog"],
    "types": ["series", "movie"],
}

STREAMS_OK = {"streams": [{"name": "Test", "title": "1080p", "url": "https://dl.example/test.mp4"}]}


class FakeResponse:
    """Simulate httpx.Response for manifest / stream requests."""

    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError("oops", request=httpx.Request("GET", "http://test"), response=None)


# ── test_addon_url ───────────────────────────────────────────────────────

def test_addon_url_basic(monkeypatch):
    """URL with a valid manifest should pass."""
    called_urls = []

    def fake_get(url, **kwargs):
        called_urls.append(url)
        if url.endswith("/manifest.json"):
            return FakeResponse(200, MANIFEST_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://addon.example.test/")
    assert result["manifest_ok"] is True
    assert result["streams_found"] == 0
    assert any(u.endswith("/manifest.json") for u in called_urls)


def test_addon_url_stream_ok(monkeypatch):
    """URL without manifest but with working stream endpoint should pass."""
    def fake_get(url, **kwargs):
        if url.endswith("/manifest.json"):
            return FakeResponse(404)
        if url.endswith("/stream/series/tt0944947:1:1.json"):
            return FakeResponse(200, STREAMS_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://streams.example.test/")
    assert result["manifest_ok"] is False
    assert result["streams_found"] == 1


def test_addon_url_with_bad_name(monkeypatch):
    """URL with neither manifest nor streams should fail — error is None because 404 is not an exception."""
    def fake_get(url, **kwargs):
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://dead.example.test/")
    assert result["manifest_ok"] is False
    assert result["streams_found"] == 0


def test_addon_url_connection_error(monkeypatch):
    """Connection error should be caught and reported."""
    def fake_get(url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://unreachable.example.test/")
    assert result["manifest_ok"] is False
    assert result["streams_found"] == 0
    assert result["error"] is not None


def test_addon_url_manifest_json_with_streams_key(monkeypatch):
    """Some addons return a streams list from the manifest endpoint."""
    def fake_get(url, **kwargs):
        if url.endswith("/manifest.json"):
            return FakeResponse(200, {"streams": [{"name": "Direct"}]})
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://direct.example.test/")
    assert result["manifest_ok"] is True


def test_addon_url_already_strips_manifest_json(monkeypatch):
    """URL ending in /manifest.json should be handled correctly."""
    called = []

    def fake_get(url, **kwargs):
        called.append(url)
        return FakeResponse(200, MANIFEST_OK)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://ex.example/base/manifest.json")
    assert result["manifest_ok"] is True
    # Should not double-append manifest.json
    assert "base/manifest.json/manifest.json" not in called[-1]


# ── update_addons_file ───────────────────────────────────────────────────

def test_update_addons_file_comments_failed(tmp_path):
    """Failing URLs get commented out, working ones stay."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# ── Section header ──\n"
        "https://working.example/\n"
        "https://broken.example/\n"
        "\n"
        "https://also-working.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://working.example/", "https://also-working.example/"],
        failed=["https://broken.example/"],
    )

    assert changes == 1
    content = addons.read_text()
    assert "https://working.example/" in content
    assert "https://also-working.example/" in content
    assert "# https://broken.example/" in content  # commented out
    assert "# ── Section header ──" in content  # preserved


def test_update_addons_file_no_changes_if_all_working(tmp_path):
    """When all URLs pass, the file is untouched."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "https://a.example/\n"
        "https://b.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://a.example/", "https://b.example/"],
        failed=[],
    )

    assert changes == 0
    assert addons.read_text() == (
        "https://a.example/\n"
        "https://b.example/\n"
    )


def test_update_addons_file_comment_already_comment_unchanged(tmp_path):
    """Already commented lines are left alone, even if URL is in failed."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# https://already-commented.example/\n"
        "https://active.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://active.example/"],
        failed=["https://already-commented.example/"],
    )

    assert changes == 0
    content = addons.read_text()
    assert "# https://already-commented.example/" in content
    assert "https://active.example/" in content


def test_update_addons_file_handles_blank_lines_and_section_headers(tmp_path):
    """Blank lines and section comments are perfectly preserved."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "\n"
        "# ── TORRENTIO ──\n"
        "https://torrentio.example/\n"
        "\n"
        "# ── ANIME ──\n"
        "https://anime.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://torrentio.example/"],
        failed=["https://anime.example/"],
    )

    assert changes == 1
    content = addons.read_text()
    assert content.splitlines()[0] == ""
    assert "# ── TORRENTIO ──" in content
    assert "https://torrentio.example/" in content
    assert "# https://anime.example/" in content
    assert "# ── ANIME ──" in content


# ── validate_all_addons (integration w/ mocked HTTP) ─────────────────────

def test_validate_all_addons(tmp_path, monkeypatch):
    """End-to-end: one working addon, one failing addon, one commented."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# ── Header ──\n"
        "https://working.example/\n"
        "https://dead.example/\n"
        "# https://already-commented.example/\n"
    )

    call_count = 0

    def fake_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "working" in url:
            return FakeResponse(200, MANIFEST_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    working, failed = validate_all_addons(str(addons), quiet=True)

    assert "https://working.example/" in working
    assert "https://dead.example/" in failed
    # Commented lines are not tested
    assert "https://already-commented.example/" not in working
    assert "https://already-commented.example/" not in failed


def test_validate_and_update_rewrites_file(tmp_path, monkeypatch):
    """Full pipeline: validates, comments dead URLs, leaves working alone."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "https://good.example/\n"
        "https://bad.example/\n"
    )

    def fake_get(url, **kwargs):
        if "good" in url:
            return FakeResponse(200, MANIFEST_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    working_count, failed_count = validate_and_update(str(addons), quiet=True)

    assert working_count == 1
    assert failed_count == 1

    content = addons.read_text()
    assert "https://good.example/" in content
    assert "# https://bad.example/" in content


def test_validate_all_addons_empty_file(tmp_path, monkeypatch):
    """Empty addons file should return empty results."""
    addons = tmp_path / "addons.txt"
    addons.write_text("# only comments\n")

    working, failed = validate_all_addons(str(addons), quiet=True)
    assert working == []
    assert failed == []


def test_validate_all_addons_connection_timeout(tmp_path, monkeypatch):
    """Connection timeout for an addon should count as failed."""
    addons = tmp_path / "addons.txt"
    addons.write_text("https://timeout.example/\n")

    def fake_get(url, **kwargs):
        raise httpx.TimeoutException("Timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    working, failed = validate_all_addons(str(addons), quiet=True)
    assert working == []
    assert len(failed) == 1
