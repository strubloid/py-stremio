# World Download Strategy

This document outlines a comprehensive plan to maximize py-stremio's ability to download any content from anywhere in the world. The goal is to never be stuck without a downloadable stream.

## Current State Analysis

### What's Working

- **80+ built-in addon classes** across Torrentio, Comet, MediaFusion, aggregators, anime, IPTV, regional, and debrid categories
- **RealDebrid integration** for torrent resolution (magnet → direct URL)
- **Preflight optimization** — discovers working addons before downloading
- **Verified server cache** per folder — only successful downloads are persisted
- **Multi-threaded concurrent downloads** with fair bandwidth sharing
- **Partial download resume** via .part files and Range headers
- **8-source addon discovery** including Stremio official collection, GitHub issues, stremio-addons.net, ElfHosted, baby-beamup.club, and cloud hosting patterns

### What's Missing

| Gap | Impact |
|-----|--------|
| **Single debrid service (RealDebrid only)** | Users without RD have very limited torrent resolution |
| **No P2P direct download** | Cannot download torrents without RD or a torrent proxy |
| **Limited regional coverage** | Missing dedicated Middle East, Southeast Asian, Chinese, Korean addons |
| **No multi-debrid fallback** | If RD fails, no other debrid service to try |
| **Preflight skips episodes on 0 results** | May miss content if rate limits clear later |
| **No WebTorrent support** | Torrents only resolved via RD |
| **Experimental addons used as last resort only** | Not proactively used when normal addons fail mid-download |
| **No Enhanced discovery sources** | Missing niche scrapers, P2P networks, regional indexes |
| **Slow file operations** | Linear O(n) scanning of all addons on every update |
| **No persistent index** | Duplicate checking rebuilds from scratch every run |
| **Naive deduplication** | Only exact URL matches, not host+path pattern awareness |
| **No AI-powered discovery** | Manual source scraping only, no intelligent addon finding |

---

## Strategy Overview

### The Five Pillars of Universal Download Coverage

1. **Multi-Debrid Integration** — Support multiple debrid services (RealDebrid, Premiumize, AllDebrid, Debrid-Link, Offcloud, DMM)
2. **Expanded Addon Ecosystem** — Add regional aggregators, niche scrapers, and independent indexes
3. **Hybrid Download Path** — Support direct HTTP, torrent proxy, AND WebTorrent fallback
4. **Adaptive Discovery** — Dynamically discover and test addons based on content type and region
5. **Fast & Smart Indexing** — Persistent in-memory index, O(1) lookups, AI-powered discovery, zero duplicate additions

---

## Pillar 1: Multi-Debrid Integration

### Why It Matters

RealDebrid has limitations:
- DMCA/451 errors for popular content
- Limited to one account per user
- Geographic restrictions on some streams
- Only supports torrents and premium links (noNZB, no Usenet)

### Implementation Plan

#### 1.1 Abstract Debrid Provider Interface

Create a common interface in `components/debrid/`:

```python
# components/debrid/base.py
from abc import ABC, abstractmethod

class BaseDebridProvider(ABC):
    name: str

    @abstractmethod
    def resolve_torrent(self, info_hash: str, file_idx: int | None = None) -> str | None:
        """Resolve torrent via this debrid service. Returns direct URL or None."""
        pass

    @abstractmethod
    def resolve_link(self, url: str) -> str | None:
        """Resolve a premium link/hoster URL through this debrid service."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this debrid service is configured and working."""
        pass
```

#### 1.2 Implement Additional Debrid Providers

| Service | API | Features | Priority |
|---------|-----|----------|----------|
| **Premiumize.me** | https://api.premiumize.me | Torrent, NZB, premium links, direct hosts | HIGH |
| **AllDebrid** | https://api.alldebrid.com | Torrent, premium links, magnets | HIGH |
| **Debrid-Link.fr** | https://api.debrid-link.fr | Torrent, premium links | MEDIUM |
| **Offcloud** | https://api.offcloud.com | Cloud torrent, premium links | MEDIUM |
| **DMM (Japan)** | https://api.dmm.com | Japanese content focus | LOW |

#### 1.3 Multi-Debrid Resolution Strategy

```python
# components/debrid/multi_resolver.py
async def resolve_with_any_debrid(info_hash: str, file_idx: int | None) -> str | None:
    """Try all configured debrid services in parallel, return first success."""
    providers = get_configured_providers()  # RealDebrid, Premiumize, AllDebrid, ...

    results = await asyncio.gather(
        *[p.resolve_torrent(info_hash, file_idx) for p in providers],
        return_exceptions=True
    )

    for provider, result in zip(providers, results):
        if isinstance(result, str) and result:
            return result
    return None
```

#### 1.4 Settings

```env
# .env
REAL_DEBRID_API_KEY=your_rd_key
PREMIUMIZE_API_KEY=your_premiumize_key
ALLDEBRID_API_KEY=your_alldebrid_key
DEBRID_LINK_API_KEY=your_debridlink_key
OFFCLOUD_API_KEY=your_offcloud_key

# Primary debrid service (attempts first)
PRIMARY_DEBRID=realdebrid

# Fallback chain (tried in order if primary fails)
DEBRID_FALLBACK_CHAIN=premiumize,alldebrid
```

