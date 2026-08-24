"""Merge newly discovered addon URLs into addons/addons.txt."""

import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from py_stremio.utils.atomic_write import atomic_write_text
from py_stremio.components.collect.addon_index import AddonIndex, get_addon_index

SECTIONS = {
    "TORRENT / DEBRID": [],
    "FREE HOSTERS / DIRECT STREAMS": [],
    "ANIME": [],
    "REGIONAL": [],
    "IPTV / LIVE TV": [],
    "SUBTITLES": [],
    "CATALOGS / METADATA": [],
    "NSFW": [],
    "MUSIC / RADIO / SPORTS": [],
    "UTILITY": [],
    "OTHER WORKING": [],
}


def _classify_addon(url: str) -> str:
    """Assign an addon URL to a section name."""
    u = url.lower()

    section_map = [
        (["intell-", "debridsearch", "mediafusion", "elfhosted", "annatar",
          "knightcrawler", "stremify", "jackettio", "aiostreams",
          "thepiratebay", "stremthru", "torz", "nyaa-scraper",
          "brazuca", "debridmedia", "torrent-catalogs", "comet.",
          "cometnet", "easynewsplus", "torrin", "peerflix", "archivio.",
          "orion.", "cinetorrent", "kickass", "easynews.",
          "shluflix", "notorrent2", "cache.", "publicdomain", "peario.",
          "rd=ecoo", "sort=seeders", "sort=size", "sort=quality"],
         "TORRENT / DEBRID"),
        (["freehost", "superflix", "plexio", "mycine.", "watchhub.",
          "publicdomainmovies"], "FREE HOSTERS / DIRECT STREAMS"),

        (["anime-", "-anime", "hanime", "onepace", "kitsu",
          "animeo", "sonzuanime", "animes-season"],
         "ANIME"),

        (["latinmovie", "latino-movie", "zoreu", "ftv-stremio",
          "figarocorso", "einthusan", "dubbindo", "ricostremio"],
         "REGIONAL"),

        (["argentinatv", "greek-tv", "xtreampro", "aio-streaming"],
         "IPTV / LIVE TV"),

        (["open", "subscene", "yify", "napisy", "hebsub", "addic7ed",
          "podnapisi", "subtito"],
         "SUBTITLES"),

        (["imdb-catalog", "mdblist", "tmdb", "trakt.", "ratings",
          "netflix-catalog", "cinemeta", "serializd", "simkl",
          "stremlist", "rpdb", "rottentomato", "tmdb-addon",
          "tmdb-collection", "age-ratings", "mdblist"],
         "CATALOGS / METADATA"),

        (["jaxxx", "javjt", "chaturbate", "stripchat", "nsfw"],
         "NSFW"),

        (["radio", "concert", "music", "broadcastify"],
         "MUSIC / RADIO / SPORTS"),

        (["up-next", "consumet", "youtube", "letterbot", "mubi",
          "premiumize", "stremioaddon.vercel", "stremio.itcon",
          "addon-marvel", "dindz", "elfhosted.com/apps", "mikmc",
          "mammamia", "mal-stremio", "hf.space", "hf.space",
          "napflix.", "syncribullet", "stremio-ar.", "subtito",
          "stremioaddons.space"],
         "OTHER WORKING"),
    ]

    for keywords, section in section_map:
        if any(k in u for k in keywords):
            return section

    # Catch-all: check if it starts with a typical addon domain
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    name = parsed.path.lower()

    # Unknown but active — put in OTHER WORKING
    return "OTHER WORKING"


