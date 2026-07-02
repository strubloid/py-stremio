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


class _StallingResponse:
    """Simulates a torrent proxy that returned some bytes and then stalled.

    The body iterator yields a single chunk (so the download makes
    progress past the ``sizing`` phase) and then blocks on
    ``stall_event`` indefinitely.  Used to exercise the
    ``StreamStallError`` translation in ``download_stream_to_file``:
    when ``httpx.ReadTimeout`` fires on the slow iterator, the
    function must convert it into our domain-specific error and clean
    up the partial file.
    """

    def __init__(self, first_chunk: bytes, headers: dict, total_size: int, *, stall_event):
        self.first_chunk = first_chunk
        self.headers = headers
        self.status_code = 200
        self._total_size = total_size
        self._stall_event = stall_event

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, chunk_size=8192):
        yield self.first_chunk
        # Simulate httpx's read-timeout firing on the next iteration.
        # The real httpx transport raises ReadTimeout from a different
        # layer but the exception class is identical and
        # ``download_stream_to_file`` catches it via ``except
        # httpx.ReadTimeout``.
        import httpx as _httpx
        self._stall_event.set()  # release any waiting test thread
        raise _httpx.ReadTimeout("simulated stall")


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


def test_download_stream_to_file_translates_read_timeout_to_stall_error(tmp_path, monkeypatch):
    """When httpx's read timeout fires (the local torrent proxy has no
    peers and the body has stalled), ``download_stream_to_file`` must
    raise ``StreamStallError`` and clean up the partial file instead
    of hanging for the full 5-minute request timeout.

    Regression: 90 Day Fiance S12E08 was stuck on "waiting for
    download" for many minutes because the local torrent proxy found
    the info hash but had no peers, and the download kept blocking on
    ``iter_bytes`` until httpx's full request timeout fired.  The fix
    threads a per-chunk ``read`` timeout through to httpx and
    translates the resulting ``ReadTimeout`` into a domain-specific
    ``StreamStallError`` so the caller can fall through to the next
    stream in the queue.
    """
    import threading
    from py_stremio.components.download import stream_download

    monkeypatch.setattr(stream_download.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 0)
    target = tmp_path / "episode.mkv"
    first_chunk = b"x" * 4096  # Above the 1-byte minimum so we get past the
                              # "sizing" phase and into the steady read loop.

    stall_event = threading.Event()
    captured_timeout = {"value": None}

    def fake_stream(method, url, **kwargs):
        captured_timeout["value"] = kwargs.get("timeout")
        return _StallingResponse(
            first_chunk=first_chunk,
            headers={"content-length": "100000", "content-type": "video/mp4"},
            total_size=100000,
            stall_event=stall_event,
        )

    monkeypatch.setattr(stream_download.httpx, "stream", fake_stream)

    with pytest.raises(stream_download.StreamStallError):
        stream_download.download_stream_to_file(
            "https://example.test/stall",
            str(target),
            stall_timeout=0.5,
        )
    # Unblock the test fixture's stall_event so the request thread can
    # exit cleanly even if anything keeps a reference to the response.
    stall_event.set()
    # The stall timeout must be applied as httpx's read timeout so the
    # body read aborts within the configured window, not the 5-minute
    # request timeout.
    assert captured_timeout["value"] is not None
    assert getattr(captured_timeout["value"], "read", None) == 0.5
    # The partial file must be cleaned up so the user does not see a
    # stale .part leftover after a stall.
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


