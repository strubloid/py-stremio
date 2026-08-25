"""Stream URL resolving and file download helpers."""
from urllib.parse import urlencode

import time

import httpx

import re

from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.debrid.real_debrid_client import resolve_torrent_with_debrid
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.stremio.stremio_url import unique_manifest_urls
from py_stremio.utils.cancellation import raise_if_shutdown_requested

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


class StreamStallError(RuntimeError):
    """Raised when a download receives no bytes for longer than the stall timeout.

    Distinct from a transport error so callers can recognise the cause
    and apply the right retry policy (e.g. fall through to the next
    stream instead of the same proxy on the next retry round).
    """


class RangeNotSupportedError(RuntimeError):
    """Raised when a source ignores a range request for a preserved partial file."""


_TEXT_ERROR_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/json",
    "application/xml",
    "text/xml",
)

# Language keyword patterns for stream title filtering.
# Keep short codes token-bound so e.g. "legend" does not imply ENG.
# Anime-specific markers (VOSTFR, VOSTEN, ITA, etc.) are included for
# scene/fansub releases where the subtitle language is not otherwise stated.
_LANGUAGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\benglish\b", re.IGNORECASE), "english"),
    (re.compile(r"(?:^|[^a-z0-9])eng(?:lish)?(?:$|[^a-z0-9])", re.IGNORECASE), "english"),
    (re.compile(r"\bvosten\b", re.IGNORECASE), "english"),
    (re.compile(r"\brussian\b", re.IGNORECASE), "russian"),
    (re.compile(r"\bрус(?:ский|ская|ское|ские)?\b", re.IGNORECASE), "russian"),
    (re.compile(r"\brusskiy\b", re.IGNORECASE), "russian"),
    (re.compile(r"(?:^|[^a-z0-9])rus(?:$|[^a-z0-9])", re.IGNORECASE), "russian"),
    (re.compile(r"\brudub\b", re.IGNORECASE), "russian"),
    (re.compile(r"\bspanish\b", re.IGNORECASE), "spanish"),
    (re.compile(r"\bespañol\b", re.IGNORECASE), "spanish"),
    (re.compile(r"\bespanol\b", re.IGNORECASE), "spanish"),
    (re.compile(r"(?:^|[^a-z0-9])spa?(?:nish)?(?:$|[^a-z0-9])", re.IGNORECASE), "spanish"),
    (re.compile(r"\bfrench\b", re.IGNORECASE), "french"),
    (re.compile(r"\bfrançais\b", re.IGNORECASE), "french"),
    (re.compile(r"\bfrancais\b", re.IGNORECASE), "french"),
    (re.compile(r"\bvostfr\b", re.IGNORECASE), "french"),
    (re.compile(r"(?:^|[^a-z0-9])fra?(?:nch|is)?(?:$|[^a-z0-9])", re.IGNORECASE), "french"),
    (re.compile(r"\bgerman\b", re.IGNORECASE), "german"),
    (re.compile(r"\bdeutsch\b", re.IGNORECASE), "german"),
    (re.compile(r"(?:^|[^a-z0-9])ger(?:$|[^a-z0-9])", re.IGNORECASE), "german"),
    (re.compile(r"\bitalian\b", re.IGNORECASE), "italian"),
    (re.compile(r"\bitaliano\b", re.IGNORECASE), "italian"),
    (re.compile(r"(?:^|[^a-z0-9])ita(?:$|[^a-z0-9])", re.IGNORECASE), "italian"),
    (re.compile(r"\bsubit\b", re.IGNORECASE), "italian"),
    (re.compile(r"\bportuguese\b", re.IGNORECASE), "portuguese"),
    (re.compile(r"\bportuguês\b", re.IGNORECASE), "portuguese"),
    (re.compile(r"\bportugues\b", re.IGNORECASE), "portuguese"),
    (re.compile(r"(?:^|[^a-z0-9])por?t?(?:uguese)?(?:$|[^a-z0-9])", re.IGNORECASE), "portuguese"),
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
    """Return True unless the stream text contains a contradicting S/E token.

    A stream is accepted when:
      - its text contains the requested S/E token, OR
      - its text contains a season-only token (``s23``) when no
        episode token is present (season packs), OR
      - its text has no S/E token AND no finished-release markers
        (info-hash-only addons whose text is just an addon/quality
        label like ``"CIN 4K"``).

    A stream whose text contains finished-release markers (year,
    resolution, format keywords) but no matching S/E is rejected, since
    it is clearly a different release.
    """
    if target_season is None or target_episode is None:
        return True
    text = _combined_stream_text(stream)
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    season = int(target_season)
    episode = int(target_episode)
    target_tokens = {
        f"s{season:02d}e{episode:02d}",
        f"s{season}e{episode:02d}",
        f"s{season:02d}e{episode}",
        f"season{season}episode{episode}",
    }
    season_only = f"s{season:02d}"
    any_se = re.findall(r"s\d{1,2}e\d{1,2}", compact)
    has_any_se_token = bool(any_se)
    has_matching_token = any(token in compact for token in target_tokens)
    has_matching_season_only = season_only in compact and not has_any_se_token
    if has_matching_token or has_matching_season_only:
        return True
    # No S/E token in text — only safe to accept when the text lacks
    # finished-release markers.  If it has a year, a resolution token,
    # or a release-format keyword, it is clearly a different release
    # and must be rejected.
    if not has_any_se_token:
        return not _looks_like_finished_release(text)
    # S/E token in text but none match — contradicting episode, reject.
    return False


