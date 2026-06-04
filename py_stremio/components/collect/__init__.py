"""Addon discovery and collection pipeline.

Scrapes known Stremio addon sources for manifest URLs,
tests reachability, and merges working ones into addons.txt.
"""

from .discovery import discover_new_addons

__all__ = ["discover_new_addons"]
