"""Scrape addon manifest URLs from known Stremio addon sources."""

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass, field
from urllib.parse import urlparse

from py_stremio.components.configs.app_settings import settings

# ── HTTP helpers ──────────────────────────────────────────────────────────

_HDR = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _fetch(url: str, timeout: int = 10) -> tuple[int | None, bytes | None]:
    try:
        req = urllib.request.Request(url, headers=_HDR)
        r = urllib.request.urlopen(req, timeout=timeout, context=_CTX)
        return r.status, r.read()
    except Exception:
        return None, None


# ── Source config ─────────────────────────────────────────────────────────

SORTS = ["seeders", "size", "quality"]


@dataclass
class SourceResult:
    """Result from a single addon source."""
    name: str
    urls: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


# ── 1. GitHub community addons issue thread ──────────────────────────────

def scrape_github_issues() -> set[str]:
    """Scrape Stremio addon URLs from the community issue thread."""
    urls: set[str] = set()
    for page in range(1, 21):  # up to 20 pages
        html_url = f"https://github.com/Stremio/addons/issues?page={page}&q=is%3Aissue+is%3Aopen"
        status, data = _fetch(html_url, timeout=8)
        if status != 200 or not data:
            break
        html = data.decode("utf-8", errors="replace")
        # Find issue links
        issue_ids = re.findall(r'/Stremio/addons/issues/(\d+)', html)
        for iid in set(issue_ids):
            status2, data2 = _fetch(
                f"https://raw.githubusercontent.com/Stremio/addons/main/.github/ISSUE_TEMPLATE/{iid}.yml",
                timeout=5
            )
            if status2 == 200 and data2:
                found = re.findall(r'https?://[^\s\"\'<>]+', data2.decode("utf-8", errors="replace"))
                for u in found:
                    u = u.rstrip("/.,;:)'\"")
                    if "stremio" in u.lower() or "manifest.json" in u.lower() or ".fun" in u or ".app" in u:
                        urls.add(u)
            # Also scrape the issue HTML page
            time.sleep(0.3)
    return urls


# ── 2. stremio-addons.net catalog ────────────────────────────────────────

def scrape_stremio_addons_net() -> set[str]:
    """Scrape addon URLs from stremio-addons.net."""
    urls: set[str] = set()
    for page in range(1, 6):
        catalog_url = f"https://stremio-addons.net/api/addons?page={page}&limit=100"
        status, data = _fetch(catalog_url, timeout=8)
        if status != 200 or not data:
            continue
        try:
            entries = json.loads(data.decode())
            for entry in entries:
                transport_url = entry.get("transportUrl", "") or entry.get("url", "")
                if transport_url and transport_url.startswith("http"):
                    urls.add(transport_url.rstrip("/"))
        except (json.JSONDecodeError, TypeError):
            pass
    return urls


# ── 3. Torrentio configuration variants ──────────────────────────────────

def gen_torrentio_variants() -> set[str]:
    """Generate core Torrentio instances — no language/sort spam, just different backends."""
    urls: set[str] = set()
    base = "https://torrentio.strem.fun"

    # Core Torrentio entries: base, lite, sort=seeders, plus RD only when
    # configured from the user's environment. Never embed a static RD key in
    # source or addons.txt.
    urls.add(f"{base}/")
    urls.add(f"{base}/lite/")
    urls.add(f"{base}/sort=seeders/")
    if settings.REAL_DEBRID_API_KEY:
        urls.add(f"{base}/realdebrid={settings.REAL_DEBRID_API_KEY}/")

    return urls


# ── 4. ElfHosted ecosystem ───────────────────────────────────────────────

