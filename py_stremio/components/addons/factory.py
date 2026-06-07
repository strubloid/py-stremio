"""Addon manager construction helpers."""
from urllib.parse import unquote, urlparse

from py_stremio.components.configs.app_settings import settings
from .base import UrlAddon
from .types.builtin_addons import (
    AIOStreamingAddon,
    AIOStreamsAddon,
    AkumaAddon,
    AnimeKitsuAddon,
    AnimeoAddon,
    AnimepaheAddon,
    AnimesSeasonAddon,
    AnimeStreamAddon,
    ArgentinaTVAddon,
    BrazucaTorrentsAddon,
    CineTorrentAddon,
    CometAddon,
    CometElfHostedAddon,
    CometNetAddon,
    EasyNewsPlusAddon,
    ConsumetAddon,
    DebridSearchAddon,
    DubbindoAddon,
    EinthusanAddon,
    FShareAddon,
    FTVStremioAddon,
    FenixFlixAddon,
    FigaroCorsoAddon,
    FlixStreamsAddon,
    GreekTVAddon,
    GuindexAddon,
    HDHubAddon,
    HanimeAddon,
    HiAnimeStreamsAddon,
    JackettioAddon,
    KnightCrawlerAddon,
    LatinMoviesAddon,
    MainelocalnewsAddon,
    MediaFusionAddon,
    MicoLeaoDubladoAddon,
    MyCineAddon,
    NebulaStreamsAddon,
    NoTorrentAddon,
    NucleusAddon,
    OnePaceAddon,
    OrionAddon,
    PeerflixAddon,
    RicosStremioAddon,
    SkyflixAddon,
    StremifyAddon,
    StremThruAddon,
    StreamViXAddon,
    ThePirateBayPlusAddon,
    TorrentioAddon,
    TorrentioHindiAddon,
    TorrentioLiteAddon,
    TorrentioPortugueseAddon,
    TorrentioSortSeedersAddon,
    TorrentioSpanishAddon,
    TorrentsDBAddon,
    TorrinAddon,
    VidFastProAddon,
    VStremioAddon,
    WatchHubAddon,
    WatchioAddon,
    XtreamProAddon,
    YaStreamAddon,
    YouTubeProAddon,
    YtztvioAddon,
)
from .manager import AddonManager
from .models import StreamInfo


