"""Stream URL resolving and file download helpers."""
from urllib.parse import urlencode

import httpx

import re

from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.debrid.real_debrid_client import resolve_torrent_with_debrid
from py_stremio.components.configs.app_settings import settings

RD_PROXY_PREFIX = "https://torrentio.strem.fun/resolve/"
# Also match the direct realdebrid=<key> format
_RD_DIRECT_PREFIX = "https://torrentio.strem.fun/realdebrid"
_KNOWN_ERROR_VIDEOS = frozenset({
    "failed_access_v2.mp4",
    "failed_access.mp4",
    "error.mp4",
    "unavailable.mp4",
})


class InvalidVideoDownloadError(ValueError):
    """Raised when a resolved stream downloads an invalid placeholder/error file."""


_TEXT_ERROR_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/json",
    "application/xml",
    "text/xml",
)

# Language keyword patterns for stream title filtering.
# Keep short codes token-bound so e.g. "legend" does not imply ENG.
_LANGUAGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\benglish\b", re.IGNORECASE), "english"),
    (re.compile(r"(?:^|[^a-z0-9])eng(?:lish)?(?:$|[^a-z0-9])", re.IGNORECASE), "english"),
    (re.compile(r"\brussian\b", re.IGNORECASE), "russian"),
    (re.compile(r"\bрус(?:ский|ская|ское|ские)?\b", re.IGNORECASE), "russian"),
    (re.compile(r"\brusskiy\b", re.IGNORECASE), "russian"),
    (re.compile(r"(?:^|[^a-z0-9])rus(?:$|[^a-z0-9])", re.IGNORECASE), "russian"),
    (re.compile(r"\brudub\b", re.IGNORECASE), "russian"),
    (re.compile(r"\bspanish\b", re.IGNORECASE), "spanish"),
    (re.compile(r"\bespañol\b", re.IGNORECASE), "spanish"),
    (re.compile(r"\bespanol\b", re.IGNORECASE), "spanish"),
    (re.compile(r"\bfrench\b", re.IGNORECASE), "french"),
    (re.compile(r"\bfrançais\b", re.IGNORECASE), "french"),
    (re.compile(r"\bfrancais\b", re.IGNORECASE), "french"),
    (re.compile(r"\bgerman\b", re.IGNORECASE), "german"),
    (re.compile(r"\bdeutsch\b", re.IGNORECASE), "german"),
    (re.compile(r"\bitalian\b", re.IGNORECASE), "italian"),
    (re.compile(r"\bitaliano\b", re.IGNORECASE), "italian"),
    (re.compile(r"\bportuguese\b", re.IGNORECASE), "portuguese"),
    (re.compile(r"\bportuguês\b", re.IGNORECASE), "portuguese"),
    (re.compile(r"\bportugues\b", re.IGNORECASE), "portuguese"),
    (re.compile(r"\bdutch\b", re.IGNORECASE), "dutch"),
    (re.compile(r"\bnederlands\b", re.IGNORECASE), "dutch"),
    (re.compile(r"\bpolish\b", re.IGNORECASE), "polish"),
    (re.compile(r"\bpolski\b", re.IGNORECASE), "polish"),
    (re.compile(r"\bturkish\b", re.IGNORECASE), "turkish"),
    (re.compile(r"\btürkçe\b", re.IGNORECASE), "turkish"),
    (re.compile(r"\bturkce\b", re.IGNORECASE), "turkish"),
    (re.compile(r"\bjapanese\b", re.IGNORECASE), "japanese"),
    (re.compile(r"日本語", re.IGNORECASE), "japanese"),
    (re.compile(r"\bkorean\b", re.IGNORECASE), "korean"),
    (re.compile(r"한국어", re.IGNORECASE), "korean"),
    (re.compile(r"\bchinese\b", re.IGNORECASE), "chinese"),
    (re.compile(r"中文", re.IGNORECASE), "chinese"),
    (re.compile(r"\barabic\b", re.IGNORECASE), "arabic"),
    (re.compile(r"\bhindi\b", re.IGNORECASE), "hindi"),
    (re.compile(r"\bthai\b", re.IGNORECASE), "thai"),
    (re.compile(r"\bvietnamese\b", re.IGNORECASE), "vietnamese"),
    (re.compile(r"\bswedish\b", re.IGNORECASE), "swedish"),
    (re.compile(r"\bdanish\b", re.IGNORECASE), "danish"),
    (re.compile(r"\bnorwegian\b", re.IGNORECASE), "norwegian"),
    (re.compile(r"\bfinnish\b", re.IGNORECASE), "finnish"),
    (re.compile(r"\bczech\b", re.IGNORECASE), "czech"),
    (re.compile(r"\bhungarian\b", re.IGNORECASE), "hungarian"),
    (re.compile(r"\bromanian\b", re.IGNORECASE), "romanian"),
    (re.compile(r"\bukrainian\b", re.IGNORECASE), "ukrainian"),
    (re.compile(r"\bgreek\b", re.IGNORECASE), "greek"),
]

