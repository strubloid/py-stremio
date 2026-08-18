"""Tests for the HLS playlist downloader and HDHub's opt-in integration."""
from __future__ import annotations

import io
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from py_stremio.components.addons.base import UrlAddon, _is_hls_stream_url
from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.addons.types.comet_family.HDHubAddon import HDHubAddon
from py_stremio.components.download import hls_download
from py_stremio.components.download.hls_download import (
    HLS_PREFERRED_QUALITY_ORDER,
    HlsDownloader,
    HlsDownloadStats,
    HlsPlaylistError,
    HlsStallError,
    HlsVariantError,
    _detect_url_quality,
    _is_master_playlist,
    _parse_ext_attributes,
    _parse_master_playlist,
    _parse_media_playlist,
    _parse_resolution,
    _select_variant_url,
)
from py_stremio.components.download.stream_download import (
    _download_hls_to_file,
    _is_hls_url,
    download_stream_to_file,
)


@pytest.fixture(autouse=True)
def _disable_min_video_size(monkeypatch):
    """The HLS downloader enforces ``MIN_COMPLETED_VIDEO_SIZE_MB`` like the
    direct-download path.  Test segment bodies are tiny (under 100 MB) so we
    zero that setting for the duration of every HLS test."""
    from py_stremio.components.configs import app_settings

    monkeypatch.setattr(app_settings.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 0, raising=False)
    yield


# ── URL / extension detection ──────────────────────────────────────────


def test_is_hls_stream_url_detects_m3u8():
    assert _is_hls_stream_url("http://hdhub.test/resolve/cj/tmdb/118422/1080p.m3u8")


def test_is_hls_stream_url_detects_m3u():
    assert _is_hls_stream_url("https://example.test/playlist.m3u")


def test_is_hls_stream_url_ignores_query_string():
    assert _is_hls_stream_url("https://example.test/video.m3u8?token=abc")


def test_is_hls_stream_url_rejects_other_extensions():
    assert not _is_hls_stream_url("https://example.test/video.mp4")
    assert not _is_hls_stream_url("https://example.test/video.mkv")
    assert not _is_hls_stream_url("https://example.test/video.ts")


def test_is_hls_stream_url_handles_empty_and_none():
    assert not _is_hls_stream_url(None)
    assert not _is_hls_stream_url("")
    assert not _is_hls_stream_url("not a url")


def test_is_hls_url_in_stream_download_module():
    assert _is_hls_url("https://x.test/a.m3u8")
    assert not _is_hls_url("https://x.test/a.mp4")
    assert not _is_hls_url(None)
    assert not _is_hls_url("")


# ── Attribute parsing ──────────────────────────────────────────────────


def test_parse_ext_attributes_quoted_values():
    attrs = _parse_ext_attributes(
        'BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"'
    )
    assert attrs == {
        "BANDWIDTH": "5000000",
        "RESOLUTION": "1920x1080",
        "CODECS": "avc1.640028,mp4a.40.2",
    }


def test_parse_ext_attributes_bare_keys():
    attrs = _parse_ext_attributes("STABLE-VARIANT,FRAME-RATE=30.000")
    assert attrs == {"STABLE-VARIANT": "", "FRAME-RATE": "30.000"}


def test_parse_resolution():
    assert _parse_resolution("1920x1080") == (1920, 1080)
    assert _parse_resolution("1280x720") == (1280, 720)
    assert _parse_resolution(None) is None
    assert _parse_resolution("garbage") is None


# ── Variant selection ──────────────────────────────────────────────────


MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028"
1080p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
720p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=15000000,RESOLUTION=3840x2160
2160p.m3u8
"""


def test_is_master_playlist_detects_stream_inf():
    assert _is_master_playlist(MASTER_PLAYLIST)


def test_is_master_playlist_rejects_media_only():
    assert not _is_master_playlist(
        "#EXTM3U\n#EXTINF:6.000,\nseg0.ts\n#EXT-X-ENDLIST\n"
    )


def test_parse_master_playlist_extracts_all_variants():
    variants = _parse_master_playlist(
        MASTER_PLAYLIST,
        base_url="http://hdhub.test/resolve/cj/tmdb/118422/",
    )
    assert len(variants) == 3
    assert variants[0].resolution == (1920, 1080)
    assert variants[1].bandwidth == 2500000
    assert variants[2].codecs == ""
    assert variants[0].url.endswith("/1080p.m3u8")


def test_select_variant_url_prefers_url_requested_quality():
    variants = _parse_master_playlist(
        MASTER_PLAYLIST,
        base_url="http://hdhub.test/resolve/cj/tmdb/118422/",
    )
    selected = _select_variant_url(
        variants,
        requested_quality="1080p",
        preferred_quality_order=HLS_PREFERRED_QUALITY_ORDER,
    )
    assert selected.endswith("/1080p.m3u8")


def test_select_variant_url_falls_back_to_preferred_order():
    variants = _parse_master_playlist(
        MASTER_PLAYLIST,
        base_url="http://hdhub.test/",
    )
    selected = _select_variant_url(
        variants,
        preferred_quality_order=("1080p", "720p", "480p"),
    )
    assert selected.endswith("/1080p.m3u8")


def test_select_variant_url_picks_closest_when_no_exact_match():
    variants_text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
360p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=14000000,RESOLUTION=3840x2160
2160p.m3u8
"""
    variants = _parse_master_playlist(variants_text, base_url="http://x.test/")
    selected = _select_variant_url(
        variants,
        preferred_quality_order=("1080p", "720p", "480p"),
    )
    # No 1080p/720p/480p variant — 360p is closer to 480 than 2160p is.
    assert selected.endswith("/360p.m3u8")


def test_select_variant_url_raises_on_empty_list():
    with pytest.raises(HlsVariantError):
        _select_variant_url([])


def test_select_variant_url_falls_back_to_highest_bandwidth_without_resolution():
    variants_text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000
a.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000
b.m3u8
"""
    variants = _parse_master_playlist(variants_text, base_url="http://x.test/")
    selected = _select_variant_url(variants)
    assert selected.endswith("/b.m3u8")


# ── Media playlist parsing ────────────────────────────────────────────


MEDIA_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:100
#EXTINF:6.000,
seg100.ts
#EXTINF:6.000,
seg101.ts
#EXTINF:4.500,
seg102.ts
#EXT-X-ENDLIST
"""


def test_parse_media_playlist_extracts_segments_with_absolute_urls():
    segments = _parse_media_playlist(
        MEDIA_PLAYLIST,
        base_url="http://hdhub.test/resolve/cj/tmdb/118422/",
    )
    assert len(segments) == 3
    assert [s.sequence for s in segments] == [100, 101, 102]
    assert [round(s.duration, 3) for s in segments] == [6.0, 6.0, 4.5]
    assert all(s.url.startswith("http://hdhub.test/resolve/cj/tmdb/118422/") for s in segments)
    assert segments[0].url.endswith("/seg100.ts")


def test_parse_media_playlist_resolves_absolute_segment_urls():
    playlist = """#EXTM3U
#EXTINF:6.000,
https://cdn.example.test/path/seg0.ts
#EXTINF:6.000,
seg1.ts
"""
    segments = _parse_media_playlist(playlist, base_url="http://hdhub.test/x/")
    assert segments[0].url == "https://cdn.example.test/path/seg0.ts"
    assert segments[1].url == "http://hdhub.test/x/seg1.ts"


def test_parse_media_playlist_ignores_unknown_tags():
    playlist = """#EXTM3U
#EXT-X-DISCONTINUITY-SEQUENCE:0
#EXT-X-PROGRAM-DATE-TIME:2024-01-01T00:00:00Z
#EXTINF:6.000,
seg0.ts
"""
    segments = _parse_media_playlist(playlist, base_url="http://x.test/")
    assert len(segments) == 1


def test_parse_media_playlist_empty():
    assert _parse_media_playlist("#EXTM3U\n", base_url="http://x.test/") == []


# ── URL quality detection ──────────────────────────────────────────────