---

## Pillar 2: Expanded Addon Ecosystem

### 2.1 Missing Regional Addon Categories

#### High Priority Additions

| Region | Addon Type | Examples to Add |
|--------|------------|------------------|
| **Korean** | Movie/Series | Waave, Kroz, Soopra clones |
| **Japanese** | Anime/Movie | Anime8, Animetbs, KissAsian variants |
| **Chinese** | Movie/Series | useaplease alternatives, doramedia |
| **Middle East** | Arabic content | Shahid variants, Crocko alternatives |
| **Southeast Asia** | Thai/Vietnamese | Regional torrent scrapers |
| **Indian Subcontinent** | Bollywood/Hindi | Expanded beyond Torrentio Hindi |
| **African** | Regional content | South African, Nigerian content |

#### Addon Discovery Enhancement

Current sources are limited. Add:

```python
# collect/sources.py additions

SOURCES = [
    # ... existing sources ...
    "scrape_stremio_addons_net",      # Already exists
    "scrape_github_issues",          # Already exists
    "gen_torrentio_variants",        # Already exists
    "gen_elfhosted_addons",           # Already exists
    "gen_cloud_addons",              # Already exists

    # NEW SOURCES
    "scrape_nightly_instructions",   # Scrape community nightlies
    "scrape_reddit_recommendations", # Scrape r/StremioAddons
    "scrape_torrentio_community",     # Official Torrentio community
    "scrape_mediafusion_instances",  # MediaFusion hosted variants
    "scrape_comet_variants",         # Comet family variants
]

def scrape_reddit_recommendations() -> set[str]:
    """Scrape addon recommendations from Reddit communities."""
    # r/StremioAddons, r/Stremio, r/Piracy
    pass

def scrape_nightly_instructions() -> set[str]:
    """Find community-built nightly addon builds."""
    # Look for self-hosted addon builds shared in Discord/Reddit
    pass
```

### 2.2 Addon Scoring System

Not all addons are equal. Implement a scoring system:

```python
@dataclass
class AddonScore:
    addon_url: str
    success_rate: float        # Downloads succeeded / attempted
    avg_response_time: float   # milliseconds
    last_success: datetime
    coverage_types: set[str]   # {"anime", "regional", "international"}
    regional_strength: str     # "japanese", "korean", "international"
```

```python
# Scoring strategy for addon selection
def score_addon(addon: BaseAddon, history: list[DownloadResult]) -> float:
    base_score = 0.0

    # Recency bonus
    if addon.last_success and addon.last_success > datetime.now() - timedelta(hours=24):
        base_score += 10.0

    # Success rate (40% weight)
    success_rate = successful_downloads / total_attempts
    base_score += success_rate * 40

    # Speed bonus (20% weight) — faster addons get higher scores
    if addon.avg_response_time < 1000:  # < 1 second
        base_score += 20
    elif addon.avg_response_time < 3000:  # < 3 seconds
        base_score += 10

    # Regional match bonus (40% weight)
    if addon.regional_strength == target_region:
        base_score += 40

    return base_score
```

### 2.3 Content-Type Specialized Addons

Different addons excel at different content:

```python
CONTENT_ADDON_AFFINITY = {
    "anime": ["AnimeKitsu", "Akuma", "Animepahe", "Animeo", "OnePace",
              "HiAnimeStreams", "AnimeStream", "YaStream", "Hanime"],
    "japanese": ["AnimeKitsu", "Animepahe", "YaStream", "OnePace"],
    "korean": ["Waave", "Kroz"],  # To be added
    "bollywood": ["TorrentioHindi", "Einthusan"],
    "international": ["Torrentio", "MediaFusion", "Comet", "Nucleus", "Orion"],
    "portuguese": ["BrazucaTorrents", "TorrentioPortuguese", "MicoLeaoDublado"],
    "spanish": ["TorrentioSpanish", "Peerflix", "LatinMovies"],
    "french": ["Frenchio", "FigaroCorso"],
    "german": ["TorrentsDB", "EasyNewsPlus"],  # No dedicated German addon
    "italian": ["TorrentsDB", "FigaroCorso"],
    " arabic": ["NoTorrent", "FTV"],  # Limited options
    "russian": ["Kinopub"],  # Was removed, needs alternative
}
```

When searching for a specific content type, prioritize addons with affinity for that type.

---

## Pillar 3: Hybrid Download Path

### 3.1 WebTorrent Fallback

When neither RD nor direct HTTP works, fall back to WebTorrent:

```python
# download/webtorrent.py
import asyncio
from webtorrent import WebTorrent

async def download_via_webtorrent(info_hash: str, file_idx: int,
                                   output_path: Path) -> bool:
    """Download using WebTorrent directly (P2P)."""

    wt = WebTorrent()
    torrent = await wt.add(f"magnet:?xt=urn:btih:{info_hash}")

    # Select file
    files = torrent.files
    if file_idx is not None and 0 <= file_idx < len(files):
        selected_file = files[file_idx]
    else:
        # Pick largest file (usually the video)
        selected_file = max(files, key=lambda f: f.length)

    # Stream to file
    with open(output_path, 'wb') as f:
        selected_file.createReadStream().pipe(f)

    wt.destroy()
    return True
```