# Markers that, when all present together, indicate the text is a
# finished release (movie, full show pack, standalone episode pack)
# rather than an info-hash label.  We require multiple signals to
# coexist — a single codec or audio marker is not enough, since
# info-hash-only addons often include those as torrent description
# flavor in the title without any show-name or S/E information.
_FINISHED_RELEASE_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_FINISHED_RELEASE_RESOLUTION = re.compile(r"\b(480|720|1080|2160|1440|4320)p\b", re.I)
_FINISHED_RELEASE_FORMAT = re.compile(
    r"\b(bluray|blu-ray|bd-?rip|brrip|web-?dl|web-?rip|hdrip|dvdrip|hdtv|pdtv|remux|complete)\b",
    re.I,
)
_FINISHED_RELEASE_KEYWORDS = re.compile(
    r"\b(movie|ova|special|collection|trilogy|extended|remastered|criterion|theatrical|uncut|repack|proper|internal)\b",
    re.I,
)


def _looks_like_finished_release(text: str) -> bool:
    """Return True when *text* contains markers typical of a finished release.

    A finished release typically pairs a release year with a resolution
    and a format keyword.  We require at least two of the four
    marker groups to fire so that info-hash-only addons (which often
    include a single codec or audio token as torrent description
    flavor) are not misclassified as finished releases.
    """
    if not text:
        return False
    signals = 0
    if _FINISHED_RELEASE_YEAR.search(text):
        signals += 1
    if _FINISHED_RELEASE_RESOLUTION.search(text):
        signals += 1
    if _FINISHED_RELEASE_FORMAT.search(text):
        signals += 1
    if _FINISHED_RELEASE_KEYWORDS.search(text):
        signals += 1
    return signals >= 2

# Title matching is intentionally conservative: release names must contain the
# requested show title after separator normalization. This blocks cross-show
# leakage from loose title-based addon searches before any download starts.


def _normalized_title_text(text: str) -> str:
    # Scene releases use dots, while library titles commonly contain colons,
    # apostrophes, question marks, and other punctuation.  Treat all
    # non-word separators alike before comparing titles so e.g.
    # "Fiancé: The Other Way" matches "Fiance.The.Other.Way".
    return re.sub(r"[^\w]+", " ", text.lower(), flags=re.UNICODE).strip()


def _strip_accents(text: str) -> str:
    """Remove diacritics (combining marks) from *text*.

    Most scene torrent releases drop accents from foreign-language
    words in their release names — ``"Fiancé"`` becomes ``"Fiance"``,
    ``"Pokémon"`` becomes ``"Pokemon"``.  A user-supplied folder
    title that keeps the original accent must still match these
    unaccented release names, otherwise the title check will
    silently reject every legitimate stream for the show.
    """
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Tokens that are pure addon labels, quality/resolution markers, or
# generic descriptors — never show titles.  When a stream's release
# text contains ONLY these (and no recognizable show-name words) it
# has no title signal to evaluate, so the show-title check should
# pass and the episode-number check becomes authoritative.  This is
# what allows info-hash-only addons like CIN (whose name is just
# ``"CIN 4K"``) to reach the episode filter.
_NON_TITLE_TOKENS = {
    "4k", "8k", "1080p", "720p", "480p", "2160p", "1440p",
    "bluray", "blu", "ray", "web", "dl", "webrip", "web-dl",
    "hdrip", "dvdrip", "brrip", "hdtv", "pdtv", "cam", "ts",
    "x264", "x265", "h264", "h265", "h265", "h", "265", "264",
    "aac", "ac3", "dts", "truehd", "atmos", "opus", "mp3",
    "remux", "uhd", "hdr", "hdr10", "dv", "hdr10plus", "hlg",
    "10bit", "8bit", "hevc", "avc", "k", "x", "gb", "mb",
    "multi", "audio", "subs", "sub", "dub", "dubbed",
    "proper", "repack", "internal", "extended", "theatrical",
    "imax", "directors", "cut", "version",
    "cin", "rd", "torrentio", "torrent", "stream", "addon",
    "amazon", "netflix", "hulu", "disney", "hbo", "max",
    "torrent", "gb", "mb",
    # Common torrent release-group names.  These are technical
    # metadata, never show titles, and are frequently appended to
    # addon info-hash descriptions (MeGusta, EDITH, TRB, Kitsune,
    # RARBG, YIFY, EVO, NTb, PSA, CtrlHD, ...).  Keeping them out
    # of the title-signal set prevents streams like CIN's
    # "CIN 1080p ... 🛠 MeGusta" from being treated as having a
    # title signal just because the release-group token is alphabetic.
    "megusta", "edith", "trb", "kitsune", "rarbg", "yify", "evo",
    "ntb", "psa", "ctrlhd", "rovers", "fov", "dimension", "killers",
    "lol", "asap", "fleet", "sva", "exporthd", "bajskorv", "bia",
    "cmrg", "ntb", "rmteam", "yestv", "eztv", "torrentgalaxy",
    "tgx", "deflate", "inflate", "sigma", "xrg", "honey", "sir",
    "ion10", "roversweb", "playhd", "playweb", "psa", "w4f", "web",
    "edith", "robin", "morc", "noir", "dna", "orbit", "luminous",
    "crimson", "archie", "morpheus", "public", "ski", "dm", "dvd",
    "blu", "ray", "complete", "final", "alt", "ext", "int",
}


def _has_show_title_signal(normalized_text: str) -> bool:
    """Return True when the text contains at least one alphabetic token
    that is not a pure quality/resolution/format descriptor.
    """
    if not normalized_text:
        return False
    # Strip digits and quality-suffix noise so "1080p" becomes "" and
    # "4k" becomes "k" (which is in _NON_TITLE_TOKENS).  This avoids
    # false-positive title signals from pure technical markers.
    cleaned = re.sub(r"\d+[a-z]*", " ", normalized_text)
    tokens = re.findall(r"[a-z]+", cleaned)
    return any(token not in _NON_TITLE_TOKENS for token in tokens)