def test_detect_url_quality():
    assert _detect_url_quality("http://hdhub.test/resolve/cj/tmdb/118422/1080p.m3u8") == "1080p"
    assert _detect_url_quality("http://hdhub.test/resolve/cj/tmdb/118422/2160p.m3u8") == "2160p"
    assert _detect_url_quality("http://hdhub.test/resolve/cj/tmdb/118422/720p.m3u8") == "720p"
    assert _detect_url_quality("http://hdhub.test/master.m3u8") is None
    assert _detect_url_quality("http://hdhub.test/") is None


# ── HDHub addon opt-in ─────────────────────────────────────────────────


HDHUB_STREAM_DICT = {
    "name": "Hdhub CJ 1080p",
    "title": "90 Day Fiance S5E1 1080p",
    "url": "http://hdhub.thevolecitor.qzz.io/resolve/cj/tmdb/90046/1080p.m3u8",
    "behaviorHints": {"notWebReady": True, "bingeGroup": "cinejoy-90046"},
}


def test_hdhub_class_declares_hls_capable():
    assert HDHubAddon.HLS_CAPABLE is True


def test_hdhub_parses_hls_stream_with_is_hls_flag():
    addon = HDHubAddon()
    streams = addon.parse_streams([HDHUB_STREAM_DICT])
    assert len(streams) == 1
    assert streams[0].url == HDHUB_STREAM_DICT["url"]
    assert streams[0].is_hls is True
    assert streams[0].addon_name == "HDHub"


def test_hdhub_keeps_hls_streams_that_base_filter_would_drop():
    """HDHub's override of parse_streams must let .m3u8 + notWebReady through."""
    addon = HDHubAddon()
    streams = addon.parse_streams([HDHUB_STREAM_DICT])
    assert streams != [], "HDHub must NOT drop HLS streams it can download"


def test_hdhub_still_filters_advisory_streams():
    addon = HDHubAddon()
    streams = addon.parse_streams([
        {
            "name": "Donation needed.",
            "title": "Configure this addon to access streams.",
        },
        HDHUB_STREAM_DICT,
    ])
    assert len(streams) == 1
    assert streams[0].url == HDHUB_STREAM_DICT["url"]


def test_hdhub_keeps_direct_video_urls_with_is_hls_false():
    addon = HDHubAddon()
    streams = addon.parse_streams([
        {
            "name": "HDHub Direct 1080p",
            "title": "Show S01E01 1080p",
            "url": "https://cdn.example.test/video.mp4",
            "behaviorHints": {"notWebReady": True},
        },
    ])
    assert len(streams) == 1
    assert streams[0].is_hls is False


def test_generic_url_addon_still_drops_hls_streams():
    """Generic UrlAddon (used for unknown addons in addons.txt) keeps the
    legacy "drop HLS" behaviour so a misconfigured addon can't make us
    try to download a 480-byte manifest as a video file."""
    addon = UrlAddon("https://hdhub.thevolecitor.qzz.io")
    streams = addon.parse_streams([HDHUB_STREAM_DICT])
    assert streams == []


def test_is_downloadable_stream_candidate_allow_hls_flag():
    """The filter must honour allow_hls=True so HDHub's override can keep
    HLS streams while the default base class still drops them."""
    from py_stremio.components.addons.base import _is_downloadable_stream_candidate

    assert _is_downloadable_stream_candidate(HDHUB_STREAM_DICT) is False
    assert _is_downloadable_stream_candidate(HDHUB_STREAM_DICT, allow_hls=True) is True


def test_hdhub_create_hls_downloader_uses_class_quality_order():
    addon = HDHubAddon()
    downloader = addon.create_hls_downloader()
    try:
        assert downloader.preferred_quality_order == HDHubAddon.HLS_PREFERRED_QUALITY_ORDER
        assert downloader.preferred_quality_order == HLS_PREFERRED_QUALITY_ORDER
    finally:
        downloader.close()


def test_hdhub_create_hls_downloader_per_instance_quality_override():
    addon = HDHubAddon()
    addon.HLS_PREFERRED_QUALITY_ORDER = ("2160p", "1080p", "720p")
    downloader = addon.create_hls_downloader()
    try:
        assert downloader.preferred_quality_order == ("2160p", "1080p", "720p")
    finally:
        downloader.close()
    addon.HLS_PREFERRED_QUALITY_ORDER = HLS_PREFERRED_QUALITY_ORDER