**Note**: This is a last-resort option. WebTorrent requires the torrent to be seeded and may be slow. It should only be used when:
- No debrid service is configured
- Direct HTTP streams all failed
- All debrid services failed for this specific content

### 3.2 Enhanced Torrent Proxy Support

The current `TORRENT_PROXY_URL` support should be enhanced:

```python
# download/torrent_proxy.py

class TorrentProxyManager:
    """Manages multiple torrent proxy endpoints."""

    def __init__(self):
        self.proxies: list[str] = []
        self.current_index = 0

    def add_proxy(self, url: str):
        """Add a torrent proxy URL."""
        self.proxies.append(url)

    def get_next_proxy(self) -> str | None:
        """Round-robin to next proxy."""
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxies)
        return proxy

    def resolve_via_proxy(self, info_hash: str, file_idx: int) -> str | None:
        """Try all proxies until one works."""
        for proxy in self.proxies:
            result = self._resolve_with_proxy(proxy, info_hash, file_idx)
            if result:
                return result
        return None
```

### 3.3 Multi-Source Combining

For difficult content, allow combining multiple partial downloads:

```python
# download/multi_source.py

async def combine_partial_downloads(parts: list[Path], output: Path) -> bool:
    """Combine multiple partial downloads into final file.

    Use case: Source A downloaded 50MB before stalling, source B downloaded
    30MB before stalling. Combine both parts to get a complete file.
    """
    with open(output, 'wb') as out:
        for part in sorted(parts, key=lambda p: p.name):
            with open(part, 'rb') as inp:
                shutil.copyfileobj(inp, out)

    # Verify final file
    return verify_video_integrity(output)
```

---

## Pillar 4: Adaptive Discovery

### 4.1 Dynamic Addon Testing

Instead of static discovery, implement continuous health monitoring:

```python
# collect/health_monitor.py

@dataclass
class AddonHealth:
    url: str
    is_alive: bool
    response_time_ms: float
    stream_success_rate: float
    last_tested: datetime
    consecutive_failures: int

class AddonHealthMonitor:
    """Continuously monitor addon health and score."""

    def __init__(self):
        self.addons: dict[str, AddonHealth] = {}

    async def test_addon(self, addon_url: str) -> AddonHealth:
        """Test addon with a probe request."""
        start = time.time()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{addon_url}/stream/movie/tt0133093.json",
                    timeout=10
                )
            elapsed = (time.time() - start) * 1000

            return AddonHealth(
                url=addon_url,
                is_alive=resp.status_code == 200,
                response_time_ms=elapsed,
                stream_success_rate=self._calculate_success_rate(addon_url, resp),
                last_tested=datetime.now(),
                consecutive_failures=0
            )
        except Exception:
            return AddonHealth(
                url=addon_url,
                is_alive=False,
                response_time_ms=999999,
                stream_success_rate=0.0,
                last_tested=datetime.now(),
                consecutive_failures=self.addons.get(addon_url, AddonHealth(url=addon_url)).consecutive_failures + 1
            )

    async def discover_and_test_all(self) -> list[AddonHealth]:
        """Run full discovery + health check cycle."""
        all_urls = await run_all_sources()
        results = await asyncio.gather(*[self.test_addon(u) for u in all_urls])
        return sorted(results, key=lambda h: h.response_time_ms)
```

### 4.2 Content-Aware Search

When searching for content, use IMDB type and region to filter addons:

```python
# addons/content_aware_search.py

def search_with_content_awareness(type_: str, id_: str,
                                   imdb_id: str | None = None) -> list[StreamInfo]:
    """Search addons with content-type awareness."""

    # Determine content characteristics
    characteristics = analyze_content(type_, id_, imdb_id)

    # Get relevant addons sorted by affinity
    relevant_addons = get_addons_by_affinity(
        characteristics.content_type,  # anime, movie, series
        characteristics.region,        # japanese, korean, international
        characteristics.language        # primarily audio language
    )

    # Search only relevant addons first
    streams = []
    for addon in relevant_addons[:10]:  # Top 10 relevant
        result = addon.search(type_, id_)
        if result:
            streams.extend(result)

    # If no results, fall back to all addons
    if not streams:
        streams = search_all_addons(type_, id_)

    return streams
```

### 4.3 Proactive Experimental Addon Usage

Instead of using experimental addons only as last resort:

```python
# download/progressive_search.py

async def search_and_download_progressive(type_: str, id_: str, file_idx: int | None):
    """Progressively search more addon tiers as earlier tiers fail."""

    # Tier 1: Cached working addons (instant)
    streams = search_cached_working_addons(type_, id_)
    if streams:
        return await download_with_fallback(streams)

    # Tier 2: Built-in premium addons (fast)
    streams = search_addons_by_tier("premium")  # Torrentio, MediaFusion, Comet
    if streams:
        return await download_with_fallback(streams)

    # Tier 3: Regional focused addons (medium speed)
    streams = search_addons_by_tier("regional")  # Regional addons for content type
    if streams:
        return await download_with_fallback(streams)

    # Tier 4: All built-in addons (slower)
    streams = search_all_builtin_addons(type_, id_)
    if streams:
        return await download_with_fallback(streams)

    # Tier 5: Experimental addons (slowest, but broadest)
    # NOW used proactively, not just as last resort
    if settings.EXPERIMENTAL_ADDONS_ENABLED:
        streams = search_experimental_addons(type_, id_)
        if streams:
            return await download_with_fallback(streams)

    # Tier 6: Live discovery (slowest, newest sources)
    discovered = await discover_live_addons(type_, id_)
    if discovered:
        return await download_with_fallback(discovered)

    return None
```