_MULTI_LANGUAGE_INDICATORS = [
    "multi",
    "multi-lang",
    "multi audio",
    "dual audio",
    "dual-lang",
    "multi-language",
    "multi-audio",
    "multi audio",
    "multi subs",
]

# Cyrillic script → strong indicator of Russian / Slavic content.
# Common in Russian tracker releases even when the show is Western.
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F]")
_ADVISORY_MARKERS = (
    "kindly configure this addon",
    "configure this addon",
    "elfhosted addons disabled",
    "reddit.com/r/stremioaddons",
    "[⛔️]",
    "⛔",
    "ℹ",
)


def _combined_stream_text(stream) -> str:
    return f"{stream.title or ''} {stream.name or ''} {getattr(stream, 'filename', '') or ''}"


def _is_advisory_stream(stream) -> bool:
    text = _combined_stream_text(stream).lower()
    return any(marker in text for marker in _ADVISORY_MARKERS)


def _matches_target_episode(stream, target_season: int | None, target_episode: int | None) -> bool:
    if target_season is None or target_episode is None:
        return True
    text = _combined_stream_text(stream)
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    season = int(target_season)
    episode = int(target_episode)
    episode_tokens = {
        f"s{season:02d}e{episode:02d}",
        f"s{season}e{episode:02d}",
        f"s{season:02d}e{episode}",
        f"season{season}episode{episode}",
    }
    return any(token in compact for token in episode_tokens)

# _matches_show_title and _filter_streams_by_title removed:
# The IMDb ID uniquely identifies the show, and _filter_streams_by_target_episode
# already validates episode matching. Title filtering caused false rejections due
# to torrent naming variations (e.g., "90 Day Fiancé" vs "90 Day The Single Life").


def _filter_streams_by_target_episode(
    streams: list,
    target_season: int | None = None,
    target_episode: int | None = None,
    title: str | None = None,
    target_imdb_id: str | None = None,
) -> list:
    """Filter streams by episode match, IMDB ID cross-validation, and title.

    When *target_imdb_id* is provided, any stream whose ``imdb_id`` field
    is set **and** does not match is rejected (prevents wrong-show downloads
    from misbehaving addons).  Streams without an ``imdb_id`` field are kept
    since many addons don't supply it.

    When *title* is provided, streams whose combined text does NOT contain
    the show title are rejected.  This catches cross-show contamination
    from addons that return wrong content under a correct IMDB ID.
    """
    filtered = []
    for stream in streams:
        if _is_advisory_stream(stream):
            continue
        if not _matches_target_episode(stream, target_season, target_episode):
            continue
        # IMDB ID cross-validation: if the stream has an imdb_id, reject
        # a mismatch even if episode numbers happen to line up.
        stream_imdb = getattr(stream, 'imdb_id', None)
        if target_imdb_id and stream_imdb and stream_imdb != target_imdb_id:
            continue
        # Title containment check: reject streams whose release name
        # doesn't contain the show title.  Normalize dots/hyphens/underscores
        # to spaces on both sides so title-based names like
        # "Bob's.Burgers.S13E13" still match "Bob's Burgers".
        if title:
            combined = _combined_stream_text(stream).lower()
            combined_norm = re.sub(r"[._\-]", " ", combined)
            title_norm = re.sub(r"[._\-]", " ", title.lower())
            if title_norm not in combined_norm:
                continue
        filtered.append(stream)
    return filtered


def _normalize_preferred_languages(preferred_languages: list[str] | None = None) -> list[str]:
    preferred = preferred_languages if preferred_languages is not None else settings.PREFERRED_LANGUAGES
    normalized = [lang.strip().lower() for lang in preferred if lang and lang.strip()]
    return normalized or ["any"]


