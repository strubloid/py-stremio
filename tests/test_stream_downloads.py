"""Tests for stream download resume behavior and language filtering."""

import pytest

from py_stremio.components.addons.models import StreamInfo
from py_stremio.components import stream_downloads


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


def test_download_stream_to_file_resumes_existing_partial_part_file(tmp_path, monkeypatch):
    # Disable the minimum file size check for this test (uses small test data)
    monkeypatch.setattr(stream_downloads.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 0)
    target = tmp_path / "episode.mkv"
    partial = tmp_path / "episode.mkv.part"
    partial.write_bytes(b"abcd")
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(stream_downloads.httpx, "stream", fake_stream)

    progress_events = []
    stream_downloads.download_stream_to_file(
        "https://example.test/video.mkv",
        str(target),
        progress_callback=lambda downloaded, total: progress_events.append((downloaded, total)),
    )

    assert captured["headers"]["Range"] == "bytes=4-"
    assert target.read_bytes() == b"abcdefghij"
    assert not partial.exists()
    assert progress_events[-1] == (10, 10)


class TestDetectLanguages:
    """Unit tests for the _detect_languages helper."""

    def test_detects_english(self):
        found = stream_downloads._detect_languages("1080p WEBRip x264 English AC3")
        assert "english" in found

    def test_detects_russian_cyrillic(self):
        found = stream_downloads._detect_languages("1080p WEBRip x264 Русский AC3")
        assert "russian" in found

    def test_detects_russian_latin(self):
        found = stream_downloads._detect_languages("S01E01 1080p Russian AAC")
        assert "russian" in found

    def test_detects_multi(self):
        found = stream_downloads._detect_languages("S01E01 1080p Multi Audio AAC")
        assert "multi" in found

    def test_detects_no_language(self):
        found = stream_downloads._detect_languages("S01E01 1080p WEBRip x264 AAC")
        assert found == set()

    def test_detects_multiple_languages(self):
        found = stream_downloads._detect_languages("English + Spanish Dual Audio")
        assert "english" in found
        assert "spanish" in found

    def test_detects_russian_cyrillic_text(self):
        """Title in Cyrillic should be detected as Russian."""
        found = stream_downloads._detect_languages(
            "Закусочная Боба / Bob's Burgers / Сезон: 13 / Серии: 1-22 из 22"
        )
        assert "russian" in found

    def test_detects_cyrillic_with_english_text(self):
        """Mixed Cyrillic+English should still detect Russian."""
        found = stream_downloads._detect_languages(
            "русская озвучка Bob's Burgers S13E01"
        )
        assert "russian" in found

    def test_no_false_positive_on_pure_latin(self):
        """Pure Latin text should not falsely detect Russian."""
        found = stream_downloads._detect_languages(
            "Bob's Burgers S13E01 1080p WEB-DL x264 English"
        )
        assert "russian" not in found


class TestFilterStreamsByLanguage:
    """Integration tests for filter_streams_by_language."""

    def make_stream(self, title: str, name: str = "Torrentio RD") -> StreamInfo:
        return StreamInfo(name=name, title=title, url="https://example.test/video.mkv")

    def test_keeps_english_stream(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 English AC3 5.1")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_filters_russian_stream(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Русский AC3 5.1")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_russian_rus_marker(self, monkeypatch):
        """'rus.' marker should be caught."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Rus. AC3 5.1")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_russian_ru_bracket(self, monkeypatch):
        """'[RU]' marker should be caught."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Show S01E01 1080p WEBRip [RU] AC3")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_russian_rudub_marker(self, monkeypatch):
        """'RuDub' marker should be caught."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Show S01E01 1080p WEBRip RuDub x264")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_cyrillic_title(self, monkeypatch):
        """Title with Cyrillic text should be filtered."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream(
            "Закусочная Боба / Bob's Burgers / Сезон: 13 / Серии: 1-22 из 22 [1080p] MVO"
        )]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_passes_english_stream_with_cyrillic_in_name(self, monkeypatch):
        """Addon name with non-language cyrillic shouldn't break English detection."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [StreamInfo(
            name="Torrentio",
            title="1080p WEBRip x264 English AC3 5.1",
            url="https://example.test/video.mkv",
        )]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_keeps_multi_language_stream(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip Multi Audio AC3 5.1")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_keeps_stream_with_no_language_info(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("1080p WEBRip x264 AAC 5.1")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_filters_stream_with_russian_marker_even_if_english_is_detected(self, monkeypatch):
        """Strict English configs remove anything marked Russian."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("The Russian S01E01 1080p WEBRip x264 English AAC")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_skip_filtering_when_any_is_preferred(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["any"]
        )
        streams = [self.make_stream("1080p WEBRip x264 Русский AC3 5.1")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_dual_language_including_english_passes(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("English + French Dual Audio")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_filters_russian_even_when_english_is_also_marked(self, monkeypatch):
        """English-preferred configs must not accept Russian/English dual releases."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Bob's Burgers S13E01 1080p English Russian Dual Audio")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_filters_russian_even_when_multi_audio_is_marked(self, monkeypatch):
        """Multi-audio releases are still blocked when they also say Russian/RU."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Bob's Burgers S13E01 1080p Multi Audio [RU]")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 0

    def test_eng_marker_counts_as_english_preference(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [self.make_stream("Bob's Burgers S13E01 1080p WEB-DL ENG AAC")]
        result = stream_downloads.filter_streams_by_language(streams)
        assert len(result) == 1

    def test_can_use_download_config_languages_instead_of_global_settings(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["any"]
        )
        streams = [
            self.make_stream("Bob's Burgers S13E01 1080p Russian AAC"),
            self.make_stream("Bob's Burgers S13E01 1080p ENG AAC"),
        ]
        result = stream_downloads.filter_streams_by_language(streams, preferred_languages=["english"])
        assert len(result) == 1
        assert "ENG" in result[0].title

    def test_spanish_preferred_keeps_spanish_filters_russian(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["spanish"]
        )
        es = self.make_stream("1080p WEBRip x264 Español AC3 5.1")
        ru = self.make_stream("1080p WEBRip x264 Russian AC3 5.1")
        en = self.make_stream("1080p WEBRip x264 English AC3 5.1")
        result = stream_downloads.filter_streams_by_language([es, ru, en])
        assert len(result) == 1  # only spanish matches; russian and english filtered
        assert result[0] == es


class TestSelectQualityStreamsWithLanguage:
    """Verify select_quality_streams applies language filtering."""

    def _make_stream(
        self, title: str, name: str = "Torrentio", url: str | None = "https://dl.test"
    ) -> StreamInfo:
        return StreamInfo(name=name, title=title, url=url)

    def test_filters_russian_with_english_default(self, monkeypatch):
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [
            self._make_stream("S01E01 1080p WEBRip Русский AAC"),
            self._make_stream("S01E01 1080p WEBRip English AAC"),
        ]
        result = stream_downloads.select_quality_streams(streams, "1080p")
        assert len(result) == 1
        assert "english" in result[0].title.lower()

    def test_filters_by_addon_name_too(self, monkeypatch):
        """Language detected in stream.name is also filtered."""
        monkeypatch.setattr(
            stream_downloads.settings, "PREFERRED_LANGUAGES", ["english"]
        )
        streams = [
            self._make_stream("S01E01 1080p AAC", name="Torrentio Russian"),
            self._make_stream("S01E01 1080p AAC", name="Torrentio English"),
        ]
        result = stream_downloads.select_quality_streams(streams, "1080p")
        assert len(result) == 1
        assert "English" in result[0].name