---

---

## Pillar 5: Fast & Smart Indexing

This pillar addresses the critical performance and intelligence gaps in addon discovery and management. Without this, the system becomes slower over time as the addon list grows.

### 5.1 Persistent In-Memory Index

**Problem**: Every operation (validation, discovery, search) rebuilds the entire addon list from disk. With 1000+ addons, this becomes O(n) slowdown.

**Solution**: Create a persistent in-memory index with O(1) lookups:

```python
# collect/addon_index.py

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from urllib.parse import urlparse

@dataclass
class IndexedAddon:
    url: str                           # Normalized URL
    hostname: str                     # e.g., "torrentio.strem.fun"
    path_pattern: str                  # e.g., "/realdebrid=XXX/sort=seeders"
    first_seen: datetime
    last_checked: datetime
    is_working: bool | None = None    # None = unknown
    consecutive_failures: int = 0
    last_error: str | None = None

class AddonIndex:
    """Thread-safe persistent index of all known addon URLs.

    Provides O(1) lookups by URL, hostname, or pattern.
    Survives across discovery runs but not process restarts (use JSON for that).
    """

    def __init__(self):
        self._by_url: dict[str, IndexedAddon] = {}
        self._by_hostname: dict[str, set[str]] = {}  # hostname → set of URLs
        self._by_pattern: dict[str, set[str]] = {}   # path_pattern → set of URLs
        self._lock = RLock()
        self._modified = False

    # ── O(1) membership tests ─────────────────────────────────────────────

    def has_url(self, url: str) -> bool:
        """Check if URL is already indexed (exact match)."""
        normalized = self._normalize(url)
        with self._lock:
            return normalized in self._by_url

    def has_hostname(self, hostname: str) -> bool:
        """Check if ANY addon from this hostname is already indexed."""
        with self._lock:
            return hostname in self._by_hostname

    def has_pattern(self, path_pattern: str) -> bool:
        """Check if this path pattern already exists (ignoring RD key)."""
        with self._lock:
            return path_pattern in self._by_pattern

    def get_by_hostname(self, hostname: str) -> list[IndexedAddon]:
        """Get all addons from a specific hostname."""
        with self._lock:
            urls = self._by_hostname.get(hostname, set())
            return [self._by_url[u] for u in urls if u in self._by_url]

    # ── Smart deduplication ───────────────────────────────────────────────

    def is_duplicate(self, url: str) -> tuple[bool, str]:
        """Check if URL is a duplicate.

        Returns (is_duplicate, reason):
          - (True, "exact") — exact URL already exists
          - (True, "hostname") — same hostname + path pattern exists
          - (True, "pattern") — same path pattern (different RD key config) exists
          - (False, "") — genuinely new addon
        """
        normalized = self._normalize(url)
        parsed = urlparse(normalized)
        hostname = parsed.netloc
        path = parsed.path.rstrip("/")

        with self._lock:
            # Exact match
            if normalized in self._by_url:
                return True, "exact"

            # Same hostname + path pattern (ignoring RD key variations)
            pattern = self._strip_variable_parts(path)
            for existing_url in self._by_hostname.get(hostname, set()):
                existing_parsed = urlparse(existing_url)
                existing_pattern = self._strip_variable_parts(existing_parsed.path.rstrip("/"))
                if pattern == existing_pattern:
                    return True, "hostname+pattern"

            # Same path pattern exists at different hostname (less strict)
            for existing_url in self._by_pattern.get(pattern, set()):
                if existing_url in self._by_url:
                    return True, "pattern"

            return False, ""

    def _strip_variable_parts(self, path: str) -> str:
        """Strip variable parts like RD keys for pattern comparison."""
        import re
        # Remove realdebrid=XXX, rd=XXX, api_key=XXX patterns
        cleaned = re.sub(r'/realdebrid=[^/]+', '/realdebrid=*', path)
        cleaned = re.sub(r'/rd=[^/]+', '/rd=*', cleaned)
        cleaned = re.sub(r'/api_key=[^/]+', '/api_key=*', cleaned)
        # Remove hex strings that look like API keys (32+ chars)
        cleaned = re.sub(r'/[a-f0-9]{32,}', '/*KEY*', cleaned)
        return cleaned

    def _normalize(self, url: str) -> str:
        """Normalize URL for consistent indexing."""
        return url.strip().rstrip("/").removesuffix("/manifest.json")

    # ── Mutations ─────────────────────────────────────────────────────────

    def add(self, url: str, is_working: bool | None = None) -> bool:
        """Add URL to index. Returns True if genuinely new, False if duplicate."""
        normalized = self._normalize(url)
        is_dup, _ = self.is_duplicate(normalized)
        if is_dup:
            return False

        parsed = urlparse(normalized)
        hostname = parsed.netloc
        path = parsed.path.rstrip("/")
        pattern = self._strip_variable_parts(path)

        addon = IndexedAddon(
            url=normalized,
            hostname=hostname,
            path_pattern=pattern,
            first_seen=datetime.now(),
            last_checked=datetime.now(),
            is_working=is_working,
        )

        with self._lock:
            self._by_url[normalized] = addon
            self._by_hostname.setdefault(hostname, set()).add(normalized)
            self._by_pattern.setdefault(pattern, set()).add(normalized)
            self._modified = True

        return True

    def mark_checked(self, url: str, is_working: bool, error: str | None = None):
        """Update addon status after a check."""
        normalized = self._normalize(url)
        with self._lock:
            if normalized in self._by_url:
                addon = self._by_url[normalized]
                addon.last_checked = datetime.now()
                addon.is_working = is_working
                if not is_working:
                    addon.consecutive_failures += 1
                    addon.last_error = error
                else:
                    addon.consecutive_failures = 0
                    addon.last_error = None

    def remove(self, url: str) -> bool:
        """Remove URL from index."""
        normalized = self._normalize(url)
        with self._lock:
            if normalized not in self._by_url:
                return False
            addon = self._by_url[normalized]
            self._by_hostname.get(addon.hostname, set()).discard(normalized)
            self._by_pattern.get(addon.path_pattern, set()).discard(normalized)
            del self._by_url[normalized]
            self._modified = True
            return True

    # ── Persistence ───────────────────────────────────────────────────────

    def to_json(self) -> list[dict]:
        """Serialize index to JSON-compatible list."""
        with self._lock:
            return [
                {
                    "url": a.url,
                    "hostname": a.hostname,
                    "path_pattern": a.path_pattern,
                    "first_seen": a.first_seen.isoformat(),
                    "last_checked": a.last_checked.isoformat(),
                    "is_working": a.is_working,
                    "consecutive_failures": a.consecutive_failures,
                    "last_error": a.last_error,
                }
                for a in self._by_url.values()
            ]

    @classmethod
    def from_json(cls, data: list[dict]) -> "AddonIndex":
        """Deserialize from JSON list."""
        index = cls()
        for item in data:
            addon = IndexedAddon(
                url=item["url"],
                hostname=item["hostname"],
                path_pattern=item["path_pattern"],
                first_seen=datetime.fromisoformat(item["first_seen"]),
                last_checked=datetime.fromisoformat(item["last_checked"]),
                is_working=item.get("is_working"),
                consecutive_failures=item.get("consecutive_failures", 0),
                last_error=item.get("last_error"),
            )
            index._by_url[addon.url] = addon
            index._by_hostname.setdefault(addon.hostname, set()).add(addon.url)
            index._by_pattern.setdefault(addon.path_pattern, set()).add(addon.url)
        return index
```