def _matches_show_title(stream, title: str | None) -> bool:
    """Return True unless the stream text names a different show.

    Symmetric with ``_matches_target_episode``: a stream is rejected
    only when it has positive evidence of being the wrong content.
    Here, "positive evidence" means the text contains a show-name-like
    word that disagrees with the requested title.  Streams whose text
    has no title signal at all (info-hash-only addons, release-group
    names, codec/quality markers, generic addon labels like ``"CIN
    4K"``) are passed through — the episode check is the authoritative
    filter for those.

    The previous asymmetric design — "stream must contain the target
    show name" — over-matched addon labels, codec tokens, and release
    group names (MeGusta, EDITH, etc.) as title signals, causing it
    to incorrectly reject legitimate info-hash streams that simply
    lacked an in-text show identifier.

    Title comparison is diacritics-insensitive: ``"90 Day Fiancé"`` in
    the user's folder config matches ``"90 Day Fiance"`` in the
    torrent release name.  Most scene releases drop accents from
    foreign-language words, and rejecting the stream because of a
    missing accent would cause the title check to silently fail for
    any accented show.
    """
    if not title:
        return True
    combined_norm = _normalized_title_text(_combined_stream_text(stream))
    if not _has_show_title_signal(combined_norm):
        # No recognisable show-name word in the text.  Treat as
        # "no title signal" and defer to the episode check.
        return True
    # Collapse any multi-space whitespace from the user's title config
    # to a single space, then strip accents.  This makes "90  Day
    # Fiance" (double space) and "90 Day Fiancé" (with accent) both
    # match the unaccented, single-spaced release name.
    title_norm = _strip_accents(re.sub(r"\s+", " ", _normalized_title_text(title)))
    combined_norm = _strip_accents(re.sub(r"\s+", " ", combined_norm))
    return title_norm in combined_norm


def _stream_has_target_identity_mismatch(
    stream,
    target_season: int | None = None,
    target_episode: int | None = None,
    title: str | None = None,
    target_imdb_id: str | None = None,
) -> bool:
    """Return True when a stream explicitly points at different content.

    This is intentionally stricter than normal filtering for blacklisting: an
    addon is considered bad when it returns an explicit wrong IMDB ID, or when
    it returns the requested S/E number under a different show title. Streams
    with no recognizable show-name signal (info-hash-only addons whose text is
    just the addon/quality label) are not blacklisted — the episode-number
    match is the only available signal for those, and a match there means the
    torrent is plausibly the requested episode.
    """
    if _is_advisory_stream(stream):
        return False
    stream_imdb = getattr(stream, "imdb_id", None)
    if target_imdb_id and stream_imdb and stream_imdb != target_imdb_id:
        return True
    if title and _matches_target_episode(stream, target_season, target_episode):
        return not _matches_show_title(stream, title)
    return False


def target_mismatch_addon_urls(
    streams: list,
    target_season: int | None = None,
    target_episode: int | None = None,
    title: str | None = None,
    target_imdb_id: str | None = None,
) -> list[str]:
    """Return addon URLs that supplied streams for the wrong target media."""
    urls = []
    for stream in streams:
        if not (getattr(stream, "url", None) or getattr(stream, "info_hash", None)):
            continue
        if _stream_has_target_identity_mismatch(
            stream,
            target_season=target_season,
            target_episode=target_episode,
            title=title,
            target_imdb_id=target_imdb_id,
        ):
            urls.append(getattr(stream, "addon_url", None))
    return unique_manifest_urls(urls)


def _filter_streams_by_target_episode(
    streams: list,
    target_season: int | None = None,
    target_episode: int | None = None,
    title: str | None = None,
    target_imdb_id: str | None = None,
) -> list:
    """Filter streams by show identity and target episode.

    A stream is kept when BOTH checks pass:
      - show-title: stream text names the requested show, OR has no
        title signal at all (info-hash-only addons like CIN whose text
        is a generic label such as ``"CIN 4K"``)
      - episode-number: stream text contains the requested S/E token,
        OR has no S/E token in its text (incomplete metadata)

    Both checks failing for the same stream means we have positive
    evidence it is the wrong content (e.g. ``Random.S01E01`` for a
    One Piece S1E1 request), and the stream is rejected. Advisory
    (non-video) streams are always rejected. IMDB ID disagreement is
    a hard reject.
    """
    filtered = []
    for stream in streams:
        if _is_advisory_stream(stream):
            continue
        stream_imdb = getattr(stream, "imdb_id", None)
        if target_imdb_id and stream_imdb and stream_imdb != target_imdb_id:
            continue
        if not _matches_show_title(stream, title):
            continue
        if not _matches_target_episode(stream, target_season, target_episode):
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


def _stream_subtitle_language_codes(stream) -> set[str]:
    """Extract language codes from a stream's structured subtitle tracks.

    Normalizes the Stremio ``flag`` and ``label`` fields into a set of
    canonical lowercase language names so callers can check for English
    presence without caring about the addon's exact encoding.
    """
    tracks = getattr(stream, "subtitle_tracks", None) or []
    codes: set[str] = set()
    for track in tracks:
        flag = str(track.get("flag") or "").strip().lower()
        label = str(track.get("label") or "").strip().lower()
        canonical = _SUBTITLE_FLAG_TO_LANGUAGE.get(flag)
        if canonical:
            codes.add(canonical)
        elif "english" in label or "eng" in flag:
            codes.add("english")
        elif "french" in label or "fra" in flag or "fre" in flag:
            codes.add("french")
        elif "spanish" in label or "spa" in flag:
            codes.add("spanish")
        elif "italian" in label or "ita" in flag:
            codes.add("italian")
        elif "german" in label or "deu" in flag or "ger" in flag:
            codes.add("german")
        elif "portuguese" in label or "por" in flag:
            codes.add("portuguese")
        elif "russian" in label or "rus" in flag:
            codes.add("russian")
        elif "japanese" in label or "jpn" in flag:
            codes.add("japanese")
        elif "korean" in label or "kor" in flag:
            codes.add("korean")
        elif "chinese" in label or "zho" in flag or "chi" in flag:
            codes.add("chinese")
        elif "arabic" in label or "ara" in flag:
            codes.add("arabic")
        elif "hindi" in label or "hin" in flag:
            codes.add("hindi")
    return codes


