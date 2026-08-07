"""Multi-debrid resolution - try all configured providers in parallel."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .base import BaseDebridProvider, create_all_providers, get_debrid_provider


async def resolve_with_all_debrid(
    info_hash: str,
    file_idx: int | None = None,
    max_concurrent: int = 3,
) -> tuple[Optional[str], Optional[str]]:
    """Try all configured debrid services in parallel, return first success.

    Args:
        info_hash: The torrent info hash to resolve.
        file_idx: Optional file index to select.
        max_concurrent: Maximum concurrent resolves.

    Returns:
        (direct_url, provider_name) if any provider succeeds, (None, None) otherwise.
    """
    providers = [p for p in create_all_providers() if p.is_available()]
    if not providers:
        return None, None

    loop = asyncio.get_event_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _resolve_sync, provider, info_hash, file_idx)
          for provider in providers],
        return_exceptions=True
    )

    for provider, result in zip(providers, results):
        if isinstance(result, str) and result:
            return result, provider.name
        if isinstance(result, tuple) and result[0]:
            return result

    return None, None


def _resolve_sync(provider: BaseDebridProvider, info_hash: str, file_idx: int | None) -> str | None:
    """Synchronous wrapper for provider.resolve_torrent()."""
    try:
        return provider.resolve_torrent(info_hash, file_idx)
    except Exception:
        return None


def resolve_with_fallback_chain(
    info_hash: str,
    file_idx: int | None = None,
    chain: list[str] | None = None,
) -> tuple[Optional[str], Optional[str]]:
    """Try debrid services in order until one succeeds.

    Args:
        info_hash: The torrent info hash to resolve.
        file_idx: Optional file index to select.
        chain: List of provider names in order (default: primary + fallback).

    Returns:
        (direct_url, provider_name) if any provider succeeds, (None, None) otherwise.
    """
    if chain is None:
        chain = get_default_chain()

    for provider_name in chain:
        provider = get_debrid_provider(provider_name)
        if provider is None or not provider.is_available():
            continue
        try:
            result = provider.resolve_torrent(info_hash, file_idx)
            if result:
                return result, provider.name
        except Exception:
            continue

    return None, None


def get_default_chain() -> list[str]:
    """Get the default debrid fallback chain from settings."""
    from py_stremio.components.configs.app_settings import settings

    chain = []

    if settings.REAL_DEBRID_API_KEY:
        chain.append("realdebrid")

    if settings.PREMIUMIZE_API_KEY:
        chain.append("premiumize")

    if settings.ALLDEBRID_API_KEY:
        chain.append("alldebrid")

    return chain


def is_any_debrid_available() -> bool:
    """Check if any debrid service is configured and available."""
    for provider in create_all_providers():
        if provider.is_available():
            return True
    return False
