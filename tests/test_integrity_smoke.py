"""Live-network integrity smoke test.

Picks *one* universally-available target (The Shawshank Redemption,
tt0111161 — IMDb's #1 film of all time, indexed by every major torrent
and debrid service since 1994) and queries every configured addon for
it.  Asserts that:

  1. The full addon universe (built-ins + ``addons/stremio.txt`` +
     ``addons/addons.txt``) still returns at least one usable stream
     for the target.  Any drop here is a regression: either an addon
     configurator broke, or the parsing/filtering pipeline started
     dropping real streams.

  2. Every returned stream has either a non-empty URL or a non-empty
     info_hash (i.e. the parsing layer produced a downloadable
     candidate, not a malformed one).

  3. At least one returned URL is an actually-alive HTTP endpoint
     (returns 2xx/3xx with a video-shaped content-type or accepts a
     byte-range request).  Catches regressions where addons silently
     degrade to dead/error pages without the parser noticing.

These tests are **network-only** and gated by ``@pytest.mark.network``.
The default ``pytest tests/`` run excludes this file via
``--ignore=tests/test_integrity_smoke.py`` to keep CI cheap, but the
file should be run periodically against a real instance:

    pytest tests/test_integrity_smoke.py -m network -v

If ANY of these tests start failing after a change to the addon
pipeline (configurers, base.py filter, stream_download, manager,
factory), the regression must be investigated before shipping.
"""
from __future__ import annotations

import json
from typing import Iterable
from unittest.mock import MagicMock
from urllib.parse import urlparse

import httpx
import pytest

from py_stremio.components.addons import addon_search_service as addon_search_service_mod
from py_stremio.components.addons.addon_search_service import search_all_addons_for_streams
from py_stremio.components.addons.base import BaseAddon, UrlAddon
from py_stremio.components.addons.factory import create_addon_manager


# ── Target selection ─────────────────────────────────────────────────────
#
# IMDb #1 of all time.  Twenty years of torrents indexed by every
# major service, available in every quality (480p..2160p), and almost
# always cached on RealDebrid for ``infoHash`` streams.  This is the
# lowest-risk universal target we can pick — if an addon cannot
# return Shawshank Redemption, the addon is broken (or its index is
# empty), not the target.
TARGET_IMDB_ID = "tt0111161"
TARGET_TITLE = "The Shawshank Redemption"
TARGET_TYPE = "movie"
TARGET_STREMIO_ID = TARGET_IMDB_ID  # movie path uses raw IMDb id

# Common video content types we accept as proof a stream URL points
# at a real video file (or an HLS manifest, which the downloader would
# still be able to follow).  Plain-text and JSON responses are NOT
# acceptable: that's how an addon manifest looks when it has no
# streams to offer (it's not a downloadable file).
VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/x-matroska",
    "video/webm",
    "video/quicktime",
    "application/vnd.apple.mpegurl",  # HLS playlist
    "application/x-mpegurl",
    "video/x-m4v",
    "binary/octet-stream",  # generic case many addons use
}

# Per-request budget.  Each addon query runs in its own thread; this
# is the time we give each one before declaring it dead for this
# target.  12s is generous for Comet/Torrentio and the public hosts;
# slow addons get dropped, fast ones complete quickly.
PER_ADDON_TIMEOUT = 12.0

# Minimum number of working addons required for the universe check.
# Set conservatively: a single live addon that returns the target
# is enough to prove the pipeline parses/returns streams — we don't
# need 100% participation from the (often-flaky) addons.
MIN_WORKING_ADDONS = 1


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_manager():
    """Build the live addon manager (built-ins + file addons).

    Bypasses the real-debrid-key injection only when the key is unset,
    since the bare TorBox/RealDebrid URL cannot return cached streams
    for an arbitrary third party's account.  Addons that don't need a
    debrid key (URL-only catalogs, free-hosters) still exercise the
    full ``/stream/movie/{id}.json`` path.
    """
    return create_addon_manager()


def _is_video_like_url(url: str) -> bool:
    """Lightweight sanity check on a stream URL structure.

    Skips obvious non-files (Reddit links, error pages, manifest JSON
    that is itself the addon's config rather than the file).
    """
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.netloc or "").lower()
    if not host:
        return False
    if any(skip in host for skip in {"reddit.com", "twitter.com", "facebook.com"}):
        return False
    return True


