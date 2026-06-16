"""Tests for stream download resume behavior and language filtering."""

import httpx
import pytest

from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.addons.base import UrlAddon
from py_stremio.components.download import stream_download


class FakeResponse:
    status_code = 206
    headers = {"content-length": "6", "content-range": "bytes 4-9/10"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, chunk_size=8192):
        yield b"ef"
        yield b"ghij"


class FakeDownloadResponse:
    def __init__(self, body: bytes, headers: dict | None = None, status_code: int = 200):
        self.body = body
        self.headers = headers or {"content-length": str(len(body))}
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, chunk_size=8192):
        yield self.body


def test_download_stream_to_file_resumes_existing_partial_part_file(tmp_path, monkeypatch):
    # Disable the minimum file size check for this test (uses small test data)
    monkeypatch.setattr(stream_download.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 0)
    target = tmp_path / "episode.mkv"
    partial = tmp_path / "episode.mkv.part"
    partial.write_bytes(b"abcd")
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        captured["follow_redirects"] = kwargs.get("follow_redirects")
        return FakeResponse()

    monkeypatch.setattr(stream_download.httpx, "stream", fake_stream)

    progress_events = []
    stream_download.download_stream_to_file(
        "https://example.test/video.mkv",
        str(target),
        progress_callback=lambda downloaded, total: progress_events.append((downloaded, total)),
    )

    assert captured["headers"]["Range"] == "bytes=4-"
    assert captured["follow_redirects"] is True
    assert target.read_bytes() == b"abcdefghij"
    assert not partial.exists()
    assert progress_events[-1] == (10, 10)


def test_download_stream_to_file_rejects_tiny_response_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(stream_download.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 100)
    target = tmp_path / "episode.mkv"

    def fake_stream(method, url, **kwargs):
        return FakeDownloadResponse(
            b"RealDebrid says this video is unavailable",
            headers={"content-length": "42", "content-type": "video/mp4"},
        )

    monkeypatch.setattr(stream_download.httpx, "stream", fake_stream)

    with pytest.raises(stream_download.InvalidVideoDownloadError, match="only 42 bytes"):
        stream_download.download_stream_to_file("https://example.test/error.mp4", str(target))

    assert not target.exists()
    assert not (tmp_path / "episode.mkv.part").exists()


def test_download_stream_to_file_rejects_text_error_response(tmp_path, monkeypatch):
    monkeypatch.setattr(stream_download.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 100)
    target = tmp_path / "episode.mkv"

    def fake_stream(method, url, **kwargs):
        return FakeDownloadResponse(
            b"{\"error\":\"not available\"}",
            headers={"content-length": "25", "content-type": "application/json"},
        )

    monkeypatch.setattr(stream_download.httpx, "stream", fake_stream)

    with pytest.raises(stream_download.InvalidVideoDownloadError, match="application/json"):
        stream_download.download_stream_to_file("https://example.test/error", str(target))

    assert not target.exists()
    assert not (tmp_path / "episode.mkv.part").exists()


def test_parse_streams_extracts_hash_and_file_idx_from_torrentio_rd_proxy_url():
    addon = UrlAddon("https://torrentio.strem.fun")
    streams = addon.parse_streams([
        {
            "name": "[RD+] Torrentio\n1080p",
            "title": "Show.S01E01.1080p.mkv",
            "url": "https://torrentio.strem.fun/resolve/realdebrid/SECRET/"
                   "106e91b93321f9c8aeeeb32ea6c92317327e7b3b/null/7/Show.mkv",
            "behaviorHints": {
                "bingeGroup": "torrentio|106e91b93321f9c8aeeeb32ea6c92317327e7b3b",
                "filename": "Show.S01E01.1080p.mkv",
            },
        }
    ])

    assert streams[0].info_hash == "106e91b93321f9c8aeeeb32ea6c92317327e7b3b"
    assert streams[0].file_idx == 7