### 5.2 Instant File Loading with Index

**Problem**: `_extract_lines()` reads every line of `addons/addons.txt` and iterates linearly. With 1000+ lines, this is slow.

**Solution**: Load once into the index, then use in-memory lookups:

```python
# collect/addon_index.py additions

class AddonIndex:
    # ... existing code ...

    def load_from_file(self, filepath: str) -> int:
        """Load all URLs from file into index. Returns count of new URLs."""
        from urllib.parse import unquote
        new_count = 0
        with open(filepath, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and stripped.startswith("http"):
                    url = unquote(stripped)
                    if self.add(url):
                        new_count += 1
        return new_count

    def save_to_file(self, filepath: str) -> None:
        """Save index to file (only working addons)."""
        with open(filepath, "w") as f:
            f.write("# Py-Stremio addon manifest URLs\n")
            f.write(f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("# Auto-generated by AddonIndex\n\n")
            for addon in sorted(self._by_url.values(), key=lambda a: a.hostname):
                if addon.is_working or addon.is_working is None:
                    f.write(f"{addon.url}\n")

    def get_all_urls(self) -> list[str]:
        """Get all indexed URLs as list (for searching)."""
        with self._lock:
            return list(self._by_url.keys())

    def get_working_urls(self) -> list[str]:
        """Get only addons confirmed to work."""
        with self._lock:
            return [
                a.url for a in self._by_url.values()
                if a.is_working is True
            ]

    def get_untested_urls(self) -> list[str]:
        """Get addons never tested (is_working is None)."""
        with self._lock:
            return [
                a.url for a in self._by_url.values()
                if a.is_working is None
            ]
```

### 5.3 Smart Deduplication Logic

**Problem**: Current deduplication only checks exact URL matches. A URL with `realdebrid=KEY1` vs `realdebrid=KEY2` are treated as different even though they're the same addon.

**Solution**: Hostname + Path Pattern matching:

```python
# Smart deduplication rules:

# Rule 1: Exact URL match → SKIP (always)
if url == existing_url:
    skip

# Rule 2: Same hostname + same path pattern (ignoring RD key) → SKIP
if new.hostname == existing.hostname and new.pattern == existing.pattern:
    skip

# Rule 3: Same path pattern at different hostname → WARN (might be mirror, add anyway)
if new.pattern == existing.pattern:
    add_with_warning(f"Similar pattern exists at {existing.hostname}")

# Rule 4: Same hostname, different path → OK (different config of same provider)
if new.hostname == existing.hostname:
    add
```