def merge_new_addons(
    addon_txt_path: str,
    working_urls: list[tuple[str, str | None]],
    dead_urls: list[str] | None = None,
    verbose: bool = True,
) -> dict[str, int]:
    """Merge newly discovered URLs into addons/addons.txt.

    Reads the existing file, extracts existing URL bases for dedup,
    strips any previously-commented dead URLs, inserts new working
    URLs into the appropriate sections, and writes the cleaned file.

    The ``dead_urls`` argument is accepted for backward compatibility
    but is ignored — dead URLs are dropped, not preserved as comments.
    They can always be rediscovered and re-tested by a future
    ``Find more addons`` run.

    Returns a dict with counts: added, total_active, total_lines, skipped.
    """
    path = Path(addon_txt_path)
    _ = dead_urls  # intentionally unused; dead URLs are not preserved

    # Read existing content + extract known URL bases
    existing_lines: list[str] = []
    known_bases: set[str] = set()
    if path.exists():
        existing_lines = path.read_text().splitlines()
        for line in existing_lines:
            stripped = line.strip()
            # Only active (uncommented) URLs count toward dedup.
            # Commented-out lines (`# http...`) are by definition dead and
            # will be stripped below; they must not block new discoveries.
            if stripped.startswith("http"):
                known_bases.add(stripped.rstrip("/"))

    # Also track Torrentio base patterns — if we already have
    # any Torrentio with RD, skip adding new bare Torrentio ones
    has_any_torrentio = any("torrentio.strem.fun" in u for u in known_bases)

    # Filter working — skip if already present
    new_working: list[tuple[str, str | None]] = []
    skipped = 0
    for url, name in working_urls:
        base = url.rstrip("/")
        if base in known_bases:
            skipped += 1
            continue
        # Torrentio: if we already have any Torrentio variant,
        # only add genuinely new variants (different config)
        if "torrentio.strem.fun" in url and has_any_torrentio:
            # Check if we already have this exact config
            # (e.g., same language + sort combo with same RD key)
            if any(base.rstrip("/") in kb for kb in known_bases):
                skipped += 1
                continue
        new_working.append((url, name))
        known_bases.add(base)

    if not new_working:
        if verbose:
            print(f"  No new addons to add (all {skipped} already in file)")
        return {"added": 0, "total_active": len(known_bases), "total_lines": len(existing_lines), "skipped": skipped}

    # Build new sections from the working URLs
    sections: dict[str, list[tuple[str, str | None]]] = {}
    for section_name in SECTIONS:
        sections[section_name] = []
    for url, name in new_working:
        section_name = _classify_addon(url)
        if section_name not in sections:
            section_name = "OTHER WORKING"
        sections[section_name].append((url, name))

    # Remove empty sections
    sections = {k: v for k, v in sections.items() if v}

    # Build the output file.
    # Start from the existing file but strip:
    #   - The legacy OBSERVED ADDONS section header, its dead URLs, and the
    #     END OF ADDONS LIST marker (the section no longer exists).
    #   - Any in-place commented URL lines (`# http...` / `# http...`).
    #     These are by definition dead URLs and the user wants only valid
    #     addons in the file.
    new_lines: list[str] = []
    in_legacy_trailer = False
    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith("# ── OBSERVED ADDONS"):
            in_legacy_trailer = True
            continue
        if stripped.startswith("# ── END OF ADDONS LIST"):
            in_legacy_trailer = True
            continue
        if in_legacy_trailer:
            continue
        if _is_commented_url(stripped):
            continue
        new_lines.append(line)

    if not new_lines:
        # Empty file or no existing — write the header
        new_lines = [
            "# Py-Stremio addon manifest URLs",
            f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "# Active URLs: auto-counted",
            "",
        ]

    # Append the new working sections at the end of the active region
    for section_name, urls in sections.items():
        if not urls:
            continue
        dash = "─" * (65 - len(section_name) - 5)
        new_lines.append("")
        new_lines.append(f"# ── {section_name} {dash}")
        for url, name in urls:
            label = f"  # {name}" if name and name != "http_200" else ""
            new_lines.append(f"{url}{label}")

    # Count active URLs in the new file
    active_count = sum(1 for l in new_lines if l.strip().startswith("http"))

    # Refresh header summary lines so they reflect the cleaned state.
    new_lines = _refresh_header_summary(new_lines, active_count)

    # Write atomically so addon discovery cannot leave the inventory truncated.
    atomic_write_text(path, "\n".join(new_lines) + "\n")

    if verbose:
        print(
            f"  ✓ Added {len(new_working)} new working addons. "
            f"Now {active_count} active in {len(new_lines)} lines "
            f"(dead URLs removed — re-run 'Find more addons' to rediscover)",
            flush=True,
        )

    return {
        "added": len(new_working),
        "total_active": active_count,
        "total_lines": len(new_lines),
        "skipped": skipped,
    }


_COMMENTED_URL_RE = re.compile(r"^#\s*https?://")


def _is_commented_url(stripped: str) -> bool:
    """Return True if the line is a commented-out URL (i.e. dead)."""
    return bool(_COMMENTED_URL_RE.match(stripped))


def _refresh_header_summary(lines: list[str], active_count: int) -> list[str]:
    """Update the top-of-file ``# Active URLs`` / ``# Total lines`` lines.

    Removes obsolete ``# Total commented (dead)`` and ``# Grand total lines``
    lines anywhere they appear.
    """
    refreshed: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# Total commented (dead):"):
            continue
        if stripped.startswith("# Grand total lines:"):
            continue
        refreshed.append(line)

    for index, line in enumerate(refreshed):
        stripped = line.strip()
        if stripped.startswith("# Active URLs:"):
            refreshed[index] = f"# Active URLs: {active_count} (last validated)"
        elif stripped.startswith("# Total lines:"):
            refreshed[index] = f"# Total lines: {len(refreshed)}"

    return refreshed


def merge_with_index(
    index: AddonIndex | None = None,
    addon_txt_path: str | None = None,
    working_urls: list[tuple[str, str | None]] | None = None,
    dead_urls: list[str] | None = None,
    verbose: bool = True,
) -> dict[str, int]:
    """Merge URLs using AddonIndex for O(1) deduplication.

    This is the fast version of merge_new_addons() that uses the index
    instead of linear O(n) file scanning.

    Args:
        index: AddonIndex to use. If None, uses global singleton.
        addon_txt_path: Path to addons.txt file.
        working_urls: List of (url, name) tuples to add as working.
        dead_urls: List of dead URLs to mark as failed in the index.
        verbose: Print progress info.

    Returns:
        Dict with counts: added, failed, skipped, total_in_index.
    """
    index = index or get_addon_index()

    if working_urls is None:
        working_urls = []
    if dead_urls is None:
        dead_urls = []

    added_count = 0
    for url, _ in working_urls:
        if index.add(url, is_working=True):
            added_count += 1

    failed_count = 0
    for url in dead_urls:
        if index.add(url, is_working=False):
            failed_count += 1

    skipped_count = len(working_urls) + len(dead_urls) - added_count - failed_count

    if verbose:
        status = index.quick_status()
        print(
            f"  Index: {status['total']} total, "
            f"{status['working']} working, "
            f"{status['failed']} failed, "
            f"{status['untested']} untested"
        )
        if added_count > 0:
            print(f"  Added {added_count} new addons to index")
        if failed_count > 0:
            print(f"  Marked {failed_count} addons as failed")
        if skipped_count > 0:
            print(f"  Skipped {skipped_count} duplicates")

    return {
        "added": added_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "total_in_index": len(index),
    }
