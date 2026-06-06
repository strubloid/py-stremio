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
    MediaFusionAddon,
    KnightCrawlerAddon,
    EasyNewsPlusAddon,
    PeerflixAddon,
    NucleusAddon,
    OrionAddon,
    DebridSearchAddon,
    StremifyAddon,
    JackettioAddon,
    AIOStreamsAddon,
    CineTorrentAddon,
    TorrinAddon,
    ThePirateBayPlusAddon,
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
)

# ── IPTV / Live TV ────────────────────────────────────────────────────────────
from .iptv import (
    SkyflixAddon,
    ArgentinaTVAddon,
    GreekTVAddon,
    XtreamProAddon,
    AIOStreamingAddon,
)

# ── Regional / language-specific ─────────────────────────────────────────────
from .regional import (
    NoTorrentAddon,
    LatinMoviesAddon,
    RicosStremioAddon,
    FTVStremioAddon,
    FigaroCorsoAddon,
    EinthusanAddon,
    VStremioAddon,
    DubbindoAddon,
    MainelocalnewsAddon,
)

# ── Miscellaneous ────────────────────────────────────────────────────────────
from .misc import (
    WatchHubAddon,
    YouTubeProAddon,
    FShareAddon,
    ConsumetAddon,
)

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
    # Comet / HDHub / StremThru / Brazuca / Guindex
    "CometAddon",
    "CometElfHostedAddon",
    "CometNetAddon",
    "HDHubAddon",
    "StremThruAddon",
    "BrazucaTorrentsAddon",
    "GuindexAddon",
    # Aggregators
    "MediaFusionAddon",
    "KnightCrawlerAddon",
    "EasyNewsPlusAddon",
    "PeerflixAddon",
    "NucleusAddon",
    "OrionAddon",
    "DebridSearchAddon",
    "StremifyAddon",
    "JackettioAddon",
    "AIOStreamsAddon",
    "CineTorrentAddon",
    "TorrinAddon",
    "ThePirateBayPlusAddon",
    # Anime
    "AnimeKitsuAddon",
    "AkumaAddon",
    "AnimepaheAddon",
    "AnimeoAddon",
    "OnePaceAddon",
    "HanimeAddon",
    "AnimesSeasonAddon",
    # IPTV
    "SkyflixAddon",
    "ArgentinaTVAddon",
    "GreekTVAddon",
    "XtreamProAddon",
    "AIOStreamingAddon",
    # Regional
    "NoTorrentAddon",
    "LatinMoviesAddon",
    "RicosStremioAddon",
    "FTVStremioAddon",
    "FigaroCorsoAddon",
    "EinthusanAddon",
    "VStremioAddon",
    "DubbindoAddon",
    "MainelocalnewsAddon",
    # Misc
    "WatchHubAddon",
    "YouTubeProAddon",
    "FShareAddon",
    "ConsumetAddon",
    # Registry
    "ADDON_REGISTRY",
    "AddonDef",
    "make_addon_class",
]