# ── download_stream_to_file dispatch ───────────────────────────────────


def test_download_stream_to_file_dispatches_hls_to_hls_downloader(tmp_path):
    """When stream.is_hls=True and URL is .m3u8, the HLS path is taken."""
    target = tmp_path / "episode.mkv"

    stream = StreamInfo(
        name="Hdhub 1080p",
        url="http://hdhub.test/resolve/cj/tmdb/1/1080p.m3u8",
        addon_name="HDHub",
        is_hls=True,
    )

    fake_downloader = MagicMock()
    fake_downloader.download = MagicMock(return_value=HlsDownloadStats())
    fake_class = MagicMock(return_value=fake_downloader)

    with patch.object(hls_download, "HlsDownloader", fake_class):
        download_stream_to_file(
            stream.url,
            str(target),
            stream=stream,
        )

    fake_class.assert_called_once()
    fake_downloader.download.assert_called_once_with(stream.url, str(target))
    fake_downloader.close.assert_called_once()


def test_download_stream_to_file_skips_hls_path_when_stream_not_marked(tmp_path):
    """When stream.is_hls=False (default), HLS path is skipped even for .m3u8 URLs."""
    target = tmp_path / "episode.mkv"

    stream = StreamInfo(
        name="Hdhub 1080p",
        url="http://hdhub.test/resolve/cj/tmdb/1/1080p.m3u8",
        addon_name="HDHub",
        is_hls=False,
    )

    fake_downloader = MagicMock()
    fake_class = MagicMock(return_value=fake_downloader)

    # The HLS downloader must NOT be called when the stream is not flagged
    # as HLS. The direct-download path will then fail because there's no
    # real HTTP server here — we catch the expected exception to prove
    # the HLS path was not entered.
    with patch.object(hls_download, "HlsDownloader", fake_class):
        with pytest.raises(Exception):
            download_stream_to_file(stream.url, str(target), stream=stream)

    fake_class.assert_not_called()


def test_download_stream_to_file_skips_hls_path_when_stream_missing(tmp_path):
    """Backwards-compat: callers that pass no stream at all must not
    trigger the HLS path (legacy direct downloads)."""
    target = tmp_path / "episode.mkv"

    fake_class = MagicMock()
    with patch.object(hls_download, "HlsDownloader", fake_class):
        with pytest.raises(Exception):
            download_stream_to_file("http://hdhub.test/1080p.m3u8", str(target))

    fake_class.assert_not_called()


# ── End-to-end with mocked HTTP ────────────────────────────────────────


class _FakeHlsResponse:
    """Minimal httpx-compatible response that yields a fixed body."""

    def __init__(self, body: bytes, status_code: int = 200):
        self.body = body
        self.status_code = status_code
        self.headers = {"content-length": str(len(body))}
        try:
            self.text = body.decode("utf-8")
        except UnicodeDecodeError:
            self.text = ""
        self._raise_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=MagicMock(), response=MagicMock()
            )

    def iter_bytes(self, chunk_size=8192):
        i = 0
        while i < len(self.body):
            yield self.body[i:i + chunk_size]
            i += chunk_size


class _FakeHlsClient:
    """Fake httpx.Client that serves a routing table keyed by URL.

    Routes can be either:
      - str (returned verbatim as text body), or
      - bytes (returned as the segment body).
    """

    def __init__(self, routes: dict[str, str | bytes]):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(("GET", url))
        body = self.routes.get(url)
        if body is None:
            raise AssertionError(f"Unexpected GET {url}")
        return _FakeHlsResponse(body.encode() if isinstance(body, str) else body)

    def stream(self, method, url, timeout=None):
        self.calls.append(("STREAM", method, url))
        body = self.routes.get(url)
        if body is None:
            raise AssertionError(f"Unexpected {method} {url}")
        return _FakeHlsResponse(body.encode() if isinstance(body, str) else body)

    def close(self):
        pass