```python
# Example deduplication decisions:
# ─────────────────────────────────────────────────────────────────────
# Existing: https://torrentio.strem.fun/realdebrid=KEY1/
# New:      https://torrentio.strem.fun/realdebrid=KEY2/
# Decision: SKIP — same hostname + pattern (different RD key)
# ─────────────────────────────────────────────────────────────────────
# Existing: https://torrentio.strem.fun/lite/
# New:      https://torrentio.strem.fun/sort=seeders/
# Decision: ADD — same hostname, different path pattern
# ─────────────────────────────────────────────────────────────────────
# Existing: https://mediafusion.elfhosted.com/
# New:      https://mediafusion.123456789.workers.dev/
# Decision: SKIP — likely same addon, different hosting
# ─────────────────────────────────────────────────────────────────────
```

### 5.4 AI-Powered Addon Discovery

**Problem**: Current discovery only scrapes known sources. AI can find patterns and predict new addon URLs.

**Solution**: Use AI to analyze existing addons and predict new ones:

```python
# collect/ai_discovery.py

from dataclasses import dataclass
from typing import Generator

@dataclass
class DiscoveredAddon:
    url: str
    confidence: float           # 0.0 - 1.0
    reasoning: str              # Why AI thinks this exists
    source_pattern: str         # What pattern was found

class AIDiscovery:
    """Use AI to discover new addon sources."""

    def __init__(self, index: AddonIndex):
        self.index = index
        self.known_patterns = self._analyze_patterns()

    def _analyze_patterns(self) -> dict[str, list[str]]:
        """Extract common URL patterns from existing addons."""
        patterns: dict[str, list[str]] = {}
        for addon in self.index.get_all_urls():
            hostname = self._extract_base_hostname(addon)
            path_pattern = self._extract_path_pattern(addon)

            key = f"{hostname}/{path_pattern}"
            patterns.setdefault(key, []).append(addon)
        return patterns

    def _extract_base_hostname(self, url: str) -> str:
        """Extract base hostname (ignore subdomains)."""
        from urllib.parse import urlparse
        parts = urlparse(url).netloc.split(".")
        if len(parts) >= 3:
            # e.g., abc123-torrentio.baby-beamup.club → baby-beamup.club
            # e.g., mediafusion.elfhosted.com → elfhosted.com
            if parts[-2] in ("com", "io", "net", "org", "fun"):
                return ".".join(parts[-3:]) if len(parts) > 3 else ".".join(parts)
        return ".".join(parts[-2:])

    def _extract_path_pattern(self, url: str) -> str:
        """Extract path pattern without variable parts."""
        from urllib.parse import urlparse
        path = urlparse(url).path.rstrip("/")
        # Remove known variable segments
        import re
        path = re.sub(r'/[a-f0-9]{32,}', '/*KEY*/', path)
        path = re.sub(r'/realdebrid=[^/]+', '/*RD*/', path)
        path = re.sub(r'/sort=[^/]+', '/*SORT*/', path)
        return path

    def predict_addon_urls(self) -> Generator[DiscoveredAddon, None, None]:
        """Use AI patterns to predict potential addon URLs."""

        # Pattern 1: ElfHosted has many addons at *.elfhosted.com
        elfhosted_patterns = [
            "comet", "cometnet", "mediafusion", "easynewsplus",
            "stremify", "jackettio", "aiostreams", "annatar",
            "archivio", "shluflix", "aiolists", "aiomanager",
            "aiometadata", "aioratings", "discussio", "frenchio",
            "itsout", "mytrakt", "posters-plus", "rating-aggregator",
            "streailer", "submaker", "toast-translator", "watchly",
        ]
        for name in elfhosted_patterns:
            url = f"https://{name}.elfhosted.com"
            if not self.index.has_hostname("elfhosted.com"):
                yield DiscoveredAddon(
                    url=url,
                    confidence=0.9,
                    reasoning=f"ElfHosted pattern known: {name}",
                    source_pattern="elfhosted"
                )

        # Pattern 2: baby-beamup.club uses hash-name format
        known_prefixes = [
            "2ecbbd610840", "7a82163c306e", "94c8cb9f702d",
            "1fe84bc728af", "5db836ec3ef8", "3b4bbf5252c4",
        ]
        known_names = [
            "torrentio", "mediafusion", "comet", "easynews",
            "anime-kitsu", "hanime", "brazuca-torrents",
        ]
        for prefix in known_prefixes:
            for name in known_names:
                url = f"https://{prefix}-{name}.baby-beamup.club/"
                if not self.index.has_url(url):
                    yield DiscoveredAddon(
                        url=url,
                        confidence=0.7,
                        reasoning=f"baby-beamup.club pattern: {prefix}-{name}",
                        source_pattern="beamup"
                    )

        # Pattern 3: Cloud hosting platforms (vercel, render, etc.)
        platforms = [
            ("vercel.app", "https://{name}.vercel.app"),
            ("onrender.com", "https://{name}.onrender.com"),
            ("koyeb.app", "https://{name}.koyeb.app"),
            ("workers.dev", "https://{name}.workers.dev"),
            ("pages.dev", "https://{name}.pages.dev"),
        ]
        common_addon_names = [
            "latinmovies", "ftv-stremio", "stremio-greek-tv",
            "mal-stremio", "stremioaddon", "addon-marvel",
            "dindz-addon", "stremiohebsubs", "hfreemiumy",
        ]
        for platform, template in platforms:
            for name in common_addon_names:
                url = template.format(name=name)
                if not self.index.has_url(url) and not self.index.has_hostname(platform):
                    yield DiscoveredAddon(
                        url=url,
                        confidence=0.6,
                        reasoning=f"Cloud hosting pattern on {platform}: {name}",
                        source_pattern="cloud"
                    )

    def analyze_community_recommendations(self, text: str) -> Generator[DiscoveredAddon, None, None]:
        """Extract addon URLs from community text (Reddit, Discord, etc.)."""
        import re
        # Match URLs that look like Stremio addon endpoints
        url_pattern = r'https?://[^\s<>"\'\]]+(?:manifest\.json)?[^\s<>"\'\]]*'
        for match in re.finditer(url_pattern, text):
            url = match.group(0).rstrip("/")
            if "/manifest.json" in url:
                url = url.replace("/manifest.json", "")

            # Skip if already indexed
            if self.index.has_url(url):
                continue

            # Skip non-addon URLs
            skip_domains = {"github.com", "reddit.com", "strem.io", "google.com",
                          "youtube.com", "twitter.com", "discord.com"}
            parsed = urlparse(url)
            if parsed.netloc in skip_domains:
                continue

            # Try to determine confidence based on context
            confidence = 0.5  # Default
            if "torrentio" in url.lower():
                confidence = 0.9
            elif "mediafusion" in url.lower():
                confidence = 0.9
            elif "comet" in url.lower():
                confidence = 0.9
            elif "elfhosted" in url.lower():
                confidence = 0.8
            elif "strem.fun" in url.lower():
                confidence = 0.8

            yield DiscoveredAddon(
                url=url,
                confidence=confidence,
                reasoning="Extracted from community recommendation",
                source_pattern="community"
            )
```