_SUBTITLE_FLAG_TO_LANGUAGE: dict[str, str] = {
    "eng": "english",
    "fra": "french",
    "fre": "french",
    "spa": "spanish",
    "ita": "italian",
    "deu": "german",
    "ger": "german",
    "por": "portuguese",
    "rus": "russian",
    "jpn": "japanese",
    "kor": "korean",
    "zho": "chinese",
    "chi": "chinese",
    "ara": "arabic",
    "hin": "hindi",
}


def has_english_subtitle(stream) -> bool:
    """Return True when a stream has English subtitle support.

    Checks three signals in order:
      1. Structured subtitle tracks from the Stremio addon response
      2. English indicators in the release name / stream title
      3. Multi-language markers (dual audio, multi subs)

    Streams with no detectable language info are accepted (safe default)
    so that valid English streams whose release name omits the language
    marker are not silently dropped.
    """
    title = getattr(stream, "title", None) or ""
    name = getattr(stream, "name", None) or ""
    filename = getattr(stream, "filename", None) or ""
    combined = f"{title} {name} {filename}"

    # 1. Structured subtitle tracks (most reliable when present)
    subtitle_codes = _stream_subtitle_language_codes(stream)
    if "english" in subtitle_codes:
        return True

    # 2. Release-name language detection
    detected = _detect_languages(combined)
    if "english" in detected:
        return True

    # 3. Multi-language indicators → accept (may include English)
    if "multi" in detected:
        return True

    # 4. No language info detected → safe default, accept
    if not detected and not subtitle_codes:
        return True

    # 5. Only non-English, non-multi languages detected → reject
    return False


def filter_for_english_subtitles(streams: list) -> list:
    """Filter streams to those with English subtitle support.

    Streams that have English in their subtitle tracks, English in their
    release name, multi-language markers, or no detectable language info
    at all are kept. Only streams that are positively identified as
    non-English are filtered out.
    """
    return [s for s in streams if has_english_subtitle(s)]


_QUALITY_STRING_SCORES: dict[str, int] = {
    "2160p": 100, "4k": 100, "uhd": 100,
    "1080p": 80, "fhd": 80,
    "720p": 60, "hd": 60,
    "480p": 40, "sd": 40,
    "360p": 20,
}


def _stream_quality_score(stream) -> int | None:
    """Return the numeric quality score of a stream, or None if it cannot be
    detected from the stream's title/filename.

    Only the *title* and *filename* fields are used as quality signals.
    The *name* field is the addon's display label (e.g. ``"CIN 4K"``,
    ``"Torrentio 1080p"``, ``"Comet 720p"``) and reflects the addon's
    own quality category rather than the actual quality of the file
    behind the stream — using it for filtering would falsely reject
    valid streams (CIN's info-hash streams are commonly tagged
    ``"CIN 4K"`` even when the underlying file is 1080p or 720p).

    4K (2160p) is checked before 1080p/720p so its marker is never
    mis-attributed to a smaller resolution that also happens to contain
    a "1080" or "720" substring.
    """
    title = (getattr(stream, "title", "") or "").lower()
    filename = (getattr(stream, "filename", "") or "").lower()
    haystacks = (title, filename)

    for marker, score in (
        (("2160", "4k", "uhd"), 100),
        (("1080", "fhd"), 80),
        (("720", "hd"), 60),
        (("480", "sd"), 40),
        (("360",), 20),
    ):
        for marker_str in marker:
            if any(marker_str in hay for hay in haystacks):
                return score
    return None


def _quality_string_to_score(quality: str | None) -> int | None:
    """Map a configured quality string like ``"1080p"`` to its numeric score."""
    if not quality:
        return None
    return _QUALITY_STRING_SCORES.get(quality.strip().lower())


def _build_quality_priority(
    preferred_quality: str | None,
    fallbacks: list[str] | None,
) -> list[int]:
    """Build a deduplicated list of quality scores in preference order:
    preferred first, then fallbacks in the order given.
    """
    priority: list[int] = []
    preferred_score = _quality_string_to_score(preferred_quality)
    if preferred_score is not None:
        priority.append(preferred_score)
    if fallbacks:
        for q in fallbacks:
            score = _quality_string_to_score(q)
            if score is not None and score not in priority:
                priority.append(score)
    return priority


def _quality_priority_rank(stream, priority_scores: list[int]) -> tuple[int, bool]:
    """Return ``(rank, is_unknown)`` for a stream under the given priority list.

    A stream whose score matches an entry in *priority_scores* is ranked by
    its position in that list (0 = best, the preferred quality).  A stream
    whose score is below the lowest allowed quality is given a rank past
    the end of the priority list so it is tried after the configured
    fallbacks.  A stream whose score is above the highest allowed quality
    is given an even larger rank so it is tried last (or filtered out
    entirely by the caller when ``allow_higher`` is False).  A stream
    whose quality cannot be detected is ranked last of all.
    """
    score = _stream_quality_score(stream)
    if score is None:
        return (len(priority_scores) + 2, True)
    if not priority_scores:
        return (0, False)
    try:
        return (priority_scores.index(score), False)
    except ValueError:
        min_score = min(priority_scores)
        max_score = max(priority_scores)
        if score > max_score:
            return (len(priority_scores) + 1, False)
        if score < min_score:
            return (len(priority_scores), False)
        # Between two configured qualities (shouldn't happen with the
        # current discrete buckets, but be defensive).
        return (len(priority_scores), False)