def gen_elfhosted_addons() -> set[str]:
    """Known addon instances on elfhosted.com.

    Note: KnightCrawler was removed in 2026 (deprecated / redirected).
    Use Comet, CometNet, MediaFusion or EasyNews+ as replacements.
    """
    return {
        # ── Stream scrapers / debrid aggregators ──────────────────────────
        "https://mediafusion.elfhosted.com",
        "https://comet.elfhosted.com",
        "https://cometnet.elfhosted.com",
        "https://easynewsplus.elfhosted.com",
        "https://stremify.elfhosted.com",
        "https://jackettio.elfhosted.com",
        "https://aiostreams.elfhosted.com",
        # ── Other services ────────────────────────────────────────────────
        "https://stremio-jackett.elfhosted.com",
        "https://annatar.elfhosted.com",
        "https://archivio.elfhosted.com",
        "https://shluflix.elfhosted.com",
        "https://aiolists.elfhosted.com",
        "https://aiomanager.elfhosted.com",
        "https://aiometadata.elfhosted.com",
        "https://aioratings.elfhosted.com",
        "https://discussio.elfhosted.com",
        "https://frenchio.elfhosted.com",
        "https://itsout.elfhosted.com",
        "https://mytrakt.elfhosted.com",
        "https://posters-plus.elfhosted.com",
        "https://rating-aggregator.elfhosted.com",
        "https://streailer.elfhosted.com",
        "https://submaker.elfhosted.com",
        "https://toast-translator.elfhosted.com",
        "https://watchly.elfhosted.com",
    }

# ── 4b. ElfHosted guide scraper ───────────────────────────────────────

def scrape_elfhosted_guide() -> set[str]:
    """Fetch the ElfHosted Stremio Addons Guide and extract addon URLs.

    Iterates known addon-name patterns from the page and tests for
    a valid ``/manifest.json``.  Cache-friendly single-page fetch.
    """
    guide_url = "https://stremio-addons-guide.elfhosted.com"
    status, data = _fetch(guide_url, timeout=10)
    if status != 200 or not data:
        return set()

    html = data.decode("utf-8", errors="replace")

    # Extract addon names between link tags on the list
    names: set[str] = set()
    for m in re.finditer(
        r'<a[^>]*href=["\']/addons/([^"\']+)["\'][^>]*>([^<]+)</a>',
        html,
    ):
        slug = m.group(1).strip()
        if slug:
            names.add(slug)

    # Also scrape for any manifest.json links directly
    for m in re.finditer(r'https?://[^"\'\s<>]+manifest\.json[^"\'\s<>]*', html):
        names.add(m.group(0).rstrip("/").replace("/manifest.json", ""))

    # Build candidate URLs and keep only those with valid manifests
    urls: set[str] = set()
    for slug in names:
        candidate = f"https://{slug}.elfhosted.com"
        cstatus, _ = _fetch(f"{candidate}/manifest.json", timeout=5)
        if cstatus == 200:
            urls.add(candidate)
        # Also try sub-path for addons at /stremio/manifest.json
        cstatus2, _ = _fetch(f"{candidate}/stremio/manifest.json", timeout=5)
        if cstatus2 == 200:
            urls.add(f"{candidate}/stremio")

    return urls


# ── 5. Known baby-beamup.club prefixes + names ──────────────────────────

def gen_beamup_addons() -> set[str]:
    """All known baby-beamup.club addon instances."""
    urls: set[str] = set()
    prefixes = [
        "2ecbbd610840", "7a82163c306e", "94c8cb9f702d", "1fe84bc728af",
        "5db836ec3ef8", "3b4bbf5252c4", "a0da031547f5", "23dfbfad8cb2",
        "24dfd6fd4287", "32d94ecc2689", "150203dd784e", "0a5433015240",
        "27a5b2bfe3c0", "5a0d1888fa64", "61ab9c85a149", "68d69db7dc40",
        "72059fbbd1e5", "848b3516657c", "86f0740f37f6", "b89262c192b0",
        "c73485b8a7a2", "d89fade85628", "ea627ddf0ee7", "f14b294b7a6d",
        "f7094476a780", "07b88951aaab", "56bca7d190fc",
    ]
    names = [
        "opensubtitles", "subscene", "yifysubtitles", "trakt",
        "imdb-catalogs", "stremio-mdblist", "stremio-tmdb",
        "stremio-anime-catalogs", "stremio-radios", "stremio-concerts",
        "tmdb-collections", "stremio-addon-age-ratings",
        "stremio-addon-ratings", "stremio-netflix-catalog-addon",
        "tmdb-addon", "stremio-brazilian-addon", "thepiratebay-ctl",
        "debrid-search", "cinetorrent-addon", 
        "animeo", "hanime-stremio", "argentinatv",
        "stremio-mainelocalnews", "superflix", "aio-streaming",
        "brazuca-torrents", "stremio-broadcastify-usa-broadcasts",
        "dubbindo", "consumet-anime", "kickass-addon", "easynews-addon",
        "easynews", "addic7ed", "podnapisi", "napflix", "stremio-ar",
        "syncribullet", "rottentomatoes", "jaxxx-v2", "javjt",
        "rpdb", "consumet-addon", "stremio-maine-radio",
    ]
    for p in prefixes:
        for n in names:
            urls.add(f"https://{p}-{n}.baby-beamup.club/")
    return urls


