"""Re-export all builtin addon classes.

This module exists for backward compatibility — factory.py and __init__.py import
directly from .types.builtin_addons.  Each addon class now lives in its own
logical file under types/, and this module globs them together so existing
import paths keep working.

New addons with custom URL logic  → add a new file in types/ (e.g. anime.py)
New simple addons                 → add an AddonDef to addon_registry.py
"""

# ── Torrentio family ──────────────────────────────────────────────────────────
from .torrentio_family import (
    TorrentioAddon,
    TorrentioSortSeedersAddon,
    TorrentioPortugueseAddon,
    TorrentioSpanishAddon,
    TorrentioHindiAddon,
    TorrentioLiteAddon,
    TorrentsDBAddon,
)

# ── Comet / HDHub / StremThru / Brazuca / Guindex ────────────────────────────
from .comet_family import (
    CometAddon,
    CometElfHostedAddon,
    CometNetAddon,
    HDHubAddon,
    StremThruAddon,
    BrazucaTorrentsAddon,
    GuindexAddon,
)

# ── Major aggregators ────────────────────────────────────────────────────────
from .aggregators import (
    AIOStreamsAddon,
    CinAddon,
    CineTorrentAddon,
    CinescrapeAddon,
    DebridSearchAddon,
    EasyNewsPlusAddon,
    FlixStreamsAddon,
    JackettioAddon,
    KnightCrawlerAddon,
    KodAddon,
    MediaFusionAddon,
    MyCineAddon,
    NebulaStreamsAddon,
    NucleusAddon,
    OrionAddon,
    PeerflixAddon,
    StremifyAddon,
    StreamViXAddon,
    SupremeAddon,
    ThePirateBayPlusAddon,
    TillAddon,
    TorrinAddon,
    VidFastProAddon,
    YtztvioAddon,
)

# ── Anime ─────────────────────────────────────────────────────────────────────
from .anime import (
    AnimeKitsuAddon,
    AkumaAddon,
    AnimepaheAddon,
    AnimeoAddon,
    OnePaceAddon,
    HanimeAddon,
    AnimesSeasonAddon,
    HiAnimeStreamsAddon,
    AnimeStreamAddon,
    YaStreamAddon,
)

# ── IPTV / Live TV ────────────────────────────────────────────────────────────
from .iptv import (
    AIOStreamingAddon,
    ArgentinaTVAddon,
    EireGBTVAddon,
    FreeMiumTVAddon,
    GreekTVAddon,
    SkyflixAddon,
    WatchioAddon,
    XtreamProAddon,
)

# ── Regional / language-specific ─────────────────────────────────────────────
from .regional import (
    DubbindoAddon,
    EinthusanAddon,
    FenixFlixAddon,
    FigaroCorsoAddon,
    FrenchioAddon,
    FTVStremioAddon,
    LatinMoviesAddon,
    MainelocalnewsAddon,
    MicoLeaoDubladoAddon,
    NoTorrentAddon,
    RicosStremioAddon,
    VStremioAddon,
)

# ── Miscellaneous ────────────────────────────────────────────────────────────
from .misc import (
    ConsumetAddon,
    FShareAddon,
    SuperFlixAddon,
    WatchHubAddon,
    YouTubeProAddon,
)

# ── Debrid service addons ────────────────────────────────────────────────────
from .debrid import (
    DMMAddon,
    PremiumizeAddon,
    PearioAddon,
)

# ── Meteor ────────────────────────────────────────────────────────────────────
from .meteor import MeteorAddon

# ── Registry exports (for tools that want to inspect the registry) ───────────
from .addon_registry import ADDON_REGISTRY, AddonDef, make_addon_class

__all__ = [
    # Torrentio
    "TorrentioAddon",
    "TorrentioSortSeedersAddon",
    "TorrentioPortugueseAddon",
    "TorrentioSpanishAddon",
    "TorrentioHindiAddon",
    "TorrentioLiteAddon",
    "TorrentsDBAddon",
    # Comet / HDHub / StremThru / Brazuca / Guindex
    "CometAddon",
    "CometElfHostedAddon",
    "CometNetAddon",
    "HDHubAddon",
    "StremThruAddon",
    "BrazucaTorrentsAddon",
    "GuindexAddon",
    # Aggregators
    "AIOStreamsAddon",
    "CinAddon",
    "CineTorrentAddon",
    "CinescrapeAddon",
    "DebridSearchAddon",
    "EasyNewsPlusAddon",
    "FlixStreamsAddon",
    "JackettioAddon",
    "KnightCrawlerAddon",
    "KodAddon",
    "MediaFusionAddon",
    "MyCineAddon",
    "NebulaStreamsAddon",
    "NucleusAddon",
    "OrionAddon",
    "PeerflixAddon",
    "StremifyAddon",
    "StreamViXAddon",
    "SupremeAddon",
    "ThePirateBayPlusAddon",
    "TillAddon",
    "TorrinAddon",
    "VidFastProAddon",
    "YtztvioAddon",
    # Anime
    "AnimeKitsuAddon",
    "AkumaAddon",
    "AnimepaheAddon",
    "AnimeoAddon",
    "OnePaceAddon",
    "HanimeAddon",
    "AnimesSeasonAddon",
    "HiAnimeStreamsAddon",
    "AnimeStreamAddon",
    "YaStreamAddon",
    # IPTV
    "AIOStreamingAddon",
    "ArgentinaTVAddon",
    "EireGBTVAddon",
    "FreeMiumTVAddon",
    "GreekTVAddon",
    "SkyflixAddon",
    "WatchioAddon",
    "XtreamProAddon",
    # Regional
    "DubbindoAddon",
    "EinthusanAddon",
    "FenixFlixAddon",
    "FigaroCorsoAddon",
    "FrenchioAddon",
    "FTVStremioAddon",
    "LatinMoviesAddon",
    "MainelocalnewsAddon",
    "MicoLeaoDubladoAddon",
    "NoTorrentAddon",
    "RicosStremioAddon",
    "VStremioAddon",
    # Misc
    "ConsumetAddon",
    "FShareAddon",
    "SuperFlixAddon",
    "WatchHubAddon",
    "YouTubeProAddon",
    # Debrid
    "DMMAddon",
    "PremiumizeAddon",
    "PearioAddon",
    # Meteor
    "MeteorAddon",
    # Registry
    "ADDON_REGISTRY",
    "AddonDef",
    "make_addon_class",
]