def _quality_sort_key(stream) -> tuple:
    """Sort streams by quality: 4K > 1080p > 720p > 480p > 360p > others.
    Prefers streams with a direct URL over info_hash-only at the same quality.
    Prefers streams with more seeders at the same quality level.

    NOTE: this helper preserves the legacy "always 4K first" behaviour and
    is kept only for callers that have not been migrated to the
    priority-aware ``_quality_priority_sort_key`` below.  New code should
    use ``select_quality_streams`` with the full quality config.
    """
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


def _quality_priority_sort_key(
    stream,
    priority_scores: list[int],
) -> tuple:
    """Sort key that respects the configured quality priority list.

    Streams are first ordered by their position in the priority list
    (preferred first, then fallbacks in order, then below-fallback, then
    above-preferred, then unknown).  Within the same priority bucket,
    the same secondary factors as ``_quality_sort_key`` apply: direct
    URLs over info-hash, Comet/non-Torrentio over Torrentio, then
    seeders.
    """
    rank, _is_unknown = _quality_priority_rank(stream, priority_scores)
    name = (stream.name or "").lower()
    title = (stream.title or "").lower()
    addon = (getattr(stream, "addon_name", "") or "").lower()

    url_bonus = 1 if stream.url else 0
    addon_bonus = 0
    if "comet" in addon:
        addon_bonus = 30
    elif "torrentio" not in addon:
        addon_bonus = 10
    seeders = getattr(stream, "seeders", None) or 0
    return (rank, -url_bonus, -addon_bonus, -seeders)


