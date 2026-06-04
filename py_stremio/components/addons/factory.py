"""Addon manager construction helpers."""
from urllib.parse import unquote

from ..settings import settings
from .base import UrlAddon
from .builtin import (
    AIOStreamingAddon,
    AIOStreamsAddon,
    AkumaAddon,
    AnimeKitsuAddon,
    AnimeoAddon,
    AnimepaheAddon,
    AnimesSeasonAddon,
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
    FigaroCorsoAddon,
    GreekTVAddon,
    GuindexAddon,
    HDHubAddon,
    HanimeAddon,
    JackettioAddon,
    KinopubAddon,
    KnightCrawlerAddon,
    LatinMoviesAddon,
    MainelocalnewsAddon,
    MediaFusionAddon,
    NoTorrentAddon,
    NucleusAddon,
    OnePaceAddon,
    OrionAddon,
    PeerflixAddon,
    RicosStremioAddon,
    SkyflixAddon,
    StremifyAddon,
    StremThruAddon,
    ThePirateBayPlusAddon,
    TorrentioAddon,
    TorrentioHindiAddon,
    TorrentioLiteAddon,
    TorrentioPortugueseAddon,
    TorrentioSortSeedersAddon,
    TorrentioSpanishAddon,
    TorrinAddon,
    VStremioAddon,
    WatchHubAddon,
    XtreamProAddon,
    YouTubeProAddon,
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


def _register_file_addons(manager: AddonManager, addon_urls: list[str]) -> None:
    for url in addon_urls:
        try:
            manager.register(UrlAddon(url))
        except Exception:
            pass


def _register_builtin_addons(manager: AddonManager, api_key: str | None) -> None:
    """Register all built-in stream-providing addons."""

    # ── Torrentio family ──────────────────────────────────────────────────
    manager.register(TorrentioAddon())
    manager.register(TorrentioSortSeedersAddon())
    manager.register(TorrentioPortugueseAddon())
    manager.register(TorrentioSpanishAddon())
    manager.register(TorrentioHindiAddon())
    manager.register(TorrentioLiteAddon())

    # ── Core torrent scrapers ─────────────────────────────────────────────
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

    # ── Free hosters / no-debrid ──────────────────────────────────────────
    manager.register(WatchHubAddon())
    manager.register(SkyflixAddon())
    manager.register(ArgentinaTVAddon())
    manager.register(GreekTVAddon())
    manager.register(XtreamProAddon())
    manager.register(AIOStreamingAddon())

    # ── Regional ──────────────────────────────────────────────────────────
    manager.register(LatinMoviesAddon())
    manager.register(RicosStremioAddon())
    manager.register(KinopubAddon())
    manager.register(FTVStremioAddon())
    manager.register(FigaroCorsoAddon())
    manager.register(EinthusanAddon())
    manager.register(VStremioAddon())
    manager.register(DubbindoAddon())
    manager.register(MainelocalnewsAddon())

    # ── Other backends ────────────────────────────────────────────────────
    manager.register(NoTorrentAddon())
    manager.register(StremThruAddon())
    manager.register(GuindexAddon())
    manager.register(YouTubeProAddon())
    manager.register(FShareAddon())
    manager.register(ConsumetAddon())

    # ── RD-keyed variant (only when key present) ──────────────────────────
    if api_key:
        manager.register(TorrentioPortugueseAddon())


def _apply_api_key(manager: AddonManager, api_key: str | None) -> None:
    for addon in manager.addons:
        addon.api_key = api_key


def create_addon_manager() -> AddonManager:
    """Create and configure addon manager with all available addons."""
    api_key = settings.REAL_DEBRID_API_KEY
    manager = AddonManager()
    addon_urls = load_addons_from_file("addons.txt")

    if addon_urls:
        print(f"    Loading {len(addon_urls)} addons from addons.txt...")
        _register_file_addons(manager, addon_urls)
    else:
        _register_builtin_addons(manager, api_key)

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
        except Exception:
            pass

    return manager


def search_addons(type_: str, id_: str, max_addons: int = 3) -> list[StreamInfo]:
    """Search all addons for streams."""
    manager = create_addon_manager()
    return manager.search_all(type_, id_, max_addons)