def _master_playlist(media_url_1080p: str, media_url_720p: str, media_url_2160p: str) -> str:
    return (
        "#EXTM3U\n"
        f"#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080\n{media_url_1080p}\n"
        f"#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720\n{media_url_720p}\n"
        f"#EXT-X-STREAM-INF:BANDWIDTH=15000000,RESOLUTION=3840x2160\n{media_url_2160p}\n"
    )


def _media_playlist(*segment_urls: str, durations: list[float] | None = None) -> str:
    durations = durations or [6.0] * len(segment_urls)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:6", "#EXT-X-MEDIA-SEQUENCE:0"]
    for url, dur in zip(segment_urls, durations):
        lines.append(f"#EXTINF:{dur:.3f},")
        lines.append(url)
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def test_hls_downloader_resolves_master_picks_1080p_and_concatenates(tmp_path):
    """End-to-end: master → variant → media → segments → file."""
    base = "http://hdhub.test/resolve/cj/tmdb/118422"
    master_url = f"{base}/1080p.m3u8"
    media_url = f"{base}/media_1080p.m3u8"
    seg_urls = [f"{base}/seg{i}.ts" for i in range(3)]

    client = _FakeHlsClient({
        master_url: _master_playlist(media_url, f"{base}/media_720p.m3u8", f"{base}/media_2160p.m3u8"),
        media_url: _media_playlist(*seg_urls),
        seg_urls[0]: b"\x47" * 4096,
        seg_urls[1]: b"\x47" * 2048,
        seg_urls[2]: b"\x47" * 1024,
    })

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(http_client=client)
    stats = downloader.download(master_url, str(target))
    downloader.close()

    assert target.exists()
    # The .part file must be renamed, not left behind
    assert not target.with_name(target.name + ".part").exists()
    assert stats.segments_total == 3
    assert stats.segments_done == 3
    assert stats.bytes_downloaded == 4096 + 2048 + 1024
    assert target.stat().st_size == 4096 + 2048 + 1024

    # Verify the URLs were fetched in the right order
    assert client.calls[0] == ("GET", master_url)
    assert client.calls[1] == ("GET", media_url)
    for i, url in enumerate(seg_urls):
        assert client.calls[2 + i] == ("STREAM", "GET", url)


def test_hls_downloader_handles_direct_media_playlist(tmp_path):
    """When the URL is already a media playlist, master detection passes through."""
    base = "http://hdhub.test/resolve/cj/tmdb/118422/1080p.m3u8"
    seg_urls = [f"http://hdhub.test/seg{i}.ts" for i in range(2)]

    client = _FakeHlsClient({
        base: _media_playlist(*seg_urls),
        seg_urls[0]: b"\x47" * 1024,
        seg_urls[1]: b"\x47" * 2048,
    })

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(http_client=client)
    stats = downloader.download(base, str(target))
    downloader.close()

    assert target.stat().st_size == 1024 + 2048
    assert stats.segments_done == 2


def test_hls_downloader_uses_url_quality_when_master_returned(tmp_path):
    """When the URL is ``/1080p.m3u8`` and the master lists 720p too,
    the requested 1080p variant is chosen (not the bandwidth fallback)."""
    base = "http://hdhub.test/resolve/cj/tmdb/118422"
    master_url = f"{base}/1080p.m3u8"
    media_1080p = f"{base}/media_1080p.m3u8"
    media_720p = f"{base}/media_720p.m3u8"

    client = _FakeHlsClient({
        master_url: f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080
{media_1080p}
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
{media_720p}
""",
        media_1080p: _media_playlist(f"{base}/seg0.ts"),
        f"{base}/seg0.ts": b"\x47" * 1024,
    })

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(http_client=client)
    downloader.download(master_url, str(target))
    downloader.close()

    assert any(call[1] == media_1080p for call in client.calls)


def test_hls_downloader_raises_when_no_segments(tmp_path):
    base = "http://hdhub.test"
    master_url = f"{base}/master.m3u8"
    media_url = f"{base}/media.m3u8"
    client = _FakeHlsClient({
        master_url: f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000
{media_url}
""",
        media_url: "#EXTM3U\n#EXT-X-ENDLIST\n",
    })

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(http_client=client)
    with pytest.raises(HlsPlaylistError):
        downloader.download(master_url, str(target))
    downloader.close()
    assert not target.exists()


