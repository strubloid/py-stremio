"""HLS playlist parser and segment downloader.

HLS (HTTP Live Streaming) delivers video as a small ``.m3u8`` playlist
file that lists many ``.ts``/``.m4s`` segment URLs.  Stremio's player
can play these by resolving the playlist and streaming segments on the
fly, but the existing single-URL download path saves the playlist itself
as the "video" — a 480-byte manifest instead of a real file.  This
module does the work Stremio's player does: fetch the master playlist
(if present), pick a variant, fetch the media playlist, download every
segment, and concatenate them into one output file.

The downloader is intentionally addon-agnostic — configuration that
varies per addon (preferred quality order, output filename handling)
lives on the addon class that opts into HLS support.  See
``HDHubAddon`` for the reference wiring.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin

import httpx

from py_stremio.utils.cancellation import raise_if_shutdown_requested


_MASTER_INF_TAG = "#EXT-X-STREAM-INF"

# Master playlist variant selection: when picking among quality buckets,
# these map a quality string to the canonical height in pixels.  Order
# in HLS_PREFERRED_QUALITY_ORDER drives preference; missing qualities
# fall back to the closest available variant.
_QUALITY_TO_HEIGHT: dict[str, int] = {
    "2160p": 2160, "4k": 2160, "uhd": 2160,
    "1080p": 1080, "fhd": 1080,
    "720p": 720, "hd": 720,
    "480p": 480, "sd": 480,
    "360p": 360,
}

HLS_PREFERRED_QUALITY_ORDER: tuple[str, ...] = (
    "1080p", "720p", "480p", "2160p",
)

# Many CDN-driven addons (HDHub in particular) embed the requested
# quality in the URL itself: ``/resolve/cj/tmdb/118422/1080p.m3u8``.
# When the master playlist is fetched from that URL, the matching
# variant is preferred over the bandwidth-only fallback.
_URL_QUALITY_RE = re.compile(r"/(\d{3,4}p)\.m3u8", re.IGNORECASE)


class HlsPlaylistError(RuntimeError):
    """Raised when the .m3u8 playlist cannot be parsed."""


class HlsVariantError(RuntimeError):
    """Raised when a master playlist contains no usable variants."""


class HlsStallError(RuntimeError):
    """Raised when an HLS segment fetch stalls past the stall timeout."""


@dataclass(frozen=True)
class HlsVariant:
    url: str
    bandwidth: int = 0
    resolution: tuple[int, int] | None = None
    codecs: str = ""


@dataclass(frozen=True)
class HlsSegment:
    url: str
    duration: float = 0.0
    sequence: int = 0


@dataclass
class HlsDownloadStats:
    bytes_downloaded: int = 0
    segments_total: int = 0
    segments_done: int = 0


def _parse_resolution(text):
    if not text:
        return None
    match = re.match(r"^(\d+)x(\d+)$", text.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _parse_ext_attributes(attr_string):
    """Parse the comma-separated attribute list after an ``#EXT-X-*-INF`` tag.

    Quoted values are preserved verbatim (without the surrounding
    quotes); commas inside quotes are not treated as attribute
    separators.  Bare keys (no ``=``) are accepted with an empty value.
    """
    result = {}
    text = attr_string
    parts: list[str] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        if text[pos] == '"':
            end = text.find('"', pos + 1)
            if end == -1:
                parts.append(text[pos:])
                pos = len(text)
            else:
                parts.append(text[pos:end + 1])
                pos = end + 1
        else:
            end = pos
            while end < len(text) and text[end] != ",":
                # A quote opens a quoted value that may span until
                # the matching close quote (which can contain commas).
                if text[end] == '"':
                    close = text.find('"', end + 1)
                    if close == -1:
                        end = len(text)
                    else:
                        end = close + 1
                    continue
                end += 1
            parts.append(text[pos:end])
            pos = end
        if pos < len(text) and text[pos] == ",":
            pos += 1

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, _, value = part.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            result[key] = value
        else:
            result[part] = ""
    return result


def _is_master_playlist(text):
    return _MASTER_INF_TAG in text


def _next_url(lines, start, base_url):
    """Return the next non-comment, non-blank URL line after *start*."""
    for j in range(start, len(lines)):
        candidate = lines[j].strip()
        if not candidate or candidate.startswith("#"):
            continue
        return urljoin(base_url, candidate)
    return None


def _parse_master_playlist(text, base_url):
    """Parse a master playlist into a list of variants.

    Each ``#EXT-X-STREAM-INF`` line is followed by the variant URL on
    the next non-blank, non-comment line.
    """
    variants = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith(f"{_MASTER_INF_TAG}:"):
            attrs = _parse_ext_attributes(line[len(f"{_MASTER_INF_TAG}:"):])
            url = _next_url(lines, i + 1, base_url)
            if url:
                variants.append(HlsVariant(
                    url=url,
                    bandwidth=int(attrs.get("BANDWIDTH") or 0),
                    resolution=_parse_resolution(attrs.get("RESOLUTION")),
                    codecs=attrs.get("CODECS", ""),
                ))
        i += 1
    return variants


def _select_variant_url(
    variants,
    preferred_quality_order=HLS_PREFERRED_QUALITY_ORDER,
    requested_quality=None,
):
    """Pick the variant matching *preferred_quality_order*.

    Selection order:
      1. An exact height match for the requested quality (URL suffix
         like ``/1080p.m3u8``) — the addon's URL contract is honoured
         first.
      2. An exact height match for the highest-priority configured
         quality.
      3. The variant closest to the highest-priority height.
      4. The highest-bandwidth variant.

    Raises :class:`HlsVariantError` when the list is empty.
    """
    if not variants:
        raise HlsVariantError("Master playlist contained no variants")

    priority_heights = [
        _QUALITY_TO_HEIGHT[q.strip().lower()]
        for q in preferred_quality_order
        if q.strip().lower() in _QUALITY_TO_HEIGHT
    ]

    if requested_quality:
        requested_height = _QUALITY_TO_HEIGHT.get(requested_quality.lower())
        if requested_height is not None:
            for variant in variants:
                if variant.resolution and variant.resolution[1] == requested_height:
                    return variant.url

    for height in priority_heights:
        for variant in variants:
            if variant.resolution and variant.resolution[1] == height:
                return variant.url

    with_resolution = [v for v in variants if v.resolution]
    if with_resolution:
        target = priority_heights[0] if priority_heights else 1080
        with_resolution.sort(key=lambda v: abs(v.resolution[1] - target))
        return with_resolution[0].url

    variants_sorted = sorted(variants, key=lambda v: v.bandwidth, reverse=True)
    return variants_sorted[0].url


def _parse_media_playlist(text, base_url):
    """Parse a media playlist into a list of segments.

    Each ``#EXTINF`` line is followed by the segment URL on the next
    non-blank, non-comment line.  ``#EXT-X-MEDIA-SEQUENCE`` shifts the
    starting sequence number.
    """
    segments = []
    sequence = 0
    pending_duration = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                sequence = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if line.startswith("#EXTINF:"):
            try:
                pending_duration = float(line.split(":", 1)[1].split(",", 1)[0].strip())
            except ValueError:
                pending_duration = 0.0
            continue
        if line.startswith("#"):
            continue
        segments.append(HlsSegment(
            url=urljoin(base_url, line),
            duration=pending_duration if pending_duration is not None else 0.0,
            sequence=sequence,
        ))
        sequence += 1
        pending_duration = None
    return segments


def _detect_url_quality(url):
    """Return the quality string encoded in *url*'s path, when present."""
    match = _URL_QUALITY_RE.search(url)
    if not match:
        return None
    return match.group(1).lower()