### 5.5 Incremental Update Strategy

**Problem**: Every discovery run re-checks ALL addons, even ones that were recently validated.

**Solution**: Only check NEW or UNTESTED addons:

```python
# collect/incremental_discovery.py

class IncrementalDiscovery:
    """Only discover and validate NEW addons, skip known-working ones."""

    def __init__(self, index: AddonIndex):
        self.index = index
        self._last_full_scan: datetime | None = None

    def discover_new_addons(self) -> list[str]:
        """Discover only genuinely new addon URLs."""
        from .sources import run_all_sources

        all_sources_urls = run_all_sources(verbose=False).urls
        new_urls = []

        for url in all_sources_urls:
            # O(1) check instead of O(n) file scan
            if self.index.add(url):  # add() returns False if duplicate
                new_urls.append(url)

        return new_urls

    def validate_only_untested(self, filepath: str) -> tuple[list[str], list[str]]:
        """Only validate addons that have is_working=None."""
        untested = self.index.get_untested_urls()
        if not untested:
            return [], []

        # Validate only untested addons
        working, failed = validate_addons(untested)

        # Update index
        for url in working:
            self.index.mark_checked(url, is_working=True)
        for url in failed:
            self.index.mark_checked(url, is_working=False)

        return working, failed

    def quick_status_check(self) -> dict[str, int]:
        """Get count of addons in each state (instant, no I/O)."""
        all_urls = self.index.get_all_urls()
        return {
            "total": len(all_urls),
            "working": len(self.index.get_working_urls()),
            "untested": len(self.index.get_untested_urls()),
            "failed": sum(
                1 for a in self.index._by_url.values()
                if a.is_working is False
            ),
        }
```

### 5.6 Fast Search Integration

**Problem**: Finding a specific file or checking if an addon exists is slow.

**Solution**: Integrate the index with all search operations:

```python
# addons/manager.py additions

class AddonManager:
    # ... existing code ...

    def find_addon_by_url(self, url: str) -> BaseAddon | None:
        """O(1) lookup of addon by URL."""
        normalized = normalize_manifest_url(url)
        return self._url_to_addon.get(normalized)

    def find_addons_by_hostname(self, hostname: str) -> list[BaseAddon]:
        """Find all addons from a specific hostname."""
        return [
            addon for addon in self.addons
            if urlparse(addon.get_url()).netloc == hostname
        ]

    def is_addon_known(self, url: str) -> bool:
        """Check if addon URL is in our known inventory."""
        return self.index.has_url(url) if hasattr(self, 'index') else False
```

---

## Implementation Roadmap

### Phase 1: Multi-Debrid Support (Weeks 1-2)

- [ ] Create `BaseDebridProvider` abstract class
- [ ] Implement `PremiumizeProvider` (most similar to RD)
- [ ] Implement `AllDebridProvider`
- [ ] Create `MultiDebridResolver` with parallel resolution
- [ ] Add environment variables for new API keys
- [ ] Add settings UI for debrid service priority

### Phase 2: Enhanced Addon Discovery (Weeks 3-4)

- [ ] Add Reddit/community scraper sources
- [ ] Implement addon scoring system
- [ ] Add regional addon affinity classification
- [ ] Implement content-aware search routing
- [ ] Add live discovery for new hosting patterns

