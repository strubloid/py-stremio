"""Data registry and factory for simple addons.

Addons with custom URL logic live in their own files (e.g. torrentio_family.py,
comet_family.py).  All remaining addons are defined as AddonDef data entries here
and turned into real HttpAddon subclasses at import time by make_addon_class().
"""

from dataclasses import dataclass

from ..base import HttpAddon


# ── Names that are already defined in explicit class files ───────────────────
# These names MUST NOT be overwritten by the dynamic class factory below.
# Update this set whenever a new explicit addon file is added.
_EXPLICIT_NAMES: frozenset[str] = frozenset([
    # torrentio_family.py
    "TorrentioAddon",
    "TorrentioSortSeedersAddon",
    "TorrentioPortugueseAddon",
    "TorrentioSpanishAddon",
    "TorrentioHindiAddon",
    "TorrentioLiteAddon",
    "TorrentsDBAddon",
    # comet_family.py
    "CometAddon",
    "CometElfHostedAddon",
    "CometNetAddon",
    "HDHubAddon",
    "StremThruAddon",
    "BrazucaTorrentsAddon",
    "GuindexAddon",
    # aggregators.py
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
    "StreamViXAddon",
    "FlixStreamsAddon",
    "YtztvioAddon",
    "VidFastProAddon",
    "MyCineAddon",
    "NebulaStreamsAddon",
    "SupremeAddon",
    "KodAddon",
    "CinescrapeAddon",
    "TillAddon",
    # anime.py
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
    # iptv.py
    "SkyflixAddon",
    "ArgentinaTVAddon",
    "GreekTVAddon",
    "XtreamProAddon",
    "AIOStreamingAddon",
    "WatchioAddon",
    "FreeMiumTVAddon",
    "EireGBTVAddon",
    # regional.py
    "NoTorrentAddon",
    "LatinMoviesAddon",
    "RicosStremioAddon",
    "FTVStremioAddon",
    "FigaroCorsoAddon",
    "EinthusanAddon",
    "VStremioAddon",
    "DubbindoAddon",
    "MainelocalnewsAddon",
    "FenixFlixAddon",
    "MicoLeaoDubladoAddon",
    "FrenchioAddon",
    # misc.py
    "WatchHubAddon",
    "YouTubeProAddon",
    "FShareAddon",
    "ConsumetAddon",
    "SuperFlixAddon",
    # debrid.py
    "DMMAddon",
    "PremiumizeAddon",
    "PearioAddon",
])


# ── AddonDef dataclass ────────────────────────────────────────────────────────

@dataclass
class AddonDef:
    """Declaration for a simple addon that just returns its base URL."""

    name: str
    base_url: str
    description: str = ""
    enabled: bool = True
    rd_suffix: str | None = None  # Optional URL suffix injected when RD key is present


# ── Name-to-class mapping for registry entries without an explicit class ─────

def _to_class_name(addon_name: str) -> str:
    """Convert addon display name to expected 'NameAddon' class name.

    Handles known naming quirks: "EasyNews+" -> "EasyNewsPlusAddon",
    "ThePirateBay+" -> "ThePirateBayPlusAddon", "Rico's Stremio" ->
    "RicosStremioAddon", etc.
    """
    _name_map: dict[str, str] = {
        "EasyNews+": "EasyNewsPlus",
        "ThePirateBay+": "ThePirateBayPlus",
        "Rico's Stremio": "RicosStremio",
        "FTV Stremio": "FTVStremio",
        "FigaroCorso": "FigaroCorso",
        "GreekTV": "GreekTV",
        "Anime-Kitsu": "AnimeKitsu",
        "NoTorrent": "NoTorrent",
        "VStremio": "VStremio",
        "Dubbindo": "Dubbindo",
        "FShare": "FShare",
        "Consumet": "Consumet",
        "LatinMovies": "LatinMovies",
        "Hanime": "Hanime",
        "YouTubePRO": "YouTubePro",
        "XtreamPro": "XtreamPro",
        "Animes Season": "AnimesSeason",
        "Maine Local News": "Mainelocalnews",
        "CineTorrent": "CineTorrent",
        "Peerflix": "Peerflix",
        "Nucleus": "Nucleus",
        "Orion": "Orion",
        "Torrin": "Torrin",
        "DebridSearch": "DebridSearch",
        "Stremify": "Stremify",
        "Jackettio": "Jackettio",
        "AIOStreams": "AIOStreams",
        "AIOStreaming": "AIOStreaming",
        "Skyflix": "Skyflix",
        "WatchHub": "WatchHub",
        "Einthusan": "Einthusan",
        "KnightCrawler": "KnightCrawler",
        "Akuma": "Akuma",
        "Animepahe": "Animepahe",
        "Animeo": "Animeo",
    }

    if addon_name in _name_map:
        base = _name_map[addon_name]
    elif "+" in addon_name:
        base = addon_name.replace("+", "Plus")
    elif " " in addon_name or "-" in addon_name or "'" in addon_name:
        words = addon_name.replace("-", " ").replace("'", "").split()
        base = "".join(w.capitalize() for w in words if w)
    else:
        base = addon_name

    return f"{base}Addon"


# ── Class factory ─────────────────────────────────────────────────────────────

# Module-level cache so make_addon_class() is idempotent.
_cache: dict[str, type[HttpAddon]] = {}


def make_addon_class(def_: AddonDef) -> type[HttpAddon]:
    """Create (or return cached) HttpAddon subclass for a simple addon definition.

    Idempotent: calling twice with the same addon name returns the same class.
    """
    if def_.name in _cache:
        return _cache[def_.name]

    class_name = _to_class_name(def_.name)
    suffix = def_.rd_suffix or ""

    def get_url(self, api_key: str | None = None) -> str:
        if api_key and suffix:
            return f"{self.base_url}{suffix.format(api_key=api_key)}"
        return self.base_url

    cls_dict = {
        "name": def_.name,
        "base_url": def_.base_url,
        "enabled": def_.enabled,
        "__doc__": def_.description,
        "get_url": get_url,
    }

    cls = type(class_name, (HttpAddon,), cls_dict)
    _cache[def_.name] = cls
    return cls


# ── Registry entries for addons that don't have an explicit class ────────────
# All addons defined here are instantiated into real classes at the bottom of
# this file so that factory.py and __init__.py can import them by name.
#
# Addons with custom URL logic (Torrentio, Comet, HDHub, etc.) are NOT here —
# they have their own explicit classes in separate files.

# fmt: off
ADDON_REGISTRY: list[AddonDef] = [
    # The registry is empty because every addon that exists in the codebase
    # already has an explicit class in one of the explicit files above.
    # This list is kept for documentation and future extension.
]
# fmt: on


# ── Instantiate dynamic classes ──────────────────────────────────────────────
# Scan ADDON_REGISTRY and create a class for each entry that doesn't already
# have an explicit class file.  In practice the loop below is a no-op because
# all registry entries are covered by explicit files, but the machinery is
# in place to add new addons via data declarations alone.

for addon_def in ADDON_REGISTRY:
    class_name = _to_class_name(addon_def.name)
    if class_name not in _EXPLICIT_NAMES:
        cls = make_addon_class(addon_def)
        globals()[class_name] = cls