def test_hls_downloader_progress_callback(tmp_path):
    base = "http://hdhub.test"
    master_url = f"{base}/master.m3u8"
    media_url = f"{base}/media.m3u8"
    seg_urls = [f"{base}/seg{i}.ts" for i in range(3)]

    client = _FakeHlsClient({
        master_url: f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000
{media_url}
""",
        media_url: _media_playlist(*seg_urls),
        seg_urls[0]: b"\x47" * 100,
        seg_urls[1]: b"\x47" * 200,
        seg_urls[2]: b"\x47" * 300,
    })

    progress = []

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(
        http_client=client,
        progress_callback=lambda done, total: progress.append((done, total)),
    )
    downloader.download(master_url, str(target))
    downloader.close()

    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_hls_downloader_handles_stall_error(tmp_path):
    """A segment that never delivers a second chunk must raise HlsStallError."""
    base = "http://hdhub.test"
    master_url = f"{base}/master.m3u8"
    media_url = f"{base}/media.m3u8"
    seg_url = f"{base}/seg0.ts"

    class _StallResponse:
        def __init__(self):
            self.headers = {"content-length": "10"}
            self.status_code = 200
            self.text = ""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self, chunk_size=8192):
            yield b"x"  # one chunk delivered, then we stall
            import httpx
            raise httpx.ReadTimeout("simulated stall")

    class _StallClient(_FakeHlsClient):
        def stream(self, method, url, timeout=None):
            self.calls.append(("STREAM", method, url))
            return _StallResponse()

    client = _StallClient({
        master_url: f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000
{media_url}
""",
        media_url: _media_playlist(seg_url),
    })

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(
        http_client=client,
        stall_timeout=0.01,  # tiny so the gap trips it fast
    )
    with pytest.raises(HlsStallError):
        downloader.download(master_url, str(target))
    downloader.close()
    assert not target.exists() or target.stat().st_size < 100


def test_hls_downloader_does_not_create_part_for_min_size_failure(tmp_path, monkeypatch):
    """The .part file must be cleaned up when the final size is too small."""
    from py_stremio.components.configs import app_settings

    # Re-enable the min-size check for this test specifically.
    monkeypatch.setattr(
        app_settings.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 1, raising=False,
    )

    base = "http://hdhub.test"
    master_url = f"{base}/master.m3u8"
    media_url = f"{base}/media.m3u8"
    seg_url = f"{base}/seg0.ts"

    client = _FakeHlsClient({
        master_url: f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000
{media_url}
""",
        media_url: _media_playlist(seg_url),
        seg_url: b"\x47" * 100,  # tiny — under the 1 MB threshold
    })

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(http_client=client)
    with pytest.raises(HlsPlaylistError):
        downloader.download(master_url, str(target))
    downloader.close()

    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_hls_downloader_uses_provined_bandwidth_limiter(tmp_path):
    """Bandwidth limiter's wait_for() must be called per chunk."""
    base = "http://hdhub.test"
    master_url = f"{base}/master.m3u8"
    media_url = f"{base}/media.m3u8"
    seg_url = f"{base}/seg0.ts"

    client = _FakeHlsClient({
        master_url: f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000
{media_url}
""",
        media_url: _media_playlist(seg_url),
        seg_url: b"\x47" * 4096 + b"\x47" * 4096,
    })

    limiter = MagicMock()
    limiter.is_thread_registered = MagicMock(return_value=False)
    limiter.register_thread = MagicMock()

    target = tmp_path / "show.mkv"
    downloader = HlsDownloader(
        http_client=client,
        bandwidth_limiter=limiter,
        thread_id=42,
    )
    downloader.download(master_url, str(target))
    downloader.close()

    limiter.register_thread.assert_called_with(42)
    assert limiter.wait_for.called
    limiter.unregister_thread.assert_called_with(42)


def test_hls_downloader_handles_close_when_downloader_already_closed(tmp_path):
    """close() must be idempotent."""
    downloader = HlsDownloader(http_client=_FakeHlsClient({}))
    downloader.close()
    downloader.close()  # second close is a no-op