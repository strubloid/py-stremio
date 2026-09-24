"""Tests for the post-download subtitle fallback service."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from py_stremio.components.download import subtitle_service as svc


# ── _language_aliases ────────────────────────────────────────────────────────


def test_language_aliases_normalises_full_name_to_iso_codes():
    """User-facing ``english`` must map to ISO 639-2 ``eng``."""
    assert "eng" in svc._language_aliases("english")
    assert "en" in svc._language_aliases("english")
    assert "english" in svc._language_aliases("english")


def test_language_aliases_passes_short_codes_through():
    """A 3-letter code round-trips unchanged."""
    assert "spa" in svc._language_aliases("spa")


def test_language_aliases_returns_empty_for_empty_input():
    assert svc._language_aliases("") == ()
    assert svc._language_aliases("   ") == ()


# ── detect_subtitle_languages ────────────────────────────────────────────────


def test_detect_subtitle_languages_parses_ffprobe_json(monkeypatch, tmp_path: Path):
    """Embedded ``eng`` and ``jpn`` tags must surface in the returned set."""
    fake_file = tmp_path / "movie.mkv"
    fake_file.write_bytes(b"\x00")

    def fake_run(cmd, **_kwargs):
        payload = {
            "streams": [
                {"tags": {"language": "eng"}},
                {"tags": {"language": "jpn"}},
                {"tags": {}},  # untagged track — must be ignored
            ]
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(svc.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(svc, "_ffprobe_runner", fake_run)

    languages = svc.detect_subtitle_languages(fake_file)
    assert languages == {"eng", "jpn"}


def test_detect_subtitle_languages_handles_invalid_json(monkeypatch, tmp_path: Path):
    fake_file = tmp_path / "movie.mkv"
    fake_file.write_bytes(b"\x00")

    def fake_run(cmd, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="not-json", stderr="")

    monkeypatch.setattr(svc.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(svc, "_ffprobe_runner", fake_run)

    assert svc.detect_subtitle_languages(fake_file) == set()


def test_detect_subtitle_languages_empty_when_ffprobe_missing(monkeypatch, tmp_path: Path):
    fake_file = tmp_path / "movie.mkv"
    fake_file.write_bytes(b"\x00")
    monkeypatch.setattr(svc.shutil, "which", lambda _: None)
    assert svc.detect_subtitle_languages(fake_file) == set()


def test_detect_subtitle_languages_empty_when_ffprobe_errors(monkeypatch, tmp_path: Path):
    fake_file = tmp_path / "movie.mkv"
    fake_file.write_bytes(b"\x00")

    def fake_run(cmd, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="error")

    monkeypatch.setattr(svc.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(svc, "_ffprobe_runner", fake_run)

    assert svc.detect_subtitle_languages(fake_file) == set()


# ── fetch_subtitle_url ──────────────────────────────────────────────────────


def _make_response(payload: Any, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com/subtitles.json")
    return httpx.Response(status_code, json=payload, request=request)


def test_fetch_subtitle_url_returns_first_matching_track(monkeypatch):
    """When the addon lists Spanish first and English second, the
    English track is still returned for an ``english`` request."""
    addon_urls = ("https://addon-a", "https://addon-b")
    seen: list[str] = []

    def fake_get(url, **_kwargs):
        seen.append(url)
        if "addon-a" in url:
            payload = {
                "subtitles": [
                    {"lang": "spa", "url": "https://spa.file.srt"},
                    {"lang": "eng", "url": "https://eng.file.srt"},
                ]
            }
        else:
            payload = {"subtitles": [{"lang": "eng", "url": "https://b.eng.srt"}]}
        return _make_response(payload)

    monkeypatch.setattr(svc, "_http_get", fake_get)

    url, base = svc.fetch_subtitle_url("series", "tt0472954:18:6", ("eng",), addon_urls=addon_urls)
    assert url == "https://eng.file.srt"
    assert base == "https://addon-a"
    # First addon answered; no need to fall through to the second.
    assert len(seen) == 1


def test_fetch_subtitle_url_falls_through_to_next_addon(monkeypatch):
    addon_urls = ("https://addon-a", "https://addon-b")

    def fake_get(url, **_kwargs):
        if "addon-a" in url:
            raise httpx.HTTPError("addon down")
        return _make_response({"subtitles": [{"lang": "eng", "url": "https://b.eng.srt"}]})

    monkeypatch.setattr(svc, "_http_get", fake_get)
    url, base = svc.fetch_subtitle_url("movie", "tt1234567", ("eng",), addon_urls=addon_urls)
    assert url == "https://b.eng.srt"
    assert base == "https://addon-b"


def test_fetch_subtitle_url_returns_none_when_nothing_matches(monkeypatch):
    def fake_get(url, **_kwargs):
        return _make_response({"subtitles": [{"lang": "spa", "url": "x"}]})

    monkeypatch.setattr(svc, "_http_get", fake_get)
    url, base = svc.fetch_subtitle_url("movie", "tt1", ("eng",), addon_urls=("https://a",))
    assert url is None
    assert base == ""


# ── download_subtitle_bytes ─────────────────────────────────────────────────


def test_download_subtitle_bytes_returns_body_on_2xx(monkeypatch):
    payload = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"

    def fake_get(url, **_kwargs):
        return _make_response_text(payload)

    monkeypatch.setattr(svc, "_http_get", fake_get)
    assert svc.download_subtitle_bytes("https://example.com/sub.srt") == payload


def test_download_subtitle_bytes_rejects_truncated_response(monkeypatch):
    """A 6-byte response is clearly an error page, not a real subtitle."""
    def fake_get(url, **_kwargs):
        return _make_response_text(b"<html>")

    monkeypatch.setattr(svc, "_http_get", fake_get)
    assert svc.download_subtitle_bytes("https://example.com/sub.srt") is None


def test_download_subtitle_bytes_returns_none_on_http_error(monkeypatch):
    def fake_get(url, **_kwargs):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(svc, "_http_get", fake_get)
    assert svc.download_subtitle_bytes("https://example.com/sub.srt") is None


def _make_response_text(body: bytes, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com/sub.srt")
    return httpx.Response(status_code, content=body, request=request)


# ── _subtitle_target_path ────────────────────────────────────────────────────


def test_subtitle_target_path_uses_two_letter_iso_prefix(tmp_path: Path):
    video = tmp_path / "ShowName_S01E03.mkv"
    target = svc._subtitle_target_path(video, "english")
    assert target.name == "ShowName_S01E03.en.srt"
    target2 = svc._subtitle_target_path(video, "japanese")
    assert target2.name == "ShowName_S01E03.ja.srt"


# ── ensure_subtitle_for_downloaded_file ─────────────────────────────────────


@pytest.fixture
def fake_file(tmp_path: Path) -> Path:
    f = tmp_path / "Movie.mkv"
    f.write_bytes(b"\x00")
    return f


def test_ensure_subtitle_skips_when_setting_disabled(monkeypatch, fake_file: Path):
    monkeypatch.setattr(svc, "_ffprobe_runner", lambda *_a, **_k: pytest.fail("ffprobe must not run"))
    from py_stremio.components.configs.app_settings import settings

    monkeypatch.setattr(settings, "DOWNLOAD_MISSING_SUBTITUTES", False)
    assert (
        svc.ensure_subtitle_for_downloaded_file(
            fake_file,
            imdb_id="tt1",
            title="Movie",
            season=None,
            episode=None,
            requested_language="english",
        )
        is None
    )


def test_ensure_subtitle_skips_when_language_disabled(monkeypatch, fake_file: Path):
    monkeypatch.setattr(svc, "_ffprobe_runner", lambda *_a, **_k: pytest.fail("ffprobe must not run"))
    assert (
        svc.ensure_subtitle_for_downloaded_file(
            fake_file,
            imdb_id="tt1",
            title="Movie",
            season=None,
            episode=None,
            requested_language="off",
        )
        is None
    )


def test_ensure_subtitle_skips_when_language_already_embedded(monkeypatch, fake_file: Path):
    def fake_run(cmd, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"streams": [{"tags": {"language": "eng"}}]}),
            stderr="",
        )

    monkeypatch.setattr(svc.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(svc, "_ffprobe_runner", fake_run)
    # If the subtitle is already present the addon must never be queried.
    monkeypatch.setattr(svc, "_http_get", lambda *_a, **_k: pytest.fail("addon must not be queried"))

    assert (
        svc.ensure_subtitle_for_downloaded_file(
            fake_file,
            imdb_id="tt1",
            title="Movie",
            season=None,
            episode=None,
            requested_language="english",
        )
        is None
    )


def test_ensure_subtitle_writes_sidecar_srt(monkeypatch, fake_file: Path):
    """Missing English → query addon → write ``<name>.en.srt``."""

    def fake_run(cmd, **_kwargs):
        # ffprobe reports no English track, but a Japanese one (raw release).
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"streams": [{"tags": {"language": "jpn"}}]}),
            stderr="",
        )

    monkeypatch.setattr(svc.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(svc, "_ffprobe_runner", fake_run)

    addon_calls: list[str] = []

    def fake_http_get(url, **_kwargs):
        if "subtitles/series" in url:
            addon_calls.append(url)
            return _make_response(
                {"subtitles": [{"lang": "eng", "url": "https://cdn.example.com/file.srt"}]}
            )
        # The actual subtitle download
        return _make_response_text(b"1\n00:00:01,000 --> 00:00:02,000\nHello world\n")

    monkeypatch.setattr(svc, "_http_get", fake_http_get)

    saved = svc.ensure_subtitle_for_downloaded_file(
        fake_file,
        imdb_id="tt0472954",
        title="Always Sunny",
        season=18,
        episode=6,
        requested_language="english",
    )

    assert saved is not None
    assert saved.name == "Movie.en.srt"
    assert saved.read_bytes().startswith(b"1\n00:00:01")
    assert addon_calls, "expected the subtitle addon to be queried"


def test_ensure_subtitle_handles_missing_imdb_and_title(monkeypatch, fake_file: Path):
    def fake_run(cmd, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(svc.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(svc, "_ffprobe_runner", fake_run)
    # No IMDB id and no title → addon must not be queried.
    monkeypatch.setattr(svc, "_http_get", lambda *_a, **_k: pytest.fail("addon must not be queried"))

    assert (
        svc.ensure_subtitle_for_downloaded_file(
            fake_file,
            imdb_id=None,
            title="",
            season=None,
            episode=None,
            requested_language="english",
        )
        is None
    )


def test_ensure_subtitle_skips_when_file_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(svc, "_ffprobe_runner", lambda *_a, **_k: pytest.fail("ffprobe must not run"))
    missing_path = tmp_path / "does-not-exist.mkv"
    assert (
        svc.ensure_subtitle_for_downloaded_file(
            missing_path,
            imdb_id="tt1",
            title="Movie",
            season=None,
            episode=None,
            requested_language="english",
        )
        is None
    )