def _detect_languages(text: str) -> set[str]:
    """Return set of canonical language names found in the given text."""
    found: set[str] = set()
    text_lower = text.lower()
    for pattern, canonical in _LANGUAGE_PATTERNS:
        if pattern.search(text):
            found.add(canonical)
    for indicator in _MULTI_LANGUAGE_INDICATORS:
        if indicator in text_lower:
            found.add("multi")
            break
    # Cyrillic text → Russian
    if _CYRILLIC_RE.search(text):
        found.add("russian")
    return found


def filter_streams_by_language(streams: list, preferred_languages: list[str] | None = None) -> list:
    """Filter streams to prefer requested languages without blocking Russian.

    Russian/Cyrillic markers are allowed because those releases may also carry
    English audio and were causing valid Stremio-playable streams to be skipped.
    Streams with *no* detectable language are kept (safe default). Multi-language
    streams pass. Streams whose detected languages include at least one preferred
    language pass. Other non-preferred single-language streams are filtered out.
    When preferred languages contains ``"any"``, all streams pass.
    """
    preferred = _normalize_preferred_languages(preferred_languages)

    if "any" in preferred:
        return streams

    filtered = []
    for stream in streams:
        title = stream.title or ""
        name = stream.name or ""
        combined = f"{title} {name}"

        detected = _detect_languages(combined)

        # Russian/Cyrillic markers are no longer a hard block: many of those
        # releases still include English audio, and blocking them caused valid
        # cached RD streams to stay stuck at "waiting for download".
        if "russian" in detected:
            filtered.append(stream)
            continue

        # Multi-language streams pass after explicitly-banned languages were removed.
        if "multi" in detected:
            filtered.append(stream)
            continue

        # No language detected → safe default, keep
        if not detected:
            filtered.append(stream)
            continue

        # At least one preferred language matches → keep
        if any(pref in detected for pref in preferred):
            filtered.append(stream)
            continue

        # Only non-preferred languages detected → filter out
        continue

    return filtered


def _quality_sort_key(stream) -> tuple:
    """Sort streams by quality: 4K > 1080p > 720p > 480p > 360p > others.
    Prefers streams with a direct URL over info_hash-only at the same quality.
    Prefers streams with more seeders at the same quality level."""
    name = (stream.name or "").lower()
    title = (stream.title or "").lower()

    # Prefer streams from non-Torrentio addons (less likely blocked)
    addon = (getattr(stream, "addon_name", "") or "").lower()

    qscore = 1
    if "2160" in name or "2160" in title or "4k" in name or "4k" in title:
        qscore = 100
    elif "1080" in name or "1080" in title or "fhd" in name or "fhd" in title:
        qscore = 80
    elif "720" in name or "720" in title or "hd" in name or "hd" in title:
        qscore = 60
    elif "480" in name or "480" in title or "sd" in name or "sd" in title:
        qscore = 40
    elif "360" in name or "360" in title:
        qscore = 20

    url_bonus = 1 if stream.url else 0
    addon_bonus = 0
    if "comet" in addon:
        # Configured Comet returns RD playback URLs for the exact episode and
        # has proven more reliable for Bob's Burgers than Torrentio season-pack
        # RD proxies / info_hash fallback.
        addon_bonus = 30
    elif "torrentio" not in addon:
        addon_bonus = 10
    seeders = getattr(stream, "seeders", None) or 0
    # Sort descending: direct/playable URLs first, then quality, addon
    # reliability, then seeders. Info-hash-only streams can require a slow
    # RealDebrid magnet/poll flow, so try Stremio-playable URLs before them.
    return (-url_bonus, -qscore, -addon_bonus, -seeders)


def select_quality_streams(
    streams: list,
    preferred_quality: str,
    preferred_languages: list[str] | None = None,
    target_season: int | None = None,
    target_episode: int | None = None,
    title: str | None = None,
    target_imdb_id: str | None = None,
) -> list:
    """Filter out unusable streams, then return all usable ones sorted by quality
    descending (1080p > 720p > 480p > ...) so the caller can try best first
    and fall back to lower qualities.

    When *title* is provided, warns about streams whose release name doesn't
    contain the show title — this helps catch IMDB-ID mismatches where an
    addon returns a wrong show's episode under the requested ID.

    When *target_imdb_id* is provided, streams whose ``imdb_id`` field does
    not match are rejected (hard validation, not a warning).
    """
    usable = [
        s for s in streams
        if s.url or s.info_hash
    ]
    # Apply target media filter before language/quality sorting so unrelated
    # high-quality results (for example The Bob's Burgers Movie on a series ID)
    # cannot crowd real episode streams out of the retry list.
    usable = _filter_streams_by_target_episode(
        usable,
        target_season=target_season,
        target_episode=target_episode,
        title=title,
        target_imdb_id=target_imdb_id,
    )
    if not usable:
        return []
    # _filter_streams_by_title removed — IMDb ID + episode filter are sufficient
    # Apply language filter
    usable = filter_streams_by_language(usable, preferred_languages=preferred_languages)
    if not usable:
        return []
    # Sort by quality descending
    usable.sort(key=_quality_sort_key)
    return usable[:20]  # cap at 20 to avoid too many attempts