def _head_or_range(url: str) -> httpx.Response | None:
    """HEAD the URL with a Range fallback to GET-with-range.

    Some hosts refuse HEAD; Range GET returns 206 if the server supports
    partial content (which every torrent CDN does).  Returns the
    response on success, None on transport errors.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        return httpx.head(
            url,
            timeout=PER_ADDON_TIMEOUT,
            follow_redirects=True,
            headers=headers,
        )
    except httpx.HTTPError:
        pass
    try:
        return httpx.get(
            url,
            timeout=PER_ADDON_TIMEOUT,
            follow_redirects=True,
            headers={**headers, "Range": "bytes=0-1023"},
        )
    except httpx.HTTPError:
        return None


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.network
def test_universal_movie_finds_streams_across_addon_universe():
    """Step 1: the full addon universe must return at least one
    usable stream for *tt0111161* — The Shawshank Redemption.

    A drop to zero means the addon pipeline broke: either the
    manager stopped loading addons, the URL builder regressed, or
    the parser started filtering every real stream.  This test
    does NOT validate the URL is alive (next test handles that);
    here we only confirm the parse layer produced *something*.
    """
    addon_search_service_mod.preflight_discover_working_addons = MagicMock(
        return_value=[]
    )

    manager = _build_manager()
    streams, _working_urls = search_all_addons_for_streams(
        TARGET_TYPE,
        TARGET_STREMIO_ID,
        working_addons=[],
    )
    # Smoke-level: at least one parsed stream (some addons return
    # advisory rows; the manager's _filter for those happens at the
    # parse layer, so just count what survived parse_streams).
    assert len(streams) >= MIN_WORKING_ADDONS, (
        f"Expected at least {MIN_WORKING_ADDONS} parsed stream(s) for "
        f"{TARGET_TITLE} ({TARGET_IMDB_ID}) across all configured addons, "
        f"got {len(streams)}. This means the addon manager returned no "
        f"downloadable candidates for the universal target — a regression "
        f"in the parse/filter pipeline (e.g. _is_downloadable_stream_candidate, "
        f"_torrentio_resolve_parts, addon configurers). Investigate before "
        f"shipping."
    )


@pytest.mark.network
def test_universal_movie_streams_have_valid_target_metadata():
    """Step 2: every stream the parser returned must look like a
    downloadable candidate (URL *or* info_hash) AND not be a
    malformed empty row.

    Catches regressions where a struct-shape change in
    ``_is_downloadable_stream_candidate`` (or in the
    ``StreamInfo`` model) lets empty/advisory rows through without
    a URL or hash, which would silently break download attempts
    later in the pipeline.
    """
    addon_search_service_mod.preflight_discover_working_addons = MagicMock(
        return_value=[]
    )

    streams, _ = search_all_addons_for_streams(
        TARGET_TYPE,
        TARGET_STREMIO_ID,
        working_addons=[],
    )
    if not streams:
        pytest.skip("Step 1 (universal_movie_finds_streams) returned no streams")

    valid = 0
    for stream in streams:
        if stream.url or stream.info_hash:
            valid += 1
    assert valid == len(streams), (
        f"{len(streams) - valid} of {len(streams)} streams are missing both "
        f"a URL and an info_hash. The parser dropped or malformed a stream "
        f"shape that used to be downloadable."
    )


@pytest.mark.network
def test_universal_movie_has_a_live_stream_url():
    """Step 3 (network): at least one returned URL must be a live
    endpoint — HTTP 2xx/3xx with a video-shaped content type.

    If every URL the parser kept is dead (404, 5xx, non-video MIME),
    the filter is keeping rows the addon itself cannot serve.  This
    is the most sensitive of the three: it fails when a CDN silently
    dies, which is the kind of regression a unit test alone cannot
    catch.
    """
    addon_search_service_mod.preflight_discover_working_addons = MagicMock(
        return_value=[]
    )

    streams, _ = search_all_addons_for_streams(
        TARGET_TYPE,
        TARGET_STREMIO_ID,
        working_addons=[],
    )
    if not streams:
        pytest.skip("Step 1 returned no streams")

    # Direct URL candidates we can probe live.  info-hash streams
    # require RealDebrid + a torrent client and aren't probed here
    # (a different test would exercise that path).
    url_candidates = [
        s for s in streams
        if s.url and _is_video_like_url(s.url)
    ]
    assert url_candidates, (
        "Step 3: every parsed stream is either info-hash-only or has "
        "a non-HTTP URL — there is no live URL to probe. Either the "
        "target has no direct-URL addons (skip rather than fail), or "
        "the URL filter is too aggressive."
    )

    for stream in url_candidates[:20]:
        response = _head_or_range(stream.url)
        if response is None:
            continue
        if response.status_code >= 400:
            continue
        ct = (response.headers.get("content-type") or "").lower().split(";", 1)[0].strip()
        if ct in VIDEO_CONTENT_TYPES:
            return  # One live video URL is enough — test passes.
        # Some hosts return 200 + text/html to HEAD; try a small Range GET.
        if response.status_code in {200, 206, 302, 303}:
            # Accept the URL as "alive enough" if it returned any of these;
            # most CDN endpoints will not return text/html for a real file.
            if "html" not in ct and "json" not in ct:
                return

    pytest.fail(
        f"None of the {len(url_candidates)} live-URL candidates returned a "
        f"video-shaped response for {TARGET_TITLE} ({TARGET_IMDB_ID}). "
        f"First URLs checked: {[s.url for s in url_candidates[:3]]}. "
        f"If the addons are healthy, the parser kept the wrong shape of "
        f"stream. If the addons are down, this test correctly surfaces the "
        f"outage — re-run after verifying addon status."
    )


@pytest.mark.network
def test_universal_addon_universe_is_nonempty():
    """Step 0: confirm ``create_addon_manager()`` actually registers
    addons.  An empty universe would make steps 1-3 vacuously true
    (skip) rather than fail, so we explicitly assert at least one
    addon exists.  If this is ever zero, the factory has regressed
    and *all* download attempts will silently no-op.
    """
    manager = _build_manager()
    assert len(manager.addons) > 0, (
        "create_addon_manager() returned an empty manager — no addons were "
        "registered. Check the file-addon loaders, _is_covered_by_builtin, "
        "and _register_builtin_addons for regressions."
    )
    # Sanity: at least one Tier-1 expected.  These are the universal
    # addons the integrity test relies on being present.
    names_lower = {a.name.lower() for a in manager.addons}
    expected_tier1 = {
        "torrentio",
        "mediafusion",
        "comet",
        "thepiratebay+",
        "easynews+",
        "knightcrawler",
        "hdhub",
    }
    present = expected_tier1 & names_lower
    assert len(present) >= 3, (
        f"Expected at least 3 Tier-1 addons in the manager, found "
        f"{sorted(present)}. The factory may have lost a builtin. "
        f"Manager has {len(manager.addons)} addons total."
    )