def select_quality_streams(
    streams: list,
    preferred_quality: str,
    preferred_languages: list[str] | None = None,
    target_season: int | None = None,
    target_episode: int | None = None,
    title: str | None = None,
    target_imdb_id: str | None = None,
    quality_fallbacks: list[str] | None = None,
    allow_higher: bool = False,
    allow_lower: bool = True,
) -> list:
    """Filter out unusable streams, then return all usable ones sorted by the
    configured quality priority (preferred first, then fallbacks in order) so
    the caller can try best first and fall back to lower qualities.

    The priority is built from *preferred_quality* + *quality_fallbacks*
    (the same fields the legacy ``plan_quality_fallback`` uses).  The
    ``allow_higher`` and ``allow_lower`` flags control what happens to
    streams whose quality is outside the configured priority list:

      * ``allow_higher=False`` (the default): streams whose quality is
        *better* than the preferred quality (e.g. 4K when the user
        prefers 1080p) are filtered out entirely.  This is the
        long-standing behaviour of the legacy ``allow_higher`` flag and
        prevents the system from silently picking a 4K release when the
        user explicitly asked for 1080p.
      * ``allow_higher=True``: those streams are kept and tried *after*
        all configured priorities, so a user who has 4K as a last-resort
        fallback still gets 1080p first.
      * ``allow_lower=False``: streams whose quality is *worse* than
        the lowest configured fallback are filtered out.
      * ``allow_lower=True`` (the default): those streams are kept and
        tried after the configured fallbacks.

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

    priority_scores = _build_quality_priority(preferred_quality, quality_fallbacks)
    if priority_scores:
        min_score = min(priority_scores)
        max_score = max(priority_scores)
        filtered: list = []
        for s in usable:
            score = _stream_quality_score(s)
            if score is None:
                # Unknown quality — only keep when we're not filtering
                # strictly; otherwise the user gets nothing.
                if allow_higher or allow_lower:
                    filtered.append(s)
                continue
            if score > max_score and not allow_higher:
                continue
            if score < min_score and not allow_lower:
                continue
            filtered.append(s)
        usable = filtered
        if not usable:
            return []
        usable.sort(key=lambda s: _quality_priority_sort_key(s, priority_scores))
    else:
        # No usable priority list (no preferred + no fallbacks).  Fall
        # back to the legacy quality-descending sort so behaviour is
        # at least sensible in this edge case.
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
        # Meteor results are debrid-backed but expose only an info hash.  Its
        # configured RealDebrid path is more reliable than the optional local
        # torrent proxy, which otherwise turns these usable streams into slow
        # no-peer/proxy retries.
        addon_identity = " ".join(
            str(getattr(stream, field, "") or "")
            for field in ("addon_name", "addon_url")
        ).lower()
        if "meteor" in addon_identity and settings.REAL_DEBRID_API_KEY:
            download_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)

        # Fast path: try local torrent proxy if configured. The proxy needs the
        # original Stremio tracker sources; without them it may not find peers.
        if not download_url and settings.TORRENT_PROXY_URL:
            download_url = build_torrent_proxy_url(settings.TORRENT_PROXY_URL, stream)

        # Slow path: full RealDebrid API flow
        if not download_url and settings.REAL_DEBRID_API_KEY:
            download_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)

    return download_url


def resolve_real_debrid_proxy_url(download_url: str) -> str | None:
    """Resolve Torrentio RealDebrid proxy redirects.
    Returns None if the redirect leads to a Torrentio error page."""
    try:
        raise_if_shutdown_requested()
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
    """Build the output filename for a movie or episode.

    The title is run through :func:`sanitize_filename` so that names
    with characters that are illegal on Windows / NTFS (e.g. ``:``)
    never reach the filesystem. This also keeps the on-disk name in
    agreement with the legacy ``library/series.py`` path which already
    sanitised titles.
    """
    from py_stremio.utils.media import sanitize_filename

    safe_title = sanitize_filename(title or "")
    if season:
        filename = f"{safe_title}_s{season:02d}e{episode:02d}.mkv"
    else:
        filename = f"{safe_title}.mkv"

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
    """Remove the final file but preserve the ``.part`` file.

    The ``.part`` file holds bytes that are still useful for the next
    download attempt: a 1.5 GB partial of a 3 GB episode is not garbage
    the moment a single stream fails — it is the work the user has
    already paid bandwidth for.  Dropping the partial forces the next
    run to restart from zero, which is what motivated the original
    report: "i could see something downloading in a good progress and
    after [failed] ... also lost the last file ... and now it is
    starting from 0".  The same reservation already applies to movies
    (``process_season_folder``'s movie branch and the
    ``RangeNotSupportedError`` path for series); the only paths that
    still called ``_delete_invalid_download`` on the partial were the
    pre-write response check, the read-timeout handler, the
    content-length mismatch check, and the post-rename size check.

    Cases 3 (post-rename too small) and 6 (rename-validation
    exception) have already consumed the ``.part`` via
    ``partial_path.replace(file_path)`` by the time
    ``_delete_invalid_download`` runs, so deleting the partial is a
    no-op there — only the final file needs to come down.
    """
    file_path.unlink(missing_ok=True)
    # The .part file is intentionally left on disk. Callers that have
    # just produced it (download loop) or that want to start over from
    # byte zero should unlink it explicitly; the default policy is
    # "preserve whatever bytes the user has already paid for".


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


def _validate_video_structure(file_path) -> bool:
    """Check if the downloaded video file is structurally valid using ffprobe.

    Reads only the file headers (not the full decoded content), so
    validation is fast even for multi-GB files.  Returns ``True``
    when the file opens cleanly in ffprobe with a positive duration.

    When ffprobe is not available, falls back to basic container
    header checking and logs a warning — files are accepted but the
    user is advised to install ffmpeg for thorough validation.

    Returns:
        True if the file appears structurally sound, False if
        truncated or corrupted.
    """
    import subprocess
    import shutil

    if not getattr(settings, "VALIDATE_DOWNLOAD_STRUCTURE", True):
        return True

    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        # ffprobe not available — log a single warning and pass
        # through so the download is not blocked.
        import warnings as _w

        _w.warn(
            "ffprobe not found on PATH; downloaded files will not be "
            "validated for structural integrity. Install ffmpeg for "
            "automatic download verification (apt install ffmpeg).",
            RuntimeWarning,
            stacklevel=2,
        )
        return True

    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        # Large files on slow I/O — skip validation rather than fail
        return True
    except FileNotFoundError:
        # ffprobe was deleted between the which() check and the run()
        return True
    except OSError:
        # Permission error, filesystem issue, etc.
        return True

    if result.returncode != 0:
        return False

    stderr = result.stderr.strip()
    if stderr:
        return False

    stdout = result.stdout.strip()
    if not stdout:
        return False

    # Validate duration string is non-empty and non-zero
    duration_str = stdout.strip()
    if not duration_str or duration_str == "N/A":
        return False

    # Try to parse duration — if it's valid (> 0), the file is OK
    try:
        duration_s = float(duration_str)
        if duration_s <= 0:
            return False
    except (ValueError, IndexError):
        return False

    return True


def _validate_completed_file(file_path, partial_path, check_structure=False) -> None:
    actual_size = file_path.stat().st_size
    min_bytes = _minimum_completed_video_bytes()
    if min_bytes > 0 and actual_size < min_bytes:
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Downloaded file is only {actual_size} bytes "
            f"(min {min_bytes} bytes for a complete video)"
        )

    if check_structure and not _validate_video_structure(file_path):
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Downloaded file failed structural validation — "
            f"likely truncated or corrupted"
        )


def download_stream_to_file(
    download_url: str,
    filename: str,
    complete_message: str = "",
    progress_callback=None,
    bandwidth_limiter=None,
    thread_id: int | None = None,
    stall_timeout: float = 60.0,
    preserve_partial_on_unsupported_range: bool = True,
    stream: StreamInfo | None = None,
) -> None:
    """Download a direct stream URL to disk, resuming partial files when possible.

    ``stall_timeout`` is the maximum number of seconds to wait between
    consecutive bytes before giving up.  The default is 60s, which is
    generous enough for slow torrents yet short enough to surface a
    "no peers" situation within one minute instead of waiting the full
    5-minute ``httpx`` request timeout.  Pass ``0`` to disable stall
    detection (rely on the request timeout instead).

    When a ``.part`` file already exists and the upstream server does
    NOT honour the ``Range:`` request (returns ``200 OK`` with the full
    body instead of ``206 Partial Content``), the partial bytes would
    be silently discarded. We always raise :class:`RangeNotSupportedError`
    in that case so the caller can fall through to the next stream
    instead of restarting from byte zero. Set
    ``preserve_partial_on_unsupported_range=False`` to opt out of this
    safety and discard the partial anyway (legacy behaviour, useful
    only when the caller has no other streams to try).

    When ``stream`` is provided with ``stream.is_hls=True`` and
    ``download_url`` is an HLS ``.m3u8`` URL, the function delegates
    to ``HlsDownloader``, which resolves the playlist and
    concatenates segments into the output file.  Addons opt in by
    setting ``HLS_CAPABLE = True`` on their class and tagging HLS
    streams with ``is_hls=True`` during ``parse_streams`` (see
    ``HDHubAddon`` for the reference implementation).

    As of the ffmpeg-backed HLS path, the trigger for the HLS branch
    is the URL shape alone: *any* download whose URL ends in
    ``.m3u8`` (or ``.m3u``) is routed through the HLS pipeline
    regardless of which addon returned it.  The ``HLS_DOWNLOAD_METHOD``
    setting picks between the ffmpeg-based downloader
    (``"ffmpeg"`` — the default) and the pure-Python segment-based
    downloader (``"segment"``).
    """
    from pathlib import Path
    import threading

    # HLS fast-path: route .m3u8 streams to the HLS downloader before
    # touching disk state.  Triggered by URL shape alone so that
    # streams returned by sources other than HLS-opt-in addons
    # (RealDebrid's CDN, generic Stremio addons, etc.) still get the
    # playlist-aware treatment.  HLS downloads always start from zero
    # (CDN segments don't support Range), so the .part logic below is
    # intentionally skipped.
    if _is_hls_url(download_url):
        _download_hls_to_file(
            url=download_url,
            filename=filename,
            bandwidth_limiter=bandwidth_limiter,
            thread_id=thread_id,
            progress_callback=progress_callback,
            stall_timeout=stall_timeout,
        )
        if complete_message:
            print(complete_message, flush=True)
        return

    file_path = Path(filename)
    partial_path = file_path.with_name(f"{file_path.name}.part")
    existing_size = partial_path.stat().st_size if partial_path.exists() else 0
    headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
    active_thread_id = thread_id if thread_id is not None else threading.get_ident()
    registered_here = False

    # Track whether the HTTP response body completeness can be verified
    # through protocol means (Content-Length/Range header or chunked
    # encoding with the 0-length terminator). When neither is present,
    # the response body is terminated by connection close, and we
    # cannot tell if the server sent all the data or closed mid-stream.
    # In that case structural validation via ffprobe is needed.
    response_body_known_complete = False
    transfer_encoding = ""

    if bandwidth_limiter and hasattr(bandwidth_limiter, "register_thread"):
        is_registered = False
        if hasattr(bandwidth_limiter, "is_thread_registered"):
            is_registered = bandwidth_limiter.is_thread_registered(active_thread_id)
        if not is_registered:
            bandwidth_limiter.register_thread(active_thread_id)
            registered_here = True

    try:
        # httpx exposes separate ``connect`` and ``read`` timeouts.  The
        # ``read`` timeout is exactly what we need for stall detection:
        # it bounds the gap between consecutive bytes during the body
        # read.  We keep the overall request timeout generous (5 min)
        # and the read timeout much shorter (default 60s) so a stalled
        # proxy aborts within a minute instead of hanging for the full
        # 5 minutes.
        if stall_timeout and stall_timeout > 0:
            request_timeout = httpx.Timeout(300.0, read=stall_timeout)
        else:
            request_timeout = 300.0
        with httpx.stream(
            "GET",
            download_url,
            timeout=request_timeout,
            headers=headers,
            follow_redirects=True,
        ) as response:
            raise_if_shutdown_requested()
            response.raise_for_status()
            # When a partial file exists and the server ignores our
            # Range request, refuse to truncate the partial. The
            # previous code fell through to ``mode = "wb"`` for
            # non-movie content, which silently discarded every byte
            # already on disk and made the user watch the download
            # restart from zero.
            if (
                existing_size
                and response.status_code != 206
                and preserve_partial_on_unsupported_range
            ):
                raise RangeNotSupportedError(
                    f"Source does not support byte-range resume for {file_path.name}; "
                    f"preserving {existing_size} bytes on disk"
                )
            resumed = bool(existing_size and response.status_code == 206)
            mode = "ab" if resumed else "wb"
            downloaded = existing_size if resumed else 0
            total_size = _total_size_from_headers(response.headers, downloaded)

            # Determine if the response body is reliably complete
            transfer_encoding = response.headers.get("transfer-encoding", "").lower()
            response_body_known_complete = (
                total_size > 0 or "chunked" in transfer_encoding
            )

            _validate_response_before_download(response, file_path, partial_path, total_size)

            if progress_callback:
                progress_callback(downloaded, total_size)

            with open(partial_path, mode) as file:
                # ``last_chunk_at`` is the moment the previous chunk
                # was processed. We measure the gap to the moment the
                # current chunk is received (top of the next loop
                # iteration) so a slow trickle of bytes still trips the
                # in-loop stall check.
                last_chunk_at = time.monotonic()
                for chunk in response.iter_bytes(chunk_size=8192):
                    raise_if_shutdown_requested()
                    now = time.monotonic()
                    if (
                        stall_timeout
                        and stall_timeout > 0
                        and downloaded > 0
                        and (now - last_chunk_at) > stall_timeout
                    ):
                        # The gap between the previous chunk and
                        # this one exceeded the stall budget. Bail
                        # out so the next stream gets a turn. We do
                        # NOT delete the .part — the bytes already
                        # written are preserved for the next resume.
                        raise StreamStallError(
                            f"No new bytes for {stall_timeout}s; aborting "
                            f"{file_path.name} (received {downloaded} total)"
                        )
                    if not chunk:
                        # Empty chunk — possible when ``iter_bytes``
                        # signals end-of-stream. Treat it as the
                        # loop terminator and let the trailing
                        # content-length check below decide whether
                        # the partial is valid.
                        if progress_callback:
                            progress_callback(downloaded, total_size)
                        break
                    if bandwidth_limiter:
                        bandwidth_limiter.wait_for(len(chunk), thread_id=active_thread_id)
                    raise_if_shutdown_requested()
                    file.write(chunk)
                    downloaded += len(chunk)
                    last_chunk_at = time.monotonic()
                    if progress_callback:
                        progress_callback(downloaded, total_size)
    except httpx.ReadTimeout as e:
        # The body stalled for longer than the read timeout.  Translate
        # to our domain-specific error so the caller can apply the
        # correct retry policy (fall through to the next stream
        # instead of retrying the same hung proxy).
        _delete_invalid_download(file_path, partial_path)
        raise StreamStallError(
            f"No bytes received for {stall_timeout}s; aborting {file_path.name}"
        ) from e
    finally:
        if registered_here and bandwidth_limiter:
            bandwidth_limiter.unregister_thread(active_thread_id)

    # Detect content-length mismatch: server claimed more bytes than it sent
    raise_if_shutdown_requested()
    # (premature close, truncated response, or spoofed headers).
    # Check BEFORE renaming so the .part file is still present for retry.
    if total_size > 0 and downloaded < total_size:
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Server promised {total_size} bytes but sent only {downloaded} "
            f"for {file_path.name}"
        )

    # Rename .part → final file inside a try block so that if validation
    # raises (file too small), the incomplete file is deleted before
    # propagating, preventing it from surviving a retry failure.
    try:
        partial_path.replace(file_path)
        _validate_completed_file(
            file_path,
            partial_path,
            check_structure=not response_body_known_complete,
        )
    except InvalidVideoDownloadError:
        _delete_invalid_download(file_path, partial_path)
        raise

    if complete_message:
        print(complete_message, flush=True)


def can_retry_with_debrid(stream: StreamInfo, download_url: str) -> bool:
    """Return True when a failed direct download can be retried via RealDebrid."""
    return bool(
        stream.info_hash
        and settings.REAL_DEBRID_API_KEY
        and not download_url.startswith("magnet:")
    )


# ── HLS routing helpers ──────────────────────────────────────────────────
#
# The HLS path is now triggered by URL shape alone: any download whose
# URL ends in ``.m3u8`` (or ``.m3u``) is routed through the HLS
# pipeline regardless of which addon produced the stream.  The
# :func:`_download_hls_to_file` dispatcher picks between the
# ffmpeg-based downloader (default) and the segment-based downloader
# based on the ``HLS_DOWNLOAD_METHOD`` setting and on whether ffmpeg
# is installed.  Addon classes that opt into HLS still set
# ``HLS_CAPABLE = True`` and tag their streams with
# ``StreamInfo.is_hls`` so addons which filter ``.m3u8`` URLs (the
# default behaviour of :func:`_is_downloadable_stream_candidate`) let
# them through, but the dispatcher in :func:`download_stream_to_file`
# no longer keys off that flag.

def _is_hls_url(url) -> bool:
    """Return True when *url* points at an HLS ``.m3u8``/``.m3u`` playlist."""
    if not url:
        return False
    from urllib.parse import urlparse

    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    path = (parsed.path or "").lower()
    return path.endswith(".m3u8") or path.endswith(".m3u")


def _download_hls_to_file(
    *,
    url: str,
    filename: str,
    bandwidth_limiter,
    thread_id,
    progress_callback,
    stall_timeout: float,
) -> None:
    """Resolve and download an HLS playlist to *filename*.

    Dispatch is driven by the ``HLS_DOWNLOAD_METHOD`` setting:

    * ``"ffmpeg"`` (default) — shell out to ``ffmpeg -i <url> -c copy
      <out>`` via :class:`HlsFfmpegDownloader`.  Robust against every
      HLS variant the CDN can serve (encrypted segments, byte-range
      / init segments, discontinuity, live edge, etc.).  Falls back
      to the segment-based downloader if ffmpeg is not on ``PATH``
      or if ffmpeg itself returns a non-zero exit code.
    * ``"segment"`` — pure-Python :class:`HlsDownloader` that
      fetches the playlist, picks a variant, downloads each
      ``.ts``/``.m3u`` segment and concatenates them.  No external
      dependency but limited to unencrypted playlists.
    """
    import threading

    from py_stremio.components.download.hls_download import HlsDownloader
    from py_stremio.components.download.hls_ffmpeg_download import (
        HlsFfmpegDownloader,
        HlsFfmpegError,
        find_ffmpeg,
        warn_missing_ffmpeg,
    )

    active_thread_id = (
        thread_id if thread_id is not None else threading.get_ident()
    )

    method = (
        getattr(settings, "HLS_DOWNLOAD_METHOD", "ffmpeg") or "ffmpeg"
    ).lower()

    if method == "ffmpeg":
        ffmpeg_path = find_ffmpeg()
        if ffmpeg_path:
            ffmpeg_downloader = HlsFfmpegDownloader(
                bandwidth_limiter=bandwidth_limiter,
                thread_id=active_thread_id,
                progress_callback=progress_callback,
                stall_timeout=stall_timeout,
            )
            try:
                ffmpeg_downloader.download(url, filename)
                return
            except HlsFfmpegError as exc:
                # ffmpeg failed — fall through to the segment-based
                # downloader so the user is not stuck on a single bad
                # playlist.  Surface the cause in the error message so
                # logs still make sense.
                import warnings as _w

                _w.warn(
                    f"ffmpeg HLS download failed ({exc}); falling back "
                    f"to segment-based downloader for {url}",
                    RuntimeWarning,
                    stacklevel=2,
                )

        # No ffmpeg on PATH (or ffmpeg failed and we're falling back).
        # Warn once and use the segment-based downloader so the
        # download still has a chance of succeeding.
        warn_missing_ffmpeg()

    downloader = HlsDownloader(
        bandwidth_limiter=bandwidth_limiter,
        thread_id=active_thread_id,
        progress_callback=progress_callback,
        stall_timeout=stall_timeout,
    )
    try:
        downloader.download(url, filename)
    finally:
        downloader.close()
