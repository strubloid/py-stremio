"""Addon URL configuration rules for host-specific runtime setup."""

from .addon_url_configurer import AddonUrlConfigurer
from .builtin_addons import (
    ADDON_REGISTRY,
    AddonDef,
    make_addon_class,
)
from .stremio import StremioAddonConfigurer
from .torrentio_family.TorrentioAddonConfigurer import TorrentioAddonConfigurer
from .comet_family.CometAddonConfigurer import CometAddonConfigurer
from .comet_family.HDHubAddonConfigurer import HDHubAddonConfigurer
from .comet_family.StremThruAddonConfigurer import StremThruAddonConfigurer
from .comet_family.BrazucaAddonConfigurer import BrazucaAddonConfigurer
from .comet_family.GuindexAddonConfigurer import GuindexAddonConfigurer
from .anime.NyaaAddonConfigurer import NyaaAddonConfigurer
from .anime.YomiAddonConfigurer import YomiAddonConfigurer
from .aggregators.IntellDebridSearchAddonConfigurer import IntellDebridSearchAddonConfigurer

# Re-export all explicit addon classes for convenience
from .builtin_addons import (
    # Torrentio
    TorrentioAddon,
    TorrentioSortSeedersAddon,
    TorrentioPortugueseAddon,
    TorrentioSpanishAddon,
    TorrentioHindiAddon,
    TorrentioLiteAddon,
    # Comet / HDHub / StremThru / Brazuca / Guindex
    CometAddon,
    CometElfHostedAddon,
    CometNetAddon,
    HDHubAddon,
    StremThruAddon,
    BrazucaTorrentsAddon,
    GuindexAddon,
    # Aggregators
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
    # Anime
    AnimeKitsuAddon,
    AkumaAddon,
    AnimepaheAddon,
    AnimeoAddon,
    OnePaceAddon,
    HanimeAddon,
    AnimesSeasonAddon,
    # IPTV
    SkyflixAddon,
    ArgentinaTVAddon,
    GreekTVAddon,
    XtreamProAddon,
    AIOStreamingAddon,
    # Regional
    NoTorrentAddon,
    LatinMoviesAddon,
    RicosStremioAddon,
    FTVStremioAddon,
    FigaroCorsoAddon,
    EinthusanAddon,
    VStremioAddon,
    DubbindoAddon,
    MainelocalnewsAddon,
    # Misc
    WatchHubAddon,
    YouTubeProAddon,
    FShareAddon,
    ConsumetAddon,
)

__all__ = [
    # Configurers
    "AddonUrlConfigurer",
    "BrazucaAddonConfigurer",
    "CometAddonConfigurer",
    "GuindexAddonConfigurer",
    "HDHubAddonConfigurer",
    "IntellDebridSearchAddonConfigurer",
    "NyaaAddonConfigurer",
    "StremioAddonConfigurer",
    "StremThruAddonConfigurer",
    "TorrentioAddonConfigurer",
    "YomiAddonConfigurer",
    # Registry
    "ADDON_REGISTRY",
    "AddonDef",
    "make_addon_class",
    # All addon classes
    "TorrentioAddon",
    "TorrentioSortSeedersAddon",
    "TorrentioPortugueseAddon",
    "TorrentioSpanishAddon",
    "TorrentioHindiAddon",
    "TorrentioLiteAddon",
    "CometAddon",
    "CometElfHostedAddon",
    "CometNetAddon",
    "HDHubAddon",
    "StremThruAddon",
    "BrazucaTorrentsAddon",
    "GuindexAddon",
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
    "AnimeKitsuAddon",
    "AkumaAddon",
    "AnimepaheAddon",
    "AnimeoAddon",
    "OnePaceAddon",
    "HanimeAddon",
    "AnimesSeasonAddon",
    "SkyflixAddon",
    "ArgentinaTVAddon",
    "GreekTVAddon",
    "XtreamProAddon",
    "AIOStreamingAddon",
    "NoTorrentAddon",
    "LatinMoviesAddon",
    "RicosStremioAddon",
    "FTVStremioAddon",
    "FigaroCorsoAddon",
    "EinthusanAddon",
    "VStremioAddon",
    "DubbindoAddon",
    "MainelocalnewsAddon",
    "WatchHubAddon",
    "YouTubeProAddon",
    "FShareAddon",
    "ConsumetAddon",
]