def test_parse_streams_prefers_explicit_info_hash_and_file_idx():
    addon = UrlAddon("https://example.test")
    streams = addon.parse_streams([
        {
            "name": "Direct",
            "url": "https://example.test/video.mkv",
            "infoHash": "abc123",
            "fileIdx": "4",
        }
    ])

    assert streams[0].info_hash == "abc123"
    assert streams[0].file_idx == 4


def test_parse_streams_preserves_tracker_sources_for_local_torrent_proxy():
    addon = UrlAddon("https://torrentsdb.com")
    streams = addon.parse_streams([
        {
            "name": "TorrentsDB\n1080p",
            "infoHash": "a480e87c450a7f581e771a00f28ea95f8db25e0a",
            "fileIdx": 0,
            "sources": [
                "tracker:udp://tracker.opentrackr.org:1337/announce",
                "tracker:udp://open.stealth.si:80/announce",
                "dht:opentrackr.org",
            ],
        }
    ])

    assert streams[0].sources == [
        "tracker:udp://tracker.opentrackr.org:1337/announce",
        "tracker:udp://open.stealth.si:80/announce",
        "dht:opentrackr.org",
    ]


def test_build_torrent_proxy_url_includes_tracker_sources():
    stream = StreamInfo(
        name="TorrentsDB\n1080p",
        info_hash="a480e87c450a7f581e771a00f28ea95f8db25e0a",
        file_idx=0,
        sources=[
            "tracker:udp://tracker.opentrackr.org:1337/announce",
            "tracker:udp://open.stealth.si:80/announce",
            "dht:opentrackr.org",
        ],
    )

    url = stream_download.build_torrent_proxy_url("http://127.0.0.1:11470/", stream)

    assert url.startswith("http://127.0.0.1:11470/a480e87c450a7f581e771a00f28ea95f8db25e0a/0?")
    assert "tr=tracker%3Audp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce" in url
    assert "tr=tracker%3Audp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce" in url
    assert "tr=dht%3Aopentrackr.org" in url


def test_resolve_real_debrid_proxy_url_timeout_logs_and_falls_back(monkeypatch):
    """RD proxy timeouts should not crash because of stale refactor imports."""
    logged = []

    def fake_get(*args, **kwargs):
        request = httpx.Request("GET", args[0])
        raise httpx.ReadTimeout("The read operation timed out", request=request)

    monkeypatch.setattr(stream_download.httpx, "get", fake_get)
    monkeypatch.setattr(
        "py_stremio.components.errors.error_logger.log_error",
        lambda context, exception, details="": logged.append((context, type(exception), details)),
    )

    url = "https://torrentio.strem.fun/resolve/realdebrid/SECRET/hash/null/0/file.mkv"

    assert stream_download.resolve_real_debrid_proxy_url(url) is None
    assert logged == [("resolve_rd_proxy", httpx.ReadTimeout, url)]


class FakeStreamInfo:
    """Minimal StreamInfo-like object for testing title matching."""
    def __init__(self, title="", name="", filename=""):
        self.title = title
        self.name = name
        self.filename = filename


# Tests for _matches_show_title removed:
# The helper function was removed along with _filter_streams_by_title because
# title matching caused false rejections. The IMDb ID is the authoritative identifier.


class TestDetectLanguages:
    """Unit tests for the _detect_languages helper."""

    def test_detects_english(self):
        found = stream_download._detect_languages("1080p WEBRip x264 English AC3")
        assert "english" in found

    def test_detects_russian_cyrillic(self):
        found = stream_download._detect_languages("1080p WEBRip x264 Русский AC3")
        assert "russian" in found

    def test_detects_russian_latin(self):
        found = stream_download._detect_languages("S01E01 1080p Russian AAC")
        assert "russian" in found

    def test_detects_multi(self):
        found = stream_download._detect_languages("S01E01 1080p Multi Audio AAC")
        assert "multi" in found

    def test_detects_no_language(self):
        found = stream_download._detect_languages("S01E01 1080p WEBRip x264 AAC")
        assert found == set()

    def test_detects_multiple_languages(self):
        found = stream_download._detect_languages("English + Spanish Dual Audio")
        assert "english" in found
        assert "spanish" in found

    def test_detects_russian_cyrillic_text(self):
        """Title in Cyrillic should be detected as Russian."""
        found = stream_download._detect_languages(
            "Закусочная Боба / Bob's Burgers / Сезон: 13 / Серии: 1-22 из 22"
        )
        assert "russian" in found

    def test_detects_cyrillic_with_english_text(self):
        """Mixed Cyrillic+English should still detect Russian."""
        found = stream_download._detect_languages(
            "русская озвучка Bob's Burgers S13E01"
        )
        assert "russian" in found

    def test_no_false_positive_on_pure_latin(self):
        """Pure Latin text should not falsely detect Russian."""
        found = stream_download._detect_languages(
            "Bob's Burgers S13E01 1080p WEB-DL x264 English"
        )
        assert "russian" not in found