def build_torrent_proxy_url(proxy_base_url: str, stream: StreamInfo) -> str | None:
    """Build a local torrent proxy URL from a Stremio info-hash stream.

    Stremio addons such as TorrentsDB return `sources` containing tracker and
    DHT entries. Local Stremio-compatible torrent proxies need these as repeated
    `tr=` query parameters; an info hash alone may not discover peers.
    """
    if not stream.info_hash:
        return None

    base = proxy_base_url.rstrip("/")
    file_part = f"/{stream.file_idx}" if stream.file_idx is not None else ""
    url = f"{base}/{stream.info_hash}{file_part}"

    # Extract tracker/DHT sources from the stream
    trackers = [
        source
        for source in (stream.sources or [])
        if isinstance(source, str) and (source.startswith("tracker:") or source.startswith("dht:"))
    ]

    # Fallback: if addon didn't provide trackers, use common public trackers
    if not trackers:
        trackers = [
            "tracker:udp://tracker.opentrackr.org:1337/announce",
            "tracker:udp://open.stealth.si:80/announce",
            "tracker:udp://tracker.openbittorrent.com:6969/announce",
            "tracker:udp://tracker.torrent.eu.org:451/announce",
            "tracker:udp://exodus.desync.com:6969/announce",
            "tracker:udp://tracker.tiny-vps.com:6969/announce",
            "tracker:udp://tracker.internetwarriors.net:1337/announce",
            "dht:opentrackr.org",
        ]

    if trackers:
        url = f"{url}?{urlencode([('tr', source) for source in trackers])}"

    return url


def resolve_stream_download_url(stream: StreamInfo) -> str | None:
    """Resolve a Stremio stream into a direct download URL when possible.

    Resolution order:
      1. Direct stream.url (if not an RD proxy)
      2. RD proxy URL → resolve_real_debrid_proxy_url
      3. info_hash + TORRENT_PROXY_URL → local proxy quick path
      4. info_hash + REAL_DEBRID_API_KEY → full RD API (slow)
    """
    download_url = stream.url

    if download_url and (
        download_url.startswith(RD_PROXY_PREFIX)
        or _RD_DIRECT_PREFIX in download_url
    ):
        download_url = resolve_real_debrid_proxy_url(download_url)

    if stream.info_hash and not download_url:
        # Fast path: try local torrent proxy if configured. The proxy needs the
        # original Stremio tracker sources; without them it may not find peers.
        if settings.TORRENT_PROXY_URL:
            download_url = build_torrent_proxy_url(settings.TORRENT_PROXY_URL, stream)

        # Slow path: full RealDebrid API flow
        if not download_url and settings.REAL_DEBRID_API_KEY:
            download_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)

    return download_url


def resolve_real_debrid_proxy_url(download_url: str) -> str | None:
    """Resolve Torrentio RealDebrid proxy redirects.
    Returns None if the redirect leads to a Torrentio error page."""
    try:
        response = httpx.get(
            download_url,
            timeout=10,
            follow_redirects=False,
            headers={"User-Agent": "Stremio/4.4.168"},
        )
        if response.status_code in (301, 302, 303, 307, 308):
            resolved_url = response.headers.get("location", "")
            # Torrentio returns redirects to its own error pages when content
            # is unavailable — these start with the torrentio domain and
            # contain '/videos/failed' or '/videos/error', or are known
            # error filenames like failed_access_v2.mp4
            if "torrentio" in resolved_url.lower() and "/videos/" in resolved_url:
                return None
            # Check resolved URL for known error video filenames
            resolved_lower = resolved_url.lower()
            if any(err_vid in resolved_lower for err_vid in _KNOWN_ERROR_VIDEOS):
                return None
            return resolved_url
    except Exception as e:
        from py_stremio.components.errors.error_logger import log_error

        log_error("resolve_rd_proxy", e, download_url)
    return None


