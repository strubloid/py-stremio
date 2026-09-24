"""Post-download subtitle detection and fetch fallback.

Pre-download subtitle filtering (``filter_for_english_subtitles`` and
friends) only inspects the structured ``subtitles`` array that the
Stremio addon returns alongside the stream. That works for clean
releases that advertise their tracks, but fails for the common case
where a torrent carries only a non-English audio/subtitle pair with no
track metadata — e.g. a raw Japanese-only release of *One Piece*.

This module is the safety net: after a successful download we ask
``ffprobe`` what subtitle tracks are actually embedded in the file, and
if the requested language is missing we query a Stremio subtitle addon
(OpenSubtitles v3) and save a ``.srt`` next to the video.

The feature is gated by the global ``DOWNLOAD_MISSING_SUBTITUTES``
setting (default true) and the per-folder ``subtitles`` field
(``"off"`` / ``"none"`` opt out, ``"english"`` is the default).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import httpx

from py_stremio.components.errors import report_error


# Stremio subtitle addon endpoints, tried in order. OpenSubtitles v3
# (``opensubtitles-v3.strem.io``) is the most widely deployed and
# returns ``lang`` as a 3-letter ISO 639-2 code (``eng``, ``spa``, …)
# which lines up with what ffprobe reports in the ``language`` tag.
_SUBTITLE_ADDON_URLS: tuple[str, ...] = (
    "https://opensubtitles-v3.strem.io",
    "https://opensubtitles.stremio.homes",
)

_FFPROBE_TIMEOUT = 30.0
_HTTP_TIMEOUT = 15.0
_DOWNLOAD_TIMEOUT = 60.0
# Anything smaller than this is not a real subtitle file — protects
# against ``200 OK`` HTML error pages being saved as ``.srt``.
_MIN_SUBTITLE_BYTES = 32


# Module-level hooks so tests can replace ffprobe / httpx without
# monkey-patching the imported names. The defaults look up the system
# binaries on every call so the test double can override them once.
_ffprobe_runner = subprocess.run
_http_get = httpx.get


def _language_aliases(language: str) -> tuple[str, ...]:
    """Normalize a user-facing language label to all the codes that
    ffprobe / OpenSubtitles might emit.

    ``english`` -> ``("english", "eng", "en")`` so a request for
    ``english`` matches ffprobe's ``eng`` ISO 639-2 code and any addon
    that returns either ``eng`` or ``en``.
    """
    normalized = (language or "").strip().lower()
    if not normalized:
        return ()
    aliases = {normalized, normalized[:2], normalized[:3]}
    # Common full-name → ISO 639-2 mappings for the languages py-stremio
    # users actually request.
    full_to_iso = {
        "english": ("eng",),
        "spanish": ("spa",),
        "french": ("fra", "fre"),
        "german": ("deu", "ger"),
        "italian": ("ita",),
        "portuguese": ("por",),
        "japanese": ("jpn",),
        "korean": ("kor",),
        "chinese": ("zho", "chi"),
        "arabic": ("ara",),
        "russian": ("rus",),
        "dutch": ("nld", "dut"),
        "polish": ("pol",),
        "turkish": ("tur",),
        "hindi": ("hin",),
    }
    aliases.update(full_to_iso.get(normalized, ()))
    return tuple(aliases)


def detect_subtitle_languages(file_path: Path) -> set[str]:
    """Return the set of ISO 639-2 language codes for every embedded
    subtitle stream in *file_path*.

    Returns an empty set when the file has no subtitle tracks, when
    ffprobe is unavailable, or when ffprobe times out. Errors are
    swallowed silently because a missing ffprobe / corrupt file must
    not block the download path that already succeeded.
    """
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        return set()

    try:
        result = _ffprobe_runner(
            [
                ffprobe_path,
                "-v", "error",
                "-select_streams", "s",
                "-show_entries", "stream_tags=language",
                "-of", "json",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=_FFPROBE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()

    if result.returncode != 0:
        return set()

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return set()

    languages: set[str] = set()
    for stream in data.get("streams") or []:
        tags = stream.get("tags") or {}
        lang = tags.get("language")
        if isinstance(lang, str) and lang:
            languages.add(lang.strip().lower())
    return languages


def _build_subtitle_query_id(
    imdb_id: str | None,
    title: str,
    season: int | None,
    episode: int | None,
) -> tuple[str, str] | None:
    """Return (content_type, stremio_id) for the OpenSubtitles endpoint.

    Returns ``None`` when neither an IMDB ID nor a title is available —
    the addon requires at least one of them.
    """
    from py_stremio.components.stremio.stremio_ids import build_stremio_id

    if not imdb_id and not title:
        return None
    stremio_id = build_stremio_id(imdb_id, title, season, episode)
    if season is not None and episode is not None:
        content_type = "series"
    else:
        content_type = "movie"
    return content_type, stremio_id


def fetch_subtitle_url(
    content_type: str,
    stremio_id: str,
    language_aliases: Iterable[str],
    *,
    addon_urls: tuple[str, ...] = _SUBTITLE_ADDON_URLS,
) -> tuple[str | None, str]:
    """Query subtitle addons for a download URL matching *language_aliases*.

    Returns ``(url, addon_base)``. ``url`` is the first matching
    subtitle download URL, or ``None`` when nothing was found across
    every addon. ``addon_base`` is the addon that actually returned it
    (empty string when nothing was found), useful for logging.
    """
    aliases = {a.lower() for a in language_aliases if a}
    if not aliases:
        return None, ""

    for base in addon_urls:
        url = f"{base.rstrip('/')}/subtitles/{content_type}/{stremio_id}.json"
        try:
            response = _http_get(url, timeout=_HTTP_TIMEOUT, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            report_error(
                context=f"fetch_subtitle_url({base.split('//')[-1].split('/')[0]})",
                exception=exc,
                url=url,
            )
            continue
        for entry in payload.get("subtitles") or []:
            if not isinstance(entry, dict):
                continue
            lang = str(entry.get("lang") or "").strip().lower()
            if lang and any(lang == alias or lang.startswith(alias) for alias in aliases):
                sub_url = entry.get("url")
                if isinstance(sub_url, str) and sub_url:
                    return sub_url, base
    return None, ""


def download_subtitle_bytes(subtitle_url: str) -> bytes | None:
    """Download the subtitle file at *subtitle_url* into memory.

    Returns ``None`` on any HTTP error, on a non-2xx response, or when
    the body is implausibly small (< ``_MIN_SUBTITLE_BYTES``). The size
    guard stops ``200 OK`` HTML error pages from being saved as
    ``.srt``.
    """
    try:
        response = _http_get(subtitle_url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        report_error(
            context="download_subtitle_bytes",
            exception=exc,
            url=subtitle_url,
        )
        return None
    data = response.content
    if not data or len(data) < _MIN_SUBTITLE_BYTES:
        return None
    return data


def _subtitle_target_path(file_path: Path, language: str) -> Path:
    """Return the sidecar ``.srt`` path for *file_path*.

    Uses the 2-letter ISO 639-1 prefix of the requested language so the
    file is recognised by every media player (``foo.mkv`` →
    ``foo.eng.srt`` / ``foo.spa.srt`` / ``foo.jpn.srt``).
    """
    lang = language.strip().lower()
    suffix = lang[:2] if lang else "sub"
    return file_path.with_name(f"{file_path.stem}.{suffix}.srt")


def _requested_language_is_disabled(language: str | None) -> bool:
    """True when the folder-level ``subtitles`` field opts out."""
    if not language:
        return False
    return language.strip().lower() in {"off", "none", "false", "no", "0", "disable", "disabled"}


def ensure_subtitle_for_downloaded_file(
    file_path: Path,
    *,
    imdb_id: str | None,
    title: str,
    season: int | None,
    episode: int | None,
    requested_language: str | None,
) -> Path | None:
    """Top-level entry point: ffprobe the file, fetch a missing language.

    Returns the saved ``.srt`` path when a subtitle was downloaded,
    ``None`` when:
      * the global ``DOWNLOAD_MISSING_SUBTITUTES`` setting is off,
      * the per-folder ``subtitles`` value is ``off``/``none``,
      * no language was requested,
      * the requested language is already embedded, or
      * the addon query / download failed (errors are reported
        through ``report_error`` but never raised).
    """
    from py_stremio.components.configs.app_settings import settings

    if not getattr(settings, "DOWNLOAD_MISSING_SUBTITUTES", True):
        return None
    if _requested_language_is_disabled(requested_language):
        return None
    if not requested_language:
        return None
    if not file_path.exists():
        return None

    aliases = _language_aliases(requested_language)
    if not aliases:
        return None

    embedded = detect_subtitle_languages(file_path)
    if any(alias in embedded for alias in aliases):
        return None

    ids = _build_subtitle_query_id(imdb_id, title, season, episode)
    if not ids:
        return None
    content_type, stremio_id = ids

    sub_url, addon_base = fetch_subtitle_url(content_type, stremio_id, aliases)
    if not sub_url:
        return None

    data = download_subtitle_bytes(sub_url)
    if not data:
        return None

    target = _subtitle_target_path(file_path, requested_language)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        report_error(
            context=f"save_subtitle({target.name})",
            exception=exc,
            url=str(target),
        )
        return None
    return target


__all__ = [
    "detect_subtitle_languages",
    "download_subtitle_bytes",
    "ensure_subtitle_for_downloaded_file",
    "fetch_subtitle_url",
    "_language_aliases",
    "_subtitle_target_path",
]