def test_parse_streams_extracts_imdb_id_and_seeders():
    addon = UrlAddon("https://example.test")
    streams = addon.parse_streams([
        {
            "name": "Direct",
            "url": "https://example.test/video.mkv",
            "title": "One.Piece.S31E01.1080p.mkv",
            "seeders": "42",
            "behaviorHints": {"imdbId": "tt0388629"},
        }
    ])

    assert streams[0].seeders == 42
    assert streams[0].imdb_id == "tt0388629"


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

    def test_keeps_russian_stream(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Русский AC3 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_keeps_russian_rus_marker(self, monkeypatch):
        """'rus.' marker should not discard potentially usable streams."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Rus. AC3 5.1")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

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

    def test_keeps_russian_rudub_marker(self, monkeypatch):
        """'RuDub' marker should not discard potentially usable streams."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Show S01E01 1080p WEBRip RuDub x264")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_keeps_cyrillic_title(self, monkeypatch):
        """Title with Cyrillic text should not be filtered before download attempts."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream(
            "Закусочная Боба / Bob's Burgers / Сезон: 13 / Серии: 1-22 из 22 [1080p] MVO"
        )]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_keeps_rd_cached_cyrillic_pack_when_filename_matches_english_target(self, monkeypatch):
        """Torrentio RD+ season packs can have Cyrillic pack metadata while the
        actual selected file is an English/Latin filename for the target episode.
        Do not discard those playable cached streams before resolution.
        """
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        stream = StreamInfo(
            name="[RD+] Torrentio\n1080p",
            title=(
                "Быть присяжным / Jury Duty / Сезон: 2 / Серии: 1-8 из 8 "
                "[2026 WEB-DL 1080p] MVO"
            ),
            filename="Jury.Duty.S02E05.1080p.WEBDL.RGzsRutracker.mkv",
            url="https://torrentio.strem.fun/resolve/realdebrid/key/hash/null/4/Jury.Duty.S02E05.1080p.WEBDL.RGzsRutracker.mkv",
            info_hash="5df1645cf455834a4c7cc686c3e9d481c755849f",
            file_idx=4,
        )
        result = stream_download.filter_streams_by_language([stream])
        assert result == [stream]

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

    def test_keeps_stream_with_russian_marker_even_if_english_is_detected(self, monkeypatch):
        """Russian markers can still include English audio; do not discard them."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("The Russian S01E01 1080p WEBRip x264 English AAC")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

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

    def test_keeps_russian_even_when_english_is_also_marked(self, monkeypatch):
        """Russian/English dual releases are allowed because they may include English audio."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Bob's Burgers S13E01 1080p English Russian Dual Audio")]
        result = stream_download.filter_streams_by_language(streams)
        assert len(result) == 1

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
            self.make_stream("Bob's Burgers S13E01 1080p French AAC"),
        ]
        result = stream_download.filter_streams_by_language(streams, preferred_languages=["english"])
        assert len(result) == 2
        assert "Russian" in result[0].title
        assert "ENG" in result[1].title

    def test_spanish_preferred_keeps_spanish_and_russian_but_filters_english_only(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["spanish"]
        )
        es = self.make_stream("1080p WEBRip x264 Español AC3 5.1")
        ru = self.make_stream("1080p WEBRip x264 Russian AC3 5.1")
        en = self.make_stream("1080p WEBRip x264 English AC3 5.1")
        result = stream_download.filter_streams_by_language([es, ru, en])
        assert result == [es, ru]


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

    def test_keeps_russian_with_english_default(self, monkeypatch):
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [
            self._make_stream("S01E01 1080p WEBRip Русский AAC"),
            self._make_stream("S01E01 1080p WEBRip English AAC"),
        ]
        result = stream_download.select_quality_streams(streams, "1080p")
        assert len(result) == 2
        assert "русский" in result[0].title.lower()
        assert "english" in result[1].title.lower()

    def test_keeps_russian_by_addon_name_too(self, monkeypatch):
        """Russian detected in stream.name is not a discard reason."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [
            self._make_stream("S01E01 1080p AAC", name="Torrentio Russian"),
            self._make_stream("S01E01 1080p AAC", name="Torrentio English"),
        ]
        result = stream_download.select_quality_streams(streams, "1080p")
        assert len(result) == 2
        assert "Russian" in result[0].name
        assert "English" in result[1].name

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