class HlsDownloader:
    """Parse and download HLS playlists (master + media).

    The downloader is built to be reused across many HLS fetches (one
    per episode/movie) within a single session: the underlying
    :class:`httpx.Client` keeps connections warm, and the
    ``preferred_quality_order`` only needs to be set once.
    """

    def __init__(
        self,
        *,
        bandwidth_limiter=None,
        thread_id=None,
        progress_callback=None,
        stall_timeout=60.0,
        preferred_quality_order=HLS_PREFERRED_QUALITY_ORDER,
        http_client=None,
        user_agent="Stremio/4.4.168",
    ):
        self.bandwidth_limiter = bandwidth_limiter
        self.thread_id = thread_id if thread_id is not None else threading.get_ident()
        self.progress_callback = progress_callback
        self.stall_timeout = float(stall_timeout) if stall_timeout else 0.0
        self.preferred_quality_order = tuple(preferred_quality_order)
        self.user_agent = user_agent
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(
            timeout=httpx.Timeout(60.0, read=self.stall_timeout) if self.stall_timeout > 0 else 60.0,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
        )
        self._registered_bandwidth = False

    def close(self):
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def download(self, url, filename):
        """Resolve *url* and concatenate its segments into *filename*.

        Handles master playlists (selects the best variant) and direct
        media playlists.  The output file is overwritten when it
        already exists.  Returns download stats for the caller to
        surface in progress UIs.
        """
        stats = HlsDownloadStats()
        playlist_text = self._fetch_text(url)

        if _is_master_playlist(playlist_text):
            variants = _parse_master_playlist(playlist_text, base_url=url)
            requested_quality = _detect_url_quality(url)
            media_url = _select_variant_url(
                variants,
                preferred_quality_order=self.preferred_quality_order,
                requested_quality=requested_quality,
            )
            playlist_text = self._fetch_text(media_url)
            base_url = media_url
        else:
            base_url = url

        segments = _parse_media_playlist(playlist_text, base_url=base_url)
        if not segments:
            raise HlsPlaylistError(f"No segments found in playlist at {url}")
        stats.segments_total = len(segments)

        self._download_segments(segments, filename, stats)
        return stats

    def _fetch_text(self, url):
        response = self._http_client.get(url)
        raise_if_shutdown_requested()
        response.raise_for_status()
        return response.text

    def _ensure_bandwidth_registered(self):
        if self._registered_bandwidth:
            return
        limiter = self.bandwidth_limiter
        if limiter is None or not hasattr(limiter, "register_thread"):
            return
        if not limiter.is_thread_registered(self.thread_id):
            limiter.register_thread(self.thread_id)
            self._registered_bandwidth = True

    def _release_bandwidth(self):
        if not self._registered_bandwidth:
            return
        limiter = self.bandwidth_limiter
        if limiter is not None:
            limiter.unregister_thread(self.thread_id)
        self._registered_bandwidth = False

    def _fetch_segment(self, segment):
        """Fetch a single HLS segment with stall detection + bandwidth limit."""
        self._ensure_bandwidth_registered()
        try:
            if self.stall_timeout > 0:
                timeout = httpx.Timeout(300.0, read=self.stall_timeout)
            else:
                timeout = 300.0

            with self._http_client.stream("GET", segment.url, timeout=timeout) as response:
                raise_if_shutdown_requested()
                response.raise_for_status()
                chunks = []
                downloaded = 0
                last_chunk_at = time.monotonic()
                for chunk in response.iter_bytes(chunk_size=8192):
                    raise_if_shutdown_requested()
                    now = time.monotonic()
                    if (
                        self.stall_timeout > 0
                        and downloaded > 0
                        and (now - last_chunk_at) > self.stall_timeout
                    ):
                        raise HlsStallError(
                            f"No new bytes for {self.stall_timeout}s while fetching "
                            f"{segment.url}"
                        )
                    if not chunk:
                        break
                    if self.bandwidth_limiter:
                        self.bandwidth_limiter.wait_for(
                            len(chunk), thread_id=self.thread_id
                        )
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    last_chunk_at = time.monotonic()
                return b"".join(chunks)
        except httpx.ReadTimeout as exc:
            raise HlsStallError(
                f"Read timeout while fetching {segment.url}"
            ) from exc
        finally:
            self._release_bandwidth()

    def _download_segments(self, segments, filename, stats):
        from pathlib import Path

        output = Path(filename)
        partial = output.with_name(f"{output.name}.part")
        total = len(segments)

        with open(partial, "wb") as out:
            for index, segment in enumerate(segments):
                raise_if_shutdown_requested()
                body = self._fetch_segment(segment)
                out.write(body)
                stats.bytes_downloaded += len(body)
                stats.segments_done = index + 1
                if self.progress_callback:
                    self.progress_callback(stats.segments_done, total)

        self._validate_and_finalize(partial, output)

    def _validate_and_finalize(self, partial, output):
        from py_stremio.components.configs.app_settings import settings

        actual_size = partial.stat().st_size
        min_bytes = max(
            0, getattr(settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 100)
        ) * 1024 * 1024
        if min_bytes > 0 and actual_size < min_bytes:
            partial.unlink(missing_ok=True)
            raise HlsPlaylistError(
                f"HLS download produced only {actual_size} bytes "
                f"(min {min_bytes} for a complete video)"
            )
        partial.replace(output)


__all__ = [
    "HlsDownloader",
    "HlsDownloadStats",
    "HlsPlaylistError",
    "HlsVariantError",
    "HlsStallError",
    "HlsVariant",
    "HlsSegment",
    "HLS_PREFERRED_QUALITY_ORDER",
]