def load_addons_from_file(filepath: str = "addons.txt") -> list[str]:
    """Load addon URLs from file."""
    try:
        with open(filepath, "r") as f:
            return [unquote(line.strip()) for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []


def _addon_identity(url: str) -> str:
    """Return a dedupe identity for base URLs and final manifest URLs."""
    return unquote(url.strip()).rstrip("/").removesuffix("/manifest.json")


def load_addon_urls() -> list[str]:
    """Load clean addon URLs plus final Stremio manifest URLs.

    `addons.txt` remains the editable clean-base source. `addons.stremio` is a
    final-product file where each URL may point directly to `manifest.json`.
    Both are loaded, with duplicates removed by their queryable addon base.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for filepath in ("addons.stremio", "addons.txt"):
        for url in load_addons_from_file(filepath):
            identity = _addon_identity(url)
            if identity in seen:
                continue
            seen.add(identity)
            urls.append(url)
    return urls


def _register_builtin_addons(manager: AddonManager) -> None:
    """Register all built-in stream-providing addons."""

    # ── Torrentio family ──────────────────────────────────────────────────
    manager.register(TorrentioAddon())
    manager.register(TorrentioSortSeedersAddon())
    manager.register(TorrentioPortugueseAddon())
    manager.register(TorrentioSpanishAddon())
    manager.register(TorrentioHindiAddon())
    manager.register(TorrentioLiteAddon())
    manager.register(TorrentsDBAddon())

    manager.register(MediaFusionAddon())
    manager.register(KnightCrawlerAddon())
    manager.register(CometAddon())
    manager.register(CometElfHostedAddon())
    manager.register(CometNetAddon())
    manager.register(EasyNewsPlusAddon())
    manager.register(PeerflixAddon())
    manager.register(NucleusAddon())
    manager.register(OrionAddon())
    manager.register(DebridSearchAddon())
    manager.register(StremifyAddon())
    manager.register(JackettioAddon())
    manager.register(AIOStreamsAddon())
    manager.register(CineTorrentAddon())
    manager.register(TorrinAddon())
    manager.register(ThePirateBayPlusAddon())
    manager.register(StreamViXAddon())
    manager.register(FlixStreamsAddon())
    manager.register(YtztvioAddon())
    manager.register(VidFastProAddon())
    manager.register(MyCineAddon())
    manager.register(NebulaStreamsAddon())

    # ── Brazilian / Portuguese ────────────────────────────────────────────
    manager.register(BrazucaTorrentsAddon())
    manager.register(HDHubAddon())

    # ── Anime ─────────────────────────────────────────────────────────────
    manager.register(AnimeKitsuAddon())
    manager.register(AkumaAddon())
    manager.register(AnimepaheAddon())
    manager.register(AnimeoAddon())
    manager.register(OnePaceAddon())
    manager.register(HanimeAddon())
    manager.register(AnimesSeasonAddon())
    manager.register(HiAnimeStreamsAddon())
    manager.register(AnimeStreamAddon())
    manager.register(YaStreamAddon())

    # ── Free hosters / no-debrid ──────────────────────────────────────────
    manager.register(WatchHubAddon())
    manager.register(SkyflixAddon())
    manager.register(ArgentinaTVAddon())
    manager.register(GreekTVAddon())
    manager.register(XtreamProAddon())
    manager.register(AIOStreamingAddon())
    manager.register(WatchioAddon())

    # ── Regional ──────────────────────────────────────────────────────────
    manager.register(LatinMoviesAddon())
    manager.register(RicosStremioAddon())
    # manager.register(KinopubAddon())  # removed 2026-06 — Russian-only
    manager.register(FTVStremioAddon())
    manager.register(FigaroCorsoAddon())
    manager.register(EinthusanAddon())
    manager.register(VStremioAddon())
    manager.register(DubbindoAddon())
    manager.register(MainelocalnewsAddon())
    manager.register(FenixFlixAddon())
    manager.register(MicoLeaoDubladoAddon())

    # ── Other backends ────────────────────────────────────────────────────
    manager.register(NoTorrentAddon())
    manager.register(StremThruAddon())
    manager.register(GuindexAddon())
    manager.register(YouTubeProAddon())
    manager.register(FShareAddon())
    manager.register(ConsumetAddon())


def _is_covered_by_builtin(url: str, manager: AddonManager) -> bool:
    """Check if a URL from addons.txt is already covered by a built-in addon.

    Uses host (netloc) comparison so that Torrentio variants etc. loaded
    from file are skipped in favour of the built-in class, which handles
    RD key injection correctly.
    """
    url_clean = url.rstrip("/").replace("/manifest.json", "")
    parsed = urlparse(url_clean)

    for addon in manager.addons:
        addon_clean = addon.get_url(None).rstrip("/")
        addon_parsed = urlparse(addon_clean)
        if parsed.netloc == addon_parsed.netloc:
            return True
    return False


def _apply_api_key(manager: AddonManager, api_key: str | None) -> None:
    for addon in manager.addons:
        addon.api_key = api_key


def create_addon_manager() -> AddonManager:
    """Create and configure addon manager with all available addons.

    Strategy:
      1. Always register built-in addons (Torrentio, MediaFusion, Comet,
         etc.) — they handle RD key injection in their own get_url().
      2. Supplement with addons from addons.txt for any extra URLs not
         already covered by built-ins.
      3. Apply the RD key from settings to every addon.
    """
    api_key = settings.REAL_DEBRID_API_KEY
    manager = AddonManager()

    # 1. Always register built-in addons (correct RD injection)
    _register_builtin_addons(manager)

    # 2. Supplement with file addons, skipping duplicates by host
    addon_urls = load_addon_urls()
    if addon_urls:
        skipped = 0
        for url in addon_urls:
            if _is_covered_by_builtin(url, manager):
                skipped += 1
                continue
            try:
                addon = UrlAddon(url)
                addon.api_key = api_key
                manager.register(addon)
            except Exception as exc:
                from py_stremio.components.errors.error_logger import log_error

                log_error("load_addon_from_file", exc, url)
        file_total = len(addon_urls) - skipped
        if file_total:
            print(f"    Loaded {file_total} addon(s) from addon file(s)"
                  f" ({skipped} skipped, covered by built-in)")
        else:
            print(f"    All {skipped} addon(s) from addon file(s) covered by built-ins — skipped")

    # 3. Apply the RD key to all addons
    _apply_api_key(manager, api_key)
    return manager


def create_addon_manager_from_urls(urls: list[str]) -> AddonManager:
    """Create addon manager from specific URLs."""
    manager = AddonManager()
    api_key = settings.REAL_DEBRID_API_KEY

    for url in urls:
        try:
            addon = UrlAddon(url)
            addon.api_key = api_key
            manager.register(addon)
        except Exception as exc:
            from py_stremio.components.errors.error_logger import log_error

            log_error("create_manager_from_urls", exc, url)

    return manager


def search_addons(type_: str, id_: str, max_addons: int = 3) -> list[StreamInfo]:
    """Search all addons for streams."""
    manager = create_addon_manager()
    return manager.search_all(type_, id_, max_addons)
