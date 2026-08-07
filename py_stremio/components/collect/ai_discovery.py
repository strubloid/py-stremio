"""AI-powered addon discovery using pattern analysis.

Analyzes existing addon URLs to extract patterns and predict potential
new addon URLs on various hosting platforms.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generator, Iterator
from urllib.parse import urlparse

from .addon_index import AddonIndex, get_addon_index


@dataclass
class DiscoveredAddon:
    url: str
    confidence: float
    reasoning: str
    source_pattern: str
    discovered_at: datetime = field(default_factory=datetime.now)


class AIDiscovery:
    """Use AI patterns to discover new addon sources.

    Analyzes existing addon URLs to extract common patterns across:
    - Hosting platforms (elfhosted.com, vercel.app, etc.)
    - URL path structures
    - Addon naming conventions

    Then generates predicted addon URLs that follow these patterns.
    """

    ELFOSTED_NAMES = [
        "comet", "cometnet", "mediafusion", "easynewsplus",
        "stremify", "jackettio", "aiostreams", "annatar",
        "archivio", "shluflix", "aiolists", "aiomanager",
        "aiometadata", "aioratings", "discussio", "frenchio",
        "itsout", "mytrakt", "posters-plus", "rating-aggregator",
        "streailer", "submaker", "toast-translator", "watchly",
        "cinemanage", "streamvix", "vidfastpro", "nebula",
        "cin", "torrin", "cinetorrent", "orion", "nucleus",
        "peerflix", "debridsearch", "supreme", "till", "cinescrape",
    ]

    BEAMUP_PREFIXES = [
        "2ecbbd610840", "7a82163c306e", "94c8cb9f702d", "1fe84bc728af",
        "5db836ec3ef8", "3b4bbf5252c4", "a0da031547f5", "23dfbfad8cb2",
        "24dfd6fd4287", "32d94ecc2689", "150203dd784e", "0a5433015240",
        "27a5b2bfe3c0", "5a0d1888fa64", "61ab9c85a149", "68d69db7dc40",
        "72059fbbd1e5", "848b3516657c", "86f0740f37f6", "b89262c192b0",
        "c73485b8a7a2", "d89fade85628", "ea627ddf0ee7", "f14b294b7a6d",
        "f7094476a780", "07b88951aaab", "56bca7d190fc",
    ]

    BEAMUP_NAMES = [
        "torrentio", "mediafusion", "comet", "easynews", "anime-kitsu",
        "hanime", "brazuca-torrents", "stremio-mainelocalnews", "superflix",
        "aio-streaming", "brazuca-torrents", "dubbindo", "consumet-anime",
        "kickass-addon", "easynews-addon", "addic7ed", "podnapisi",
        "napflix", "stremio-ar", "syncribullet", "rottentomatoes",
        "jaxxx-v2", "javjt", "rpdb", "consumet-addon",
    ]

    CLOUD_PLATFORMS = [
        ("vercel.app", "https://{name}.vercel.app"),
        ("onrender.com", "https://{name}.onrender.com"),
        ("koyeb.app", "https://{name}.koyeb.app"),
        ("workers.dev", "https://{name}.workers.dev"),
        ("pages.dev", "https://{name}.pages.dev"),
        ("surge.sh", "https://{name}.surge.sh"),
    ]

    CLOUD_ADDON_NAMES = [
        "latinmovies", "ftv-stremio", "stremio-greek-tv", "mal-stremio",
        "stremioaddon", "addon-marvel", "dindz-addon", "stremiohebsubs",
        "hfreemiumy", "heiregby", "letterbot", "stremio-tv",
        "noodlestv", "stremio-sport", "stremthru", "hdhub",
        "torrin", "peerflix", "thepiratebay-plus", "anime-kitsu",
    ]

    STREMIO_FUN_ADDONS = [
        "torrentio", "anime-kitsu", "thepiratebay-plus",
    ]

    STREMIO_FUN_VARIANTS = [
        "", "/lite", "/sort=seeders", "/sort=size", "/sort=quality",
    ]

    def __init__(self, index: AddonIndex | None = None):
        self.index = index or get_addon_index()
        self._known_base_hostnames: set[str] = set()
        self._analyze_base_hostnames()

    def _analyze_base_hostnames(self):
        """Extract base hostnames from existing addons."""
        for url in self.index.get_all_urls():
            base = self._extract_base_hostname(url)
            self._known_base_hostnames.add(base)

    def _extract_base_hostname(self, url: str) -> str:
        """Extract base hostname (ignore subdomains)."""
        parts = urlparse(url).netloc.split(".")
        if len(parts) >= 3:
            if parts[-2] in ("com", "io", "net", "org", "fun"):
                return ".".join(parts[-3:]) if len(parts) > 3 else ".".join(parts)
        return ".".join(parts[-2:])

    def _extract_path_pattern(self, url: str) -> str:
        """Extract path pattern without variable parts."""
        path = urlparse(url).path.rstrip("/")
        path = re.sub(r"/[a-f0-9]{32,}", "/*KEY*/", path)
        path = re.sub(r"/realdebrid=[^/]+", "/*RD*/", path)
        path = re.sub(r"/sort=[^/]+", "/*SORT*/", path)
        path = re.sub(r"/rd=[^/]+", "/*RD*/", path)
        return path

    def is_hostname_known(self, hostname: str) -> bool:
        """Check if we already know about this base hostname."""
        base = self._extract_base_hostname(f"https://{hostname}")
        return base in self._known_base_hostnames

    def is_url_known(self, url: str) -> bool:
        """Check if URL is already in index."""
        return self.index.has_url(url)

    def predict_elfhosted(self) -> Generator[DiscoveredAddon, None, None]:
        """Predict ElfHosted addon URLs based on known patterns."""
        for name in self.ELFOSTED_NAMES:
            url = f"https://{name}.elfhosted.com"
            if not self.is_url_known(url) and not self.is_hostname_known("elfhosted.com"):
                yield DiscoveredAddon(
                    url=url,
                    confidence=0.9,
                    reasoning=f"ElfHosted pattern known: {name}.elfhosted.com is a standard hosting pattern",
                    source_pattern="elfhosted",
                )

    def predict_beamup(self) -> Generator[DiscoveredAddon, None, None]:
        """Predict baby-beamup.club addon URLs."""
        for prefix in self.BEAMUP_PREFIXES:
            for name in self.BEAMUP_NAMES:
                url = f"https://{prefix}-{name}.baby-beamup.club/"
                if not self.is_url_known(url) and not self.is_hostname_known("baby-beamup.club"):
                    yield DiscoveredAddon(
                        url=url,
                        confidence=0.7,
                        reasoning=f"baby-beamup.club pattern: {prefix}-{name}",
                        source_pattern="beamup",
                    )

    def predict_cloud_hosting(self) -> Generator[DiscoveredAddon, None, None]:
        """Predict cloud-hosted addon URLs."""
        for platform, template in self.CLOUD_PLATFORMS:
            for name in self.CLOUD_ADDON_NAMES:
                url = template.format(name=name)
                if not self.is_url_known(url) and not self.is_hostname_known(platform):
                    yield DiscoveredAddon(
                        url=url,
                        confidence=0.6,
                        reasoning=f"Cloud hosting pattern on {platform}: {name}",
                        source_pattern="cloud",
                    )

    def predict_stremio_fun(self) -> Generator[DiscoveredAddon, None, None]:
        """Predict stremio.fun addon variants."""
        base = "https://torrentio.strem.fun"
        for variant in self.STREMIO_FUN_VARIANTS:
            url = f"{base}{variant}/"
            if not self.is_url_known(url):
                variant_name = variant if variant else "base"
                yield DiscoveredAddon(
                    url=url,
                    confidence=0.95,
                    reasoning=f"Torrentio stremio.fun variant: {variant_name}",
                    source_pattern="torrentio-fun",
                )

        for name in self.STREMIO_FUN_ADDONS:
            if name == "torrentio":
                continue
            url = f"https://{name}.strem.fun"
            if not self.is_url_known(url):
                yield DiscoveredAddon(
                    url=url,
                    confidence=0.8,
                    reasoning=f"stremio.fun addon: {name}",
                    source_pattern="stremio-fun",
                )

    def predict_all(self) -> Generator[DiscoveredAddon, None, None]:
        """Generate all predicted addon URLs across all patterns."""
        yield from self.predict_elfhosted()
        yield from self.predict_beamup()
        yield from self.predict_cloud_hosting()
        yield from self.predict_stremio_fun()

    def predict_high_confidence(self) -> Generator[DiscoveredAddon, None, None]:
        """Only yield high-confidence predictions (> 0.7)."""
        for addon in self.predict_all():
            if addon.confidence >= 0.7:
                yield addon

    def analyze_community_text(self, text: str) -> Generator[DiscoveredAddon, None, None]:
        """Extract addon URLs from community text (Reddit, Discord, etc.).

        Args:
            text: Raw text content to analyze

        Yields:
            DiscoveredAddon objects for each URL found
        """
        url_pattern = r"https?://[^\s<>\"\'\]\)]+(?:manifest\.json)?[^\s<>\"\'\]\)]*"
        for match in re.finditer(url_pattern, text):
            url = match.group(0).rstrip("/")
            if "/manifest.json" in url:
                url = url.replace("/manifest.json", "")

            if self.is_url_known(url):
                continue

            skip_domains = {
                "github.com", "reddit.com", "strem.io", "google.com",
                "youtube.com", "twitter.com", "discord.com", "facebook.com",
                "instagram.com", "tiktok.com", "twitch.tv",
            }
            parsed = urlparse(url)
            if parsed.netloc in skip_domains:
                continue

            confidence = self._calculate_confidence(url)
            yield DiscoveredAddon(
                url=url,
                confidence=confidence,
                reasoning="Extracted from community recommendation",
                source_pattern="community",
            )

    def _calculate_confidence(self, url: str) -> float:
        """Calculate confidence score for a URL based on known patterns."""
        url_lower = url.lower()
        confidence = 0.5

        if "torrentio" in url_lower:
            confidence = 0.9
        elif "mediafusion" in url_lower:
            confidence = 0.9
        elif "comet" in url_lower:
            confidence = 0.9
        elif "elfhosted" in url_lower:
            confidence = 0.85
        elif "strem.fun" in url_lower:
            confidence = 0.85
        elif "anime" in url_lower and ("-kitsu" in url_lower or "pahe" in url_lower):
            confidence = 0.85
        elif "vercel.app" in url_lower or "onrender.com" in url_lower:
            confidence = 0.7
        elif "beamup.club" in url_lower:
            confidence = 0.7
        elif "workers.dev" in url_lower or "pages.dev" in url_lower:
            confidence = 0.6

        return confidence

    def discover_and_add(self) -> list[DiscoveredAddon]:
        """Discover new addons and add them to the index.

        Returns list of DiscoveredAddon objects that were added.
        """
        added = []
        for discovered in self.predict_all():
            if self.index.add(discovered.url):
                added.append(discovered)
        return added


class IncrementalDiscovery:
    """Only discover and validate NEW addons, skip known-working ones.

    Uses the AddonIndex for O(1) duplicate detection instead of O(n) file scans.
    """

    def __init__(self, index: AddonIndex | None = None):
        self.index = index or get_addon_index()
        self.ai_discovery = AIDiscovery(self.index)

    def discover_new_addons(self) -> list[str]:
        """Discover only genuinely new addon URLs from all sources.

        Uses O(1) index lookups instead of O(n) file scans.
        """
        from .sources import run_all_sources

        result = run_all_sources(verbose=False)
        new_urls = []

        for url in result.urls:
            if self.index.add(url):
                new_urls.append(url)

        return new_urls

    def discover_via_ai(self) -> list[DiscoveredAddon]:
        """Use AI pattern analysis to discover new addon URLs."""
        return self.ai_discovery.discover_and_add()

    def validate_only_untested(self, urls: list[str] | None = None) -> tuple[list[str], list[str]]:
        """Validate only addons that have is_working=None.

        Args:
            urls: Optional list of URLs to validate. If None, validates all untested.

        Returns:
            (working_urls, failed_urls)
        """
        from py_stremio.components.addons.addon_validator import check_addon_url
        from py_stremio.components.configs.app_settings import settings

        if urls is None:
            urls = self.index.get_untested_urls()

        if not urls:
            return [], []

        working = []
        failed = []
        api_key = settings.REAL_DEBRID_API_KEY

        for url in urls:
            result = check_addon_url(url, api_key)
            if result["manifest_ok"] or result["streams_found"] > 0:
                self.index.mark_working(url)
                working.append(url)
            else:
                self.index.mark_failed(url, result.get("error"))
                failed.append(url)

        return working, failed

    def quick_status(self) -> dict:
        """Get count of addons in each state (instant, no I/O)."""
        return self.index.quick_status()

    def sync_from_file(self, filepath: str) -> int:
        """Load addons from file into index, returning count of new addons."""
        return self.index.load_from_file(filepath)

    def get_new_urls_since(self, since: datetime) -> list[str]:
        """Get URLs added to index since a given time."""
        return [
            a.url for a in self.index.iter_addons()
            if a.first_seen >= since
        ]
