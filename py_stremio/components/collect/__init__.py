"""Addon discovery and collection pipeline.

Scrapes known Stremio addon sources for manifest URLs,
tests reachability, and merges working ones into addons/addons.txt.
"""

from .addon_index import AddonIndex, get_addon_index
from .ai_discovery import AIDiscovery, DiscoveredAddon, IncrementalDiscovery
from .discovery import discover_new_addons, discover_official_stremio_addons

__all__ = [
    "discover_new_addons",
    "discover_official_stremio_addons",
    "AddonIndex",
    "get_addon_index",
    "AIDiscovery",
    "DiscoveredAddon",
    "IncrementalDiscovery",
]