def build_media_filename(
    title: str,
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
) -> str:
    """Build the output filename for a movie or episode."""
    if season:
        filename = f"{title}_s{season:02d}e{episode:02d}.mkv"
    else:
        filename = f"{title}.mkv"

    if folder_path:
        return f"{folder_path}/{filename}"
    return filename


def _total_size_from_headers(headers: httpx.Headers, existing_size: int) -> int:
    content_range = headers.get("content-range") or headers.get("Content-Range")
    if content_range and "/" in content_range:
        total_text = content_range.rsplit("/", 1)[-1]
        if total_text.isdigit():
            return int(total_text)

    content_length = headers.get("content-length") or headers.get("Content-Length")
    if content_length and content_length.isdigit():
        return existing_size + int(content_length)
    return 0


def _minimum_completed_video_bytes() -> int:
    return max(0, getattr(settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 100)) * 1024 * 1024


def _content_type(headers: httpx.Headers) -> str:
    return (headers.get("content-type") or headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()


def _delete_invalid_download(file_path, partial_path) -> None:
    file_path.unlink(missing_ok=True)
    partial_path.unlink(missing_ok=True)


def _validate_response_before_download(response, file_path, partial_path, total_size: int) -> None:
    """Reject known non-video placeholder/error responses before writing bytes."""
    content_type = _content_type(response.headers)
    if content_type in _TEXT_ERROR_CONTENT_TYPES:
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Resolved stream returned {content_type or 'non-video'} content, not a video"
        )

    min_bytes = _minimum_completed_video_bytes()
    if min_bytes > 0 and total_size and total_size < min_bytes:
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Resolved stream is only {total_size} bytes "
            f"(min {min_bytes} bytes for a complete video)"
        )


def _validate_completed_file(file_path, partial_path) -> None:
    actual_size = file_path.stat().st_size
    min_bytes = _minimum_completed_video_bytes()
    if min_bytes > 0 and actual_size < min_bytes:
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Downloaded file is only {actual_size} bytes "
            f"(min {min_bytes} bytes for a complete video)"
        )


def download_stream_to_file(
    download_url: str,
    filename: str,
    complete_message: str = "",
    progress_callback=None,
    bandwidth_limiter=None,
    thread_id: int | None = None,
) -> None:
    """Download a direct stream URL to disk, resuming partial files when possible."""
    from pathlib import Path
    import threading

    file_path = Path(filename)
    partial_path = file_path.with_name(f"{file_path.name}.part")
    existing_size = partial_path.stat().st_size if partial_path.exists() else 0
    headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
    active_thread_id = thread_id if thread_id is not None else threading.get_ident()
    registered_here = False

    if bandwidth_limiter and hasattr(bandwidth_limiter, "register_thread"):
        is_registered = False
        if hasattr(bandwidth_limiter, "is_thread_registered"):
            is_registered = bandwidth_limiter.is_thread_registered(active_thread_id)
        if not is_registered:
            bandwidth_limiter.register_thread(active_thread_id)
            registered_here = True

    try:
        with httpx.stream("GET", download_url, timeout=300, headers=headers, follow_redirects=True) as response:
            response.raise_for_status()
            resumed = bool(existing_size and response.status_code == 206)
            mode = "ab" if resumed else "wb"
            downloaded = existing_size if resumed else 0
            total_size = _total_size_from_headers(response.headers, downloaded)
            _validate_response_before_download(response, file_path, partial_path, total_size)

            if progress_callback:
                progress_callback(downloaded, total_size)

            with open(partial_path, mode) as file:
                for chunk in response.iter_bytes(chunk_size=8192):
                    if not chunk:
                        continue
                    if bandwidth_limiter:
                        bandwidth_limiter.wait_for(len(chunk), thread_id=active_thread_id)
                    file.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)
    finally:
        if registered_here and bandwidth_limiter:
            bandwidth_limiter.unregister_thread(active_thread_id)

    partial_path.replace(file_path)
    _validate_completed_file(file_path, partial_path)

    if complete_message:
        print(complete_message, flush=True)


def can_retry_with_debrid(stream: StreamInfo, download_url: str) -> bool:
    """Return True when a failed direct download can be retried via RealDebrid."""
    return bool(
        stream.info_hash
        and settings.REAL_DEBRID_API_KEY
        and not download_url.startswith("magnet:")
    )
