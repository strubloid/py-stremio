"""Debrid service integration.

Provides multi-debrid support for torrent resolution via RealDebrid,
Premiumize.me, AllDebrid, and other services.
"""

from .base import (
    BaseDebridProvider,
    DebridProviderInfo,
    register_debrid_provider,
    get_debrid_provider,
    get_all_provider_names,
    create_all_providers,
)
from .real_debrid_client import (
    resolve_torrent_with_debrid,
    RD_POLL_ATTEMPTS,
    RD_POLL_INTERVAL_SECONDS,
)
from .premiumize_client import (
    resolve_torrent_with_premiumize,
    is_premiumize_available,
)
from .alldebrid_client import (
    resolve_torrent_with_alldebrid,
    is_alldebrid_available,
)
from .multi_resolver import (
    resolve_with_all_debrid,
    resolve_with_fallback_chain,
    get_default_chain,
    is_any_debrid_available,
)

__all__ = [
    "BaseDebridProvider",
    "DebridProviderInfo",
    "register_debrid_provider",
    "get_debrid_provider",
    "get_all_provider_names",
    "create_all_providers",
    "resolve_torrent_with_debrid",
    "resolve_torrent_with_premiumize",
    "resolve_torrent_with_alldebrid",
    "resolve_with_all_debrid",
    "resolve_with_fallback_chain",
    "get_default_chain",
    "is_any_debrid_available",
    "is_premiumize_available",
    "is_alldebrid_available",
    "RD_POLL_ATTEMPTS",
    "RD_POLL_INTERVAL_SECONDS",
]
