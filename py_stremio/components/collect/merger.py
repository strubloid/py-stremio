"""Merge newly discovered addon URLs into addons.txt."""

import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from py_stremio.utils.atomic_write import atomic_write_text

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
    "OBSERVED ADDONS": [],
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
    dead_urls: list[str],
    verbose: bool = True,
) -> dict[str, int]:
    """Merge newly discovered URLs into addons.txt.

    Reads the existing file, extracts existing URL bases for dedup,
    then inserts new working URLs into the appropriate sections and
    appends dead URLs as comments.

    Returns a dict with counts: added, dead_added, total_after.
    """
    path = Path(addon_txt_path)

    # Read existing content + extract known URL bases
    existing_lines: list[str] = []
    known_bases: set[str] = set()
    existing_observed: list[str] = []
    if path.exists():
        existing_lines = path.read_text().splitlines()
        in_observed = False
        for line in existing_lines:
            stripped = line.strip()
            if stripped.startswith("# ── OBSERVED ADDONS"):
                in_observed = True
                continue
            if in_observed:
                if stripped.startswith("# http"):
                    observed_url = stripped.removeprefix("# ").split("  #", 1)[0].rstrip("/")
                    existing_observed.append(observed_url)
                    known_bases.add(observed_url)
                continue
            if stripped.startswith("http"):
                # Normalise trailing slash for dedup
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

    # Filter dead — skip if already present (active or dead)
    new_dead: list[str] = []
    for url in dead_urls:
        base = url.rstrip("/")
        if base in known_bases:
            continue
        # Also check if it's already in dead section
        dead_line = f"# {url.rstrip('/')}/"
        if any(dead_line in l for l in existing_lines):
            continue
        new_dead.append(url)
        known_bases.add(base)

    if not new_working and not new_dead:
        if verbose:
            print(f"  No new addons to add (all {skipped} already in file)")
        return {"added": 0, "dead_added": 0, "total_after": len(known_bases), "skipped": skipped}

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

    # Build the output file
    # Start with existing header and active lines up to the OBSERVED section
    new_lines: list[str] = []

    # Copy the existing header and all active sections
    in_observed = False
    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith("# ── OBSERVED ADDONS"):
            in_observed = True
            continue
        if not in_observed:
            new_lines.append(line)

    if not new_lines:
        # Empty file or no existing — write the header
        new_lines = [
            "# Py-Stremio addon manifest URLs",
            f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "# Active URLs: auto-counted",
            "",
        ]

    # Add the new sections right before the OBSERVED section
    for section_name, urls in sections.items():
        if not urls:
            continue
        dash = "─" * (65 - len(section_name) - 5)
        new_lines.append("")
        new_lines.append(f"# ── {section_name} {dash}")
        for url, name in urls:
            label = f"  # {name}" if name and name != "http_200" else ""
            new_lines.append(f"{url}{label}")

    # Count active so far
    is_active = lambda l: l.strip().startswith("http") and not l.strip().startswith("#")
    active_before_observed = sum(1 for l in new_lines if is_active(l))

    # Append observed section with dead addons
    new_lines.append("")
    new_lines.append("# ── OBSERVED ADDONS (was down, may come back) ───────────────────")
    for url in dict.fromkeys([*existing_observed, *new_dead]):
        new_lines.append(f"# {url.rstrip('/')}/")

    # Count dead
    dead_count = sum(1 for l in new_lines if l.strip().startswith("# http"))

    # Final footer
    new_lines.append("")
    new_lines.append("# ── END OF ADDONS LIST ───────────────────────────────────────────────")
    new_lines.append(f"# Total active: {active_before_observed}")
    new_lines.append(f"# Total commented (dead): {dead_count}")
    new_lines.append(f"# Grand total lines: {len(new_lines)}")

    # Write atomically so addon discovery cannot leave addons.txt truncated.
    atomic_write_text(path, "\n".join(new_lines) + "\n")

    if verbose:
        print(
            f"  ✓ Added {len(new_working)} new working addons, "
            f"{len(new_dead)} dead (commented). "
            f"Now {active_before_observed} active + {dead_count} dead = {len(new_lines)} lines",
            flush=True,
        )

    return {
        "added": len(new_working),
        "dead_added": len(new_dead),
        "total_active": active_before_observed,
        "total_dead": dead_count,
        "total_lines": len(new_lines),
        "skipped": skipped,
    }