class TestSearchCrossValidation:
    """Defend against wrong-show downloads.

    Addons occasionally return streams whose episode numbers happen to
    match the request but whose show content is completely unrelated
    (e.g. South Park returned for a One Piece query).  Two signals are
    checked together: IMDB ID cross-validation rejects streams whose
    metadata IMDB ID does not match the target, and show-title
    containment rejects streams whose release name does not contain the
    show title.  Together they ensure that even loose addons can not
    leak wrong content past the filter.
    """

    def _make_stream(
        self,
        title: str,
        name: str = "Torrentio",
        url: str | None = "https://dl.test",
        imdb_id: str | None = None,
    ) -> StreamInfo:
        return StreamInfo(
            name=name,
            title=title,
            url=url,
            imdb_id=imdb_id,
        )

    def test_rejects_stream_with_mismatched_imdb_id(self):
        """Streams whose metadata IMDB ID is set but does not match are rejected."""
        wrong_show = self._make_stream(
            "South.Park.S01E01.1080p.WEB-DL.mkv",
            imdb_id="tt0121955",  # South Park
        )
        result = stream_download._filter_streams_by_target_episode(
            [wrong_show],
            target_season=1,
            target_episode=1,
            title="One Piece",
            target_imdb_id="tt0388629",  # One Piece
        )
        assert result == []

    def test_keeps_stream_with_matching_imdb_id(self):
        """Streams whose metadata IMDB ID matches the target pass."""
        target = self._make_stream(
            "One.Piece.S31E01.1080p.WEB-DL.mkv",
            imdb_id="tt0388629",
        )
        result = stream_download._filter_streams_by_target_episode(
            [target],
            target_season=31,
            target_episode=1,
            title="One Piece",
            target_imdb_id="tt0388629",
        )
        assert result == [target]

    def test_keeps_stream_without_imdb_id_when_target_set(self):
        """Streams without metadata IMDB ID are kept (defensive default).

        Many addons don't include imdb_id on stream objects.  We allow
        those through and rely on title containment + post-download
        validation as the second line of defense.
        """
        stream_without_imdb = self._make_stream(
            "One.Piece.S31E01.1080p.WEB-DL.mkv",
            imdb_id=None,
        )
        result = stream_download._filter_streams_by_target_episode(
            [stream_without_imdb],
            target_season=31,
            target_episode=1,
            title="One Piece",
            target_imdb_id="tt0388629",
        )
        assert result == [stream_without_imdb]

    def test_rejects_wrong_show_with_matching_episode_numbers(self):
        """South Park S31E01 must not pass for a One Piece S31E1 query."""
        south_park = self._make_stream(
            "South.Park.S31E01.1080p.WEB-DL.mkv",
            imdb_id="tt0121955",
        )
        cop_show = self._make_stream(
            "COPS.S31E01.1080p.WEB-DL.mkv",
            imdb_id="tt0080317",
        )
        result = stream_download.select_quality_streams(
            [south_park, cop_show],
            "1080p",
            target_season=31,
            target_episode=1,
            title="One Piece",
            target_imdb_id="tt0388629",
        )
        assert south_park not in result
        assert cop_show not in result

    def test_title_check_normalizes_dots_in_stream_filename(self):
        """Stream titles like 'one.piece.s31e01' must match 'One Piece'."""
        target = self._make_stream(
            "one.piece.s31e01.1080p.web-dl.mkv",
        )
        result = stream_download.select_quality_streams(
            [target],
            "1080p",
            target_season=31,
            target_episode=1,
            title="One Piece",
        )
        assert result == [target]

    def test_title_check_allows_hyphen_variants(self):
        """Show-name matching tolerates dashes in the release name."""
        target = self._make_stream(
            "Bobs-Burgers.S13E13.1080p.WEB-DL.mkv",
        )
        result = stream_download.select_quality_streams(
            [target],
            "1080p",
            target_season=13,
            target_episode=13,
            title="Bobs Burgers",
        )
        assert result == [target]

    def test_title_check_rejects_completely_unrelated_show(self):
        """A stream whose release name does not contain the show title is rejected."""
        wrong = self._make_stream(
            "Random.S01E01.1080p.WEB-DL.mkv",
        )
        result = stream_download.select_quality_streams(
            [wrong],
            "1080p",
            target_season=1,
            target_episode=1,
            title="One Piece",
        )
        assert result == []

    def test_target_mismatch_addon_urls_flags_wrong_show_servers(self):
        wrong = self._make_stream(
            "South.Park.S31E01.1080p.WEB-DL.mkv",
            imdb_id="tt0121955",
        )
        wrong.addon_url = "https://bad-addon.test/manifest.json"
        result = stream_download.target_mismatch_addon_urls(
            [wrong],
            target_season=31,
            target_episode=1,
            title="One Piece",
            target_imdb_id="tt0388629",
        )
        assert result == ["https://bad-addon.test"]

    def test_imdb_id_check_does_not_block_when_no_target_imdb(self):
        """When no target IMDB is known we don't reject streams for IMDB mismatch."""
        stream_with_unrelated_imdb = self._make_stream(
            "One.Piece.S31E01.1080p.WEB-DL.mkv",
            imdb_id="tt0121955",  # some other IMDB
        )
        result = stream_download._filter_streams_by_target_episode(
            [stream_with_unrelated_imdb],
            target_season=31,
            target_episode=1,
            title="One Piece",
            target_imdb_id=None,  # not known
        )
        # Falls back to title check; this stream would still pass it
        assert result == [stream_with_unrelated_imdb]

    def test_select_quality_streams_accepts_target_imdb_id_kwarg(self, monkeypatch):
        """select_quality_streams must accept and forward target_imdb_id."""
        monkeypatch.setattr(
            stream_download.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        target = self._make_stream(
            "Bobs.Burgers.S13E13.1080p.WEB-DL.mkv",
            imdb_id="tt2225764",
        )
        result = stream_download.select_quality_streams(
            [target],
            "1080p",
            target_season=13,
            target_episode=13,
            title="Bobs Burgers",
            target_imdb_id="tt2225764",
        )
        assert result == [target]


class TestSearchAndDownloadIdFallback:
    """Verify the search-and-download uses both IMDB-based and title-based IDs."""

    def test_series_strategies_include_title_fallback(self):
        """When IMDB is available, the title-based strategy must still be tried
        if the IMDB-based strategy doesn't yield a successful download.
        """
        from py_stremio.components.stremio.stremio_client import search_and_download

        attempted_strategies = []

        def fake_resolve(title, imdb_id, season):
            return "tt0388629"  # known One Piece ID

        def fake_search_single_id(*, title, stremio_id, id_type, **kwargs):
            attempted_strategies.append(stremio_id)
            if "tt0388629" in stremio_id:
                return {"success": False, "error": "no streams", "working_urls": []}
            return {
                "success": True,
                "filename": "test.mkv",
                "quality": "1080p",
                "working_urls": [],
                "successful_url": "https://example.test",
            }

        import py_stremio.components.stremio.stremio_client as stremio_client
        monkey = __import__("pytest").MonkeyPatch()
        monkey.setattr(stremio_client, "_resolve_imdb_id", fake_resolve)
        monkey.setattr(stremio_client, "_search_single_id", fake_search_single_id)
        try:
            result = search_and_download(
                title="One Piece",
                season=22,
                episode=120,
            )
            # Both IMDB-based and title-based should have been attempted
            assert len(attempted_strategies) == 2
            assert any("tt0388629" in s for s in attempted_strategies)
            assert any("tt0388629" not in s for s in attempted_strategies)
            assert result.get("success") is True
        finally:
            monkey.undo()

    def test_movie_strategies_include_title_fallback(self):
        """Movies with a known IMDB ID must also fall back to title-based."""
        from py_stremio.components.stremio.stremio_client import search_and_download

        attempted_strategies = []

        def fake_resolve(title, imdb_id, season):
            return "tt2914114"  # some movie ID

        def fake_search_single_id(*, title, stremio_id, id_type, **kwargs):
            attempted_strategies.append((id_type, stremio_id))
            if "tt2914114" in stremio_id:
                return {"success": False, "error": "no streams", "working_urls": []}
            return {
                "success": True,
                "filename": "test.mkv",
                "quality": "720p",
                "working_urls": [],
                "successful_url": "https://example.test",
            }

        import py_stremio.components.stremio.stremio_client as stremio_client
        monkey = __import__("pytest").MonkeyPatch()
        monkey.setattr(stremio_client, "_resolve_imdb_id", fake_resolve)
        monkey.setattr(stremio_client, "_search_single_id", fake_search_single_id)
        try:
            result = search_and_download(
                title="Bob's Burgers Movie",
                content_type="movie",
            )
            assert len(attempted_strategies) == 2
            assert result.get("success") is True
        finally:
            monkey.undo()


class TestStreamInfoCarriesImdbId:
    """Verify the StreamInfo model carries IMDB IDs from addon responses."""

    def test_query_addon_parsing_extracts_imdb_id(self, monkeypatch):
        """query_addon_for_streams must propagate imdb_id from addon responses."""
        from py_stremio.components.addons.addon_search_service import (
            query_addon_for_streams,
        )

        fake_response = {
            "streams": [
                {
                    "name": "Comet 1080p",
                    "url": "https://example.test/video.mkv",
                    "title": "Show.S01E01.1080p.mkv",
                    "imdb_id": "tt1234567",
                },
            ]
        }

        def fake_addon_get(url, timeout=10):
            return fake_response

        monkeypatch.setattr(
            "py_stremio.components.addons.cloudscraper_client.addon_get",
            fake_addon_get,
        )

        streams = query_addon_for_streams(
            "https://example.test",
            "series",
            "tt1234567:1:1",
        )
        assert len(streams) == 1
        assert streams[0].imdb_id == "tt1234567"


class TestInfoHashOnlyStreamFiltering:
    """CIN and similar addons return info-hash streams whose name/title is
    a generic label (``"CIN 4K"``) with no show name or S/E pattern.
    The episode filter must still accept them when the request context
    is present, and reject them when it isn't.
    """

    def test_cin_infohash_stream_passes_for_correct_season_episode(self):
        """CIN-style info-hash stream is kept when the target S/E is supplied."""
        from py_stremio.components.addons.models import StreamInfo

        cin_stream = StreamInfo(
            name="CIN 4K",
            title=None,
            url=None,
            info_hash="598974fc04f0344822b34411a2d9f0a5219d47b1",
            file_idx=0,
            sources=[
                "tracker:udp://tracker.opentrackr.org:1337/announce",
                "dht:598974fc04f0344822b34411a2d9f0a5219d47b1",
            ],
            filename=None,
            addon_name="CIN",
            addon_url="https://cinnn.vercel.app/manifest.json",
        )
        result = stream_download.select_quality_streams(
            [cin_stream],
            "1080p",
            target_season=23,
            target_episode=3,
            title="One Piece",
            target_imdb_id="tt0388629",
        )
        assert result == [cin_stream]

    def test_cin_infohash_stream_rejected_when_no_target_season(self):
        """Without a target S/E the episode check can't validate, and the
        stream has no title signal — it should still pass (per the
        'no-signal' rule) because we have no contradicting evidence.
        """
        from py_stremio.components.addons.models import StreamInfo

        cin_stream = StreamInfo(
            name="CIN 4K",
            title=None,
            url=None,
            info_hash="598974fc04f0344822b34411a2d9f0a5219d47b1",
            file_idx=0,
            sources=["dht:598974fc04f0344822b34411a2d9f0a5219d47b1"],
            filename=None,
            addon_name="CIN",
            addon_url="https://cinnn.vercel.app/manifest.json",
        )
        result = stream_download._filter_streams_by_target_episode(
            [cin_stream],
            title="One Piece",
        )
        assert result == [cin_stream]

    def test_infohash_stream_with_wrong_title_still_rejected(self):
        """A stream with a contradicting show name must still be rejected,
        even when the metadata lacks a clear S/E token.
        """
        from py_stremio.components.addons.models import StreamInfo

        wrong = StreamInfo(
            name="South Park 1080p",
            title="South.Park.S23E03.1080p.WEB-DL.mkv",
            url="https://dl.test/file.mkv",
            addon_name="Bad",
        )
        result = stream_download._filter_streams_by_target_episode(
            [wrong],
            target_season=23,
            target_episode=3,
            title="One Piece",
        )
        assert result == []

    def test_cin_infohash_stream_with_release_group_passes(self):
        """CIN info-hash streams with a release-group token in the title
        (e.g. "MeGusta", "EDITH", "TRB") must still pass the filter.
        Release-group names are torrent technical metadata, not show
        names — they must not be treated as title signals that would
        cause the filter to reject the stream.

        Regression: 90 Day Fiance S12E8 was being rejected because the
        filter counted "MeGusta" as a show-title signal and then failed
        to find "90 Day Fiance" in the torrent description.
        """
        from py_stremio.components.addons.models import StreamInfo

        cin_stream = StreamInfo(
            name="CIN 📺 1080p",
            title="🧲 Torrent\n🎞️ x265\n💾 1.17 GB • 🌱 41\n🛠️ MeGusta",
            url=None,
            info_hash="8b71f3ea0ef0c3da4f7dc3cae58f9955e54c01db",
            file_idx=0,
            sources=["dht:8b71f3ea0ef0c3da4f7dc3cae58f9955e54c01db"],
            filename=None,
            addon_name="CIN",
            addon_url="https://cinnn.vercel.app/manifest.json",
        )
        result = stream_download.select_quality_streams(
            [cin_stream],
            "1080p",
            target_season=12,
            target_episode=8,
            title="90 Day Fiance",
            target_imdb_id="tt3469050",
        )
        assert result == [cin_stream]

    def test_accented_title_matches_unaccented_stream(self):
        """Title check must be diacritics-insensitive.

        Regression: 90 Day Fiance S12E8 was being rejected with
        "No downloadable streams found after filtering" when the
        user's folder title was "90 Day Fiancé" (with the é) because
        torrent release names drop the accent ("90.Day.Fiance"), so
        the substring match failed.  Most scene releases drop accents
        from foreign-language words, so the title comparison must
        normalise both sides.
        """
        from py_stremio.components.addons.models import StreamInfo

        kod_stream = StreamInfo(
            name="KOD | 720P",
            title="90.Day.Fiance.S12E08.720p.HEVC.x265-MeGusta\n👤 69 💾 780.34 MB ⚙️ TorrentGalaxy",
            info_hash="01c477b01ed57fecb3e4673ed3711a1e3053b986",
            file_idx=0,
            filename="90.Day.Fiance.S12E08.720p.HEVC.x265-MeGusta.mkv",
            addon_name="KOD",
            addon_url="https://kod-three.vercel.app/manifest.json",
        )
        for title in (
            "90 Day Fiancé",
            "90 day fiancé",
            "90 Day FIANCÉ",
            "90  Day  Fiancé",  # double spaces
            " 90 Day Fiancé ",  # surrounding whitespace
        ):
            result = stream_download.select_quality_streams(
                [kod_stream],
                "1080p",
                target_season=12,
                target_episode=8,
                title=title,
                target_imdb_id="tt3469050",
            )
            assert result == [kod_stream], f"title={title!r} got {len(result)} streams"

    def test_accented_wrong_show_still_rejected(self):
        """Diacritics-insensitive title matching must not weaken the
        wrong-show defense.  An accented title for a show that is NOT
        present in the stream text must still cause the stream to be
        rejected.
        """
        from py_stremio.components.addons.models import StreamInfo

        op_stream = StreamInfo(
            name="KOD | 720P",
            title="One.Piece.S12E08.720p.HEVC.x265-MeGusta",
            info_hash="abc",
            file_idx=0,
            filename="One.Piece.S12E08.720p.HEVC.x265-MeGusta.mkv",
            addon_name="KOD",
            addon_url="https://kod-three.vercel.app/manifest.json",
        )
        # "90 Day Fiancé" should NOT match "One Piece"
        result = stream_download.select_quality_streams(
            [op_stream],
            "1080p",
            target_season=12,
            target_episode=8,
            title="90 Day Fiancé",
            target_imdb_id="tt3469050",
        )
        assert result == []


# Title filtering is kept in the active pipeline because loose addon searches can
# return streams from unrelated shows with the same S/E number.