class TestFilterStreamsByLanguage:
    """Integration tests for filter_streams_by_language."""

    def make_stream(self, title: str, name: str = "Torrentio RD") -> StreamInfo:
        return StreamInfo(name=name, title=title, url="https://example.test/video.mkv")

    def test_keeps_english_stream(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 English AC3 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_filters_russian_stream(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Русский AC3 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_russian_rus_marker(self, monkeypatch):
        """'rus.' marker should be caught."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Rus. AC3 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_russian_ru_bracket_passes_without_aggressive_ru_pattern(self, monkeypatch):
        """'[RU]' is no longer a reliable Russian marker — too many false positives
        from release group names and abbreviations. Only 'rus', 'russian', 'rudub',
        and cyrillic are used now."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Show S01E01 1080p WEBRip [RU] AC3")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_filters_russian_rudub_marker(self, monkeypatch):
        """'RuDub' marker should be caught."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Show S01E01 1080p WEBRip RuDub x264")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_cyrillic_title(self, monkeypatch):
        """Title with Cyrillic text should be filtered."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream(
            "Закусочная Боба / Bob's Burgers / Сезон: 13 / Серии: 1-22 из 22 [1080p] MVO"
        )]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_passes_english_stream_with_cyrillic_in_name(self, monkeypatch):
        """Addon name with non-language cyrillic shouldn't break English detection."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [StreamInfo(
            name="Torrentio",
            title="1080p WEBRip x264 English AC3 5.1",
            url="https://example.test/video.mkv",
        )]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_keeps_multi_language_stream(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip Multi Audio AC3 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_keeps_stream_with_no_language_info(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 AAC 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_filters_stream_with_russian_marker_even_if_english_is_detected(self, monkeypatch):
        """Strict English configs remove anything marked Russian."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("The Russian S01E01 1080p WEBRip x264 English AAC")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_skip_filtering_when_any_is_preferred(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["any"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Русский AC3 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_dual_language_including_english_passes(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("English + French Dual Audio")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_filters_russian_even_when_english_is_also_marked(self, monkeypatch):
        """English-preferred configs must not accept Russian/English dual releases."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Bob's Burgers S13E01 1080p English Russian Dual Audio")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_russian_even_when_multi_audio_is_marked(self, monkeypatch):
        """Multi-audio releases marked only with '[RU]' are no longer blocked — the
        'ru' standalone pattern was too aggressive (release groups, abbreviations)."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Bob's Burgers S13E01 1080p Multi Audio [RU]")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1  # [RU] alone no longer triggers Russian filter

    def test_eng_marker_counts_as_english_preference(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Bob's Burgers S13E01 1080p WEB-DL ENG AAC")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_can_use_download_config_languages_instead_of_global_settings(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["any"]
        )
        streams = [
            self.make_stream("Bob's Burgers S13E01 1080p Russian AAC"),
            self.make_stream("Bob's Burgers S13E01 1080p ENG AAC"),
        ]
        result = stream_download.filter_streams_by_language(streams, preferred_languages=["english"])
        assert len(result) == 1
        assert "ENG" in result[0].title

    def test_spanish_preferred_keeps_spanish_filters_russian(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["spanish"]
        )
        es = self.make_stream("1080p WEBRip x264 Español AC3 5.1")
        ru = self.make_stream("1080p WEBRip x264 Russian AC3 5.1")
        en = self.make_stream("1080p WEBRip x264 English AC3 5.1")
        result = stream_download.filter_streams_by_language([es, ru, en])
        assert len(result) == 1  # only spanish matches; russian and english filtered
        assert result[0] == es