# ── 6. Known cloud-hosting patterns ─────────────────────────────────────

def gen_cloud_addons() -> set[str]:
    """Addons hosted on various cloud platforms."""
    return {
        "https://stremio-greek-tv.onrender.com",
        "https://xtreampro.onrender.com",
        "https://addon-marvel.onrender.com",
        "https://dindz-addon.onrender.com",
        "https://stremiohebsubs.onrender.com",
        "https://latinmovies.vercel.app",
        "https://latinmovies2.vercel.app",
        "https://latino-movies.vercel.app",
        "https://guindex-stremio.vercel.app",
        "https://stremioaddon.vercel.app",
        "https://mal-stremio.vercel.app",
        "https://letterbot-main-rgvilis-projects.vercel.app",
        "https://ftv-stremio.surge.sh",
        "https://hfreemiumy.surge.sh",
        "https://heiregby.surge.sh",
        "https://onepaceaddon-zoropogger.koyeb.app",
        "https://addon.notorrent2.workers.dev",
        "https://stremio-sport.pages.dev",
        "https://noodlestv.pages.dev",
        "https://stremio-tv.pages.dev",
        "https://addon.peario.xyz",
        "https://stremthru.13377001.xyz",
        "https://hdhub.thevolecitor.qzz.io",
        "https://torrin.app",
        "https://peerflix.mov",
        "https://thepiratebay-plus.strem.fun",
        "https://anime-kitsu.strem.fun",
        "https://watchhub.strem.io",
        "https://caching.stremio.net/publicdomainmovies.now.sh",
        "https://cinemeta.ratingposterdb.com",
        "https://comet.feels.legal",
        "https://mycine.alwaysdata.net",
        "https://plexio.stream",
        "https://shluflix.elfhosted.com",
        "https://deeplsubtitle.sonsuzanime.com",
        "https://opensubtitles.stremio.homes",
        "https://opensubtitlesv3-pro.dexter21767.com",
        "https://stremio-simkl-backend.nktfh100.com",
        "https://stremlist.com",
        "https://serializd.almosteffective.com",
        "https://premiumize.almosteffective.com",
        "https://mubi2stremio.adiba.ro",
        "https://subtito.com",
        "https://napisy24-stremio.top",
        "https://up-next.dontwanttos.top",
        "https://victorgveloso.github.io/animes-season-addon",
        "https://www.figarocorso.info/stremio",
        "https://einthusan.asaddon.com",
        "https://stremio.itcon.au/aisearch",
        "https://stremiohebsubs.onrender.com",
    }


# ── Run all sources ──────────────────────────────────────────────────────

def run_all_sources(verbose: bool = True) -> SourceResult:
    """Collect addon URLs from every known source.

    Returns a SourceResult with all unique URLs found.
    """
    result = SourceResult(name="all")
    generators = [
        ("GitHub issues (HTML)", scrape_github_issues),
        ("stremio-addons.net API", scrape_stremio_addons_net),
        ("Torrentio variants", gen_torrentio_variants),
        ("ElfHosted ecosystem", gen_elfhosted_addons),
        ("ElfHosted guide (live)", scrape_elfhosted_guide),
        ("baby-beamup.club instances", gen_beamup_addons),
        ("Cloud-hosted addons", gen_cloud_addons),
    ]

    urls = set()
    for name, fn in generators:
        try:
            found = fn()
            urls.update(found)
            if verbose:
                print(f"  {name}: {len(found)} URLs", flush=True)
        except Exception as e:
            result.errors.append(f"{name}: {e}")
            if verbose:
                print(f"  ! {name}: {e}", flush=True)

    result.urls = urls
    if verbose:
        print(f"  Total unique after dedup: {len(urls)}", flush=True)
    return result
