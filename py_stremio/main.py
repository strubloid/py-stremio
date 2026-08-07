"""Console entry point for the full py-stremio workflow."""
from __future__ import annotations

import os
import sys

from .app import AppService

__all__ = ["run", "run_cron", "update_config_imdb_ids"]


CRON_DOWNLOAD_THREADS = 5
CRON_SPEED_PERCENT = 80


def _apply_cli_env_overrides() -> dict[str, str]:
    """Pull ``--root PATH`` and ``--key NAME=VALUE`` flags out of
    ``sys.argv`` and re-apply them to the live ``Settings`` singleton.

    This is the fix for the network-share trap: the ``.env`` lives
    next to the source tree (a shared mount), but ``ROOT_FOLDER`` is
    a per-machine path.  Editing the shared ``.env`` is wrong — the
    next person to clone the share would inherit the override.  The
    correct way is to keep the ``.env`` generic and let each user
    pass ``--root`` on the command line.

    Underscored ``--root_folder`` is accepted as an alias because it
    matches the env-var name.

    Returns a dict of ``{key: value}`` so the caller can echo what
    was applied (useful for the banner).
    """
    if not sys.argv:
        return {}
    overrides: dict[str, str] = {}
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--root", "--root_folder", "--root-folder") and i + 1 < len(args):
            overrides["ROOT_FOLDER"] = args[i + 1]
            i += 2
            continue
        if arg.startswith("--root="):
            overrides["ROOT_FOLDER"] = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--key" and i + 1 < len(args):
            kv = args[i + 1].split("=", 1)
            if len(kv) == 2:
                overrides[kv[0]] = kv[1]
            i += 2
            continue
        if arg.startswith("--key="):
            kv = arg.split("=", 2)[1:]
            if len(kv) == 2:
                overrides[kv[0]] = kv[1]
            i += 1
            continue
        i += 1

    if not overrides:
        return {}

    # Apply to the live Settings singleton.  We import lazily so the
    # import order stays: dotenv-load → app_settings import → re-apply.
    from py_stremio.components.configs.app_settings import settings

    if "ROOT_FOLDER" in overrides:
        settings.reapply_root(overrides["ROOT_FOLDER"])
        os.environ["ROOT_FOLDER"] = overrides["ROOT_FOLDER"]
    for key, value in overrides.items():
        if key == "ROOT_FOLDER":
            continue
        os.environ[key] = value
    return overrides


def run() -> None:
    if "--show-config" in sys.argv:
        _print_resolved_config()
        return
    overrides = _apply_cli_env_overrides()
    AppService().run(cli_overrides=overrides)


def run_cron() -> None:
    """Cron-friendly entry point using the same AppService path as py-stremio."""
    if "--show-config" in sys.argv:
        _print_resolved_config()
        return
    overrides = _apply_cli_env_overrides()
    AppService().run(
        interactive=False,
        default_max_workers=CRON_DOWNLOAD_THREADS,
        default_speed_percent=CRON_SPEED_PERCENT,
        cli_overrides=overrides,
    )


def _print_resolved_config() -> None:
    """Dump every resolved settings value so a user can see exactly
    which ``.env`` was loaded and what overrides are in effect.

    The .env lookup order (first hit wins) is also listed so the
    user can verify their ``.env`` is in a location the loader will
    actually check.
    """
    from py_stremio.components.configs.app_settings import (
        SETTINGS_DOTENV_PATH,
        settings,
    )
    from pathlib import Path as _Path

    print("py-stremio resolved configuration")
    print("=" * 60)
    print(f"  .env loaded from: {SETTINGS_DOTENV_PATH or '(none — using hardcoded defaults)'}")
    print(f"  cwd:               {_Path.cwd()}")
    print()
    print("  .env lookup order (first hit wins):")
    explicit = os.environ.get("PY_STREMIO_ENV") or "(unset)"
    print(f"    1. $PY_STREMIO_ENV       = {explicit}")
    print(f"    2. cwd/.env             = {_Path.cwd() / '.env'}")
    print(f"    3. project root/.env    = {settings.ROOT_FOLDER.parent.parent / '.env' if False else '<resolved at import>'}")
    print(f"    4. $HOME/.env           = {_Path.home() / '.env'}")
    print()
    print("  Resolved values:")
    print(f"    ROOT_FOLDER          = {settings.ROOT_FOLDER}")
    print(f"    SERIES_FOLDER        = {settings.SERIES_FOLDER}")
    print(f"    MOVIES_FOLDER        = {settings.MOVIES_FOLDER}")
    print(f"    REAL_DEBRID_API_KEY  = {'<set>' if settings.REAL_DEBRID_API_KEY else '<unset>'}")
    print(f"    PREMIUMIZE_API_KEY   = {'<set>' if settings.PREMIUMIZE_API_KEY else '<unset>'}")
    print(f"    ALLDEBRID_API_KEY  = {'<set>' if settings.ALLDEBRID_API_KEY else '<unset}'}")
    print(f"    STREMIO_ADDON_URL    = {settings.STREMIO_ADDON_URL or '<unset>'}")
    print(f"    STREMIO_ADDON_URL_BASE = {settings.STREMIO_ADDON_URL_BASE}")
    print(f"    DOWNLOAD_THREADS     = {settings.DOWNLOAD_THREADS}")
    print(f"    INTERNET_SPEED_LIMIT = {settings.INTERNET_SPEED_LIMIT}")
    print(f"    INTERNET_MAX_SPEED_MBPS = {settings.INTERNET_MAX_SPEED_MBPS}")
    print(f"    PREFERRED_LANGUAGES  = {settings.PREFERRED_LANGUAGES}")
    print(f"    DRY_RUN              = {settings.DRY_RUN}")
    print(f"    MAX_DOWNLOAD_ATTEMPTS = {settings.MAX_DOWNLOAD_ATTEMPTS}")
    print(f"    MIN_COMPLETED_VIDEO_SIZE_MB = {settings.MIN_COMPLETED_VIDEO_SIZE_MB}")
    print(f"    DOWNLOAD_STALL_TIMEOUT = {settings.DOWNLOAD_STALL_TIMEOUT}")
    print(f"    VALIDATE_DOWNLOAD_STRUCTURE = {settings.VALIDATE_DOWNLOAD_STRUCTURE}")
    print(f"    METADATA_CACHE_HOURS = {settings.METADATA_CACHE_HOURS}")
    print(f"    TORRENT_PROXY_URL    = {settings.TORRENT_PROXY_URL or '<unset>'}")
    print(f"    SMTP configured      = {settings.smtp_configured}")


def update_config_imdb_ids(quiet: bool = False) -> int:
    """Backward-compat alias — delegates to MetadataService."""
    from py_stremio.services.metadata import MetadataService
    return MetadataService().run(quiet=quiet)


if __name__ == "__main__":
    run()