class TestSelectQualityStreamsWithLanguage:
    """Verify select_quality_streams applies language/media filtering."""

    def _make_stream(
        self,
        title: str,
        name: str = "Torrentio",
        url: str | None = "https://dl.test",
        info_hash: str | None = None,
        file_idx: int | None = None,
        filename: str | None = None,
    ) -> StreamInfo:
        return StreamInfo(
            name=name,
            title=title,
            url=url,
            info_hash=info_hash,
            file_idx=file_idx,
            filename=filename,
        )

    def test_filters_russian_with_english_default(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [
            self._make_stream("S01E01 1080p WEBRip Русский AAC"),
            self._make_stream("S01E01 1080p WEBRip English AAC"),
        ]
        result = stream_download.select_quality_streams(streams, "1080p")
        assert len(result) == 1
        assert "english" in result[0].title.lower()

    def test_filters_by_addon_name_too(self, monkeypatch):
        """Language detected in stream.name is also filtered."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [
            self._make_stream("S01E01 1080p AAC", name="Torrentio Russian"),
            self._make_stream("S01E01 1080p AAC", name="Torrentio English"),
        ]
        result = stream_download.select_quality_streams(streams, "1080p")
        assert len(result) == 1
        assert "English" in result[0].name

    def test_target_episode_filter_removes_unrelated_bobs_burgers_movie(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        movie = self._make_stream(
            "The.Bobs.Burgers.Movie.2022.2160p.UHD.BluRay.x265"
        )
        episode = self._make_stream(
            "Bobs Burgers S13 1080p WEB-DL Bobs.Burgers.S13E13.mkv",
            url=None,
            info_hash="abc123",
            file_idx=12,
        )
        result = stream_download.select_quality_streams(
            [movie, episode],
            "1080p",
            target_season=13,
            target_episode=13,
        )
        assert result == [episode]

    def test_target_episode_filter_uses_behavior_hint_filename(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        episode = self._make_stream(
            "[RD] Torz 1080p",
            filename="Bobs.Burgers.S13E20.1080p.WEB-DL.mkv",
        )
        result = stream_download.select_quality_streams(
            [episode],
            "1080p",
            target_season=13,
            target_episode=20,
        )
        assert result == [episode]

    def test_target_episode_filter_removes_advisory_addon_messages(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        advisory = self._make_stream(
            "ℹ Kindly configure this addon to access streams.",
            url="https://addon.example/playback/not-a-video",
        )
        episode = self._make_stream(
            "Bobs.Burgers.S13E13.1080p.WEB-DL.mkv",
            url=None,
            info_hash="def456",
            file_idx=12,
        )
        result = stream_download.select_quality_streams(
            [advisory, episode],
            "1080p",
            target_season=13,
            target_episode=13,
        )
        assert result == [episode]
    def test_target_episode_filter_rejects_wrong_movie_with_generated_episode_suffix(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["any"]
        )
        wrong_movie = self._make_stream(
            "Na.Mira.2022.1080p.WEB-DL.x264.DUAL",
            name="[RD] GuIndex WEB-DL",
            filename="Na.Mira.2022.1080p.WEB-DL.x264.DUAL 2.24 GB E05 - starck_filmes",
        )

        result = stream_download.select_quality_streams(
            [wrong_movie],
            "1080p",
            target_season=2,
            target_episode=5,
            title="Jury Duty Presents",
        )

        assert result == []


# TestFilterStreamsByTitle removed:
# The _filter_streams_by_title function was removed from the pipeline because
# it caused false rejections when torrent release names didn't match the official
# show title. The IMDb ID + episode filter are sufficient to ensure correct content.