### Phase 2b: Fast & Smart Indexing (Weeks 3-4)

- [ ] Create `AddonIndex` class with O(1) lookups
- [ ] Implement persistent in-memory index with thread-safe operations
- [ ] Add hostname + path pattern deduplication
- [ ] Create index persistence (JSON load/save)
- [ ] Implement `load_from_file()` for instant file loading
- [ ] Add AI-powered addon discovery (`AIDiscovery` class)
- [ ] Implement incremental update strategy
- [ ] Integrate index with `AddonManager`
- [ ] Add fast status check without I/O

### Phase 3: Hybrid Download Path (Weeks 5-6)

- [ ] Add WebTorrent as last-resort fallback
- [ ] Implement enhanced torrent proxy manager
- [ ] Add multi-source combining for partial downloads
- [ ] Implement proxy round-robin with health checking

### Phase 4: Adaptive Discovery (Weeks 7-8) — Now Pillar 4

- [ ] Implement continuous addon health monitoring
- [ ] Add progressive search tiers
- [ ] Make experimental addons proactive tier
- [ ] Implement dynamic re-discovery on failures

### Phase 5: Integration & Polish (Weeks 9-10)

- [ ] Wire `AddonIndex` into all addon file operations
- [ ] Replace `merge_new_addons()` with index-based merging
- [ ] Replace `_extract_lines()` with index loading
- [ ] Add `--index-status` CLI command for instant inventory overview
- [ ] Add `--index-update` CLI command for AI-powered discovery
- [ ] Performance test: verify O(1) lookups vs O(n) file scans

---

## Anti-Gaps Checklist

Use this checklist when a download fails to diagnose the issue:

- [ ] **Debrid coverage**: Are ALL configured debrid services failing, or just one?
- [ ] **Addon diversity**: Did we try addons from at least 3 different hosts?
- [ ] **Regional coverage**: Did we try region-specific addons for the content's origin?
- [ ] **Quality flexibility**: Did we try all quality levels (4K, 1080p, 720p, 480p, ANY)?
- [ ] **Language flexibility**: Did we try original audio + dubbed tracks?
- [ ] **Info hash vs direct URL**: Did we try both torrent (via RD) and direct streams?
- [ ] **Experimental tier**: Was the experimental addon tier searched?
- [ ] **Fresh discovery**: Should we run a live discovery pass?
- [ ] **Index status**: Is the addon index up-to-date (`py-stremio --index-status`)?
- [ ] **Duplicate check**: Did we verify the addon isn't already indexed before adding?
- [ ] **AI discovery**: Have we run AI-powered discovery recently (`--index-update --ai`)?

---

## Environment Variables for Maximum Coverage

```env
# Multi-Debrid Configuration
REAL_DEBRID_API_KEY=your_rd_key
PREMIUMIZE_API_KEY=your_premiumize_key
ALLDEBRID_API_KEY=your_alldebrid_key
DEBRID_LINK_API_KEY=your_debridlink_key
OFFCLOUD_API_KEY=your_offcloud_key

# Primary and fallback chain
PRIMARY_DEBRID=realdebrid
DEBRID_FALLBACK_CHAIN=premiumize,alldebrid

# Enhanced Discovery
ENABLE_LIVE_DISCOVERY=true
ENABLE_EXPERIMENTAL_ADDONS=true
EXPERIMENTAL_ADDONS_ENABLED=true
ENABLE_CONTENT_AWARE_SEARCH=true
ENABLE_AI_DISCOVERY=true

# Torrent Proxy (multiple comma-separated)
TORRENT_PROXY_URL=https://proxy1.example.com,https://proxy2.example.com

# WebTorrent fallback
ENABLE_WEBTORRENT_FALLBACK=true
WEBTORRENT_SEED_TIME_LIMIT=300

# Regional preferences (helps content-aware search)
PREFERRED_REGIONS=japanese,korean,international
PREFERRED_CONTENT_TYPES=anime,movie,series

# Performance
MAX_CONCURRENT_DEBRID_RESOLVES=3
ADDON_TIMEOUT_SECONDS=15
ADDON_INDEX_CACHE_FILE=.addon_index.json
```

---

## Summary: Never Be Stuck Again

The key to universal download coverage is **redundancy at every layer**:

1. **Many debrid services** — If RealDebrid fails, Premiumize or AllDebrid might succeed
2. **Many addons** — If Torrentio has no streams, MediaFusion or regional addons might
3. **Many qualities** — If 4K fails, 1080p or 480p might work
4. **Many languages** — If English fails, original audio or dubbed might work
5. **Many hosts** — If direct HTTP fails, RD or torrent proxy might work
6. **Many proxy options** — Round-robin through multiple torrent proxies
7. **Many tiers of addons** — Built-in → Regional → Experimental → Live Discovery
8. **Fast & Smart Indexing** — O(1) lookups, zero duplicates, AI-powered discovery

By implementing all five pillars, py-stremio transforms from a tool that works well when everything cooperates into a tool that **refuses to fail** when faced with difficult content. The Fast & Smart Indexing pillar ensures operations stay fast even with 1000+ addons, and the AI-powered discovery continuously finds new sources without manual intervention.

---

*Document version: 1.1*
*Last updated: 2026-08-06*
