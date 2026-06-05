"""Addon URL configuration rules for host-specific runtime setup."""

from .addon_url_configurer import AddonUrlConfigurer
from .brazuca_addon import BrazucaAddonConfigurer
from .comet_addon import CometAddonConfigurer
from .guindex_addon import GuindexAddonConfigurer
from .hdhub_addon import HDHubAddonConfigurer
from .intell_debrid_search_addon import IntellDebridSearchAddonConfigurer
from .nyaa_addon import NyaaAddonConfigurer
from .stremio import StremioAddonConfigurer
from .strem_thru_addon import StremThruAddonConfigurer
from .torrentio_addon import TorrentioAddonConfigurer
from .yomi_addon import YomiAddonConfigurer

__all__ = [
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
]
