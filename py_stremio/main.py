"""Console entry point for the full py-stremio workflow."""
from __future__ import annotations

import os
import sys
from contextlib import nullcontext

from .app import AppService

__all__ = ["run", "run_cron", "update_config_imdb_ids", "run_migrate"]


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


def _job_name_from_argv() -> str | None:
    """Map CLI flags to the cron job name used for job_runs logging.

    The cron wrapper calls py-stremio-cron with these flags, so a
    manual ``py-stremio --download`` run is recorded the same way as a
    scheduled one.  Flags without a matching job (e.g. ``--run``,
    ``--library``, the interactive menu) are not job-wrapped.
    """
    flag_map = {
        "--configs": "configs",
        "--download": "download",
        "--download-all": "download",
        "--validate-addons": "validate-addons",
        "--validate": "validate-addons",
        "--discover-addons": "discover-addons",
        "--discover": "discover-addons",
    }
    for arg in sys.argv[1:]:
        if arg in flag_map:
            return flag_map[arg]
    return None


def _job_log_context():
    """Return a job_run() context when argv names a scheduled job, else a no-op."""
    job = _job_name_from_argv()
    if not job:
        return nullcontext()
    from py_stremio.services.job_log import job_run

    return job_run(job)


def run() -> None:
    if "--show-config" in sys.argv:
        _print_resolved_config()
        return
    if "--migrate" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] == "migrate"):
        run_migrate()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "export-json":
        run_export_json()
        return
    _apply_retry_failed_flag()
    overrides = _apply_cli_env_overrides()
    with _job_log_context():
        AppService().run(cli_overrides=overrides)


def _cron_speed_percent() -> int:
    """Resolve the cron download speed cap.

    The cron wrapper exports ``INTERNET_SPEED_LIMIT`` (= ``--speed`` on
    ``./cron.sh install``, default 50) so that cap must win here —
    otherwise ``CRON_SPEED_PERCENT`` (80) would silently override it and
    ``--speed`` would have no effect.  Without a wrapper-set env var,
    fall back to the 80% cron preset.
    """
    raw = os.environ.get("INTERNET_SPEED_LIMIT")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return CRON_SPEED_PERCENT


def run_cron() -> None:
    """Cron-friendly entry point using the same AppService path as py-stremio."""
    if "--show-config" in sys.argv:
        _print_resolved_config()
        return
    _apply_retry_failed_flag()
    overrides = _apply_cli_env_overrides()
    with _job_log_context():
        AppService().run(
            interactive=False,
            default_max_workers=CRON_DOWNLOAD_THREADS,
            default_speed_percent=_cron_speed_percent(),
            cli_overrides=overrides,
        )


def run_api() -> None:
    """Start the optional local dashboard API."""
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Install the API extra with `pip install 'py-stremio[api]'`.") from exc
    host = os.environ.get("PY_STREMIO_API_HOST", "127.0.0.1")
    port = int(os.environ.get("PY_STREMIO_API_PORT", "8765"))
    print(
        f"[py-stremio-api pid={os.getpid()}] Dashboard server starting at "
        f"http://{host}:{port} — stop this server with Ctrl+C in this terminal.",
        flush=True,
    )
    uvicorn.run(
        "py_stremio.api.main:app",
        host=host,
        port=port,
        reload=os.environ.get("PY_STREMIO_API_RELOAD", "false").lower() in ("1", "true", "yes"),
    )


def _apply_retry_failed_flag() -> None:
    """Translate ``--retry-failed`` into the ``PY_STREMIO_RETRY_FAILED``
    env var so :func:`py_stremio.components.download.processing._retry_failed_episodes_requested`
    can see it without the CLI surface leaking into the processing layer.

    The flag re-attempts every episode that has previously exhausted its
    retry budget — useful after a long outage, once a previously dead
    addon has come back online, or after the user manually deleted a
    failed ``.part`` file. The skip-notice message reflects that the
    bypass is active so the behaviour is not surprising in the report.
    """
    if "--retry-failed" in sys.argv:
        os.environ["PY_STREMIO_RETRY_FAILED"] = "true"
        os.environ["PY_STREMIO_CLI_RETRY_FAILED"] = "true"


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
    print(f"    CONFIGS_CACHE_HOURS = {settings.CONFIGS_CACHE_HOURS}")
    print(f"    TORRENT_PROXY_URL    = {settings.TORRENT_PROXY_URL or '<unset>'}")
    print(f"    SMTP configured      = {settings.smtp_configured}")


def update_config_imdb_ids(quiet: bool = False) -> int:
    """Backward-compat alias — delegates to MetadataService."""
    from py_stremio.services.metadata import MetadataService
    return MetadataService().run(quiet=quiet)


def run_migrate() -> None:
    """Migrate per-folder JSON configs/states to SQLite catalog."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="py-stremio migrate",
        description="Migrate download-config.json + .download-state.json to SQLite catalog",
    )
    parser.add_argument("--db", type=Path, help="Target SQLite database path (default: ~/.local/share/py-stremio/library.sqlite)")
    parser.add_argument("--root", type=Path, help="Media root folder (default: from .env/ROOT_FOLDER)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without writing")
    parser.add_argument("--export", type=Path, help="Export a folder's config/state from SQLite back to JSON (debugging)")

    args = parser.parse_args(sys.argv[2:])

    if args.export:
        from py_stremio.storage.migration import export_json
        from py_stremio.components.configs.app_settings import settings
        export_json(args.export, args.export.parent)
        print(f"Exported {args.export} to {args.export.parent}")
        return

    from py_stremio.storage.migration import migrate
    from py_stremio.components.configs.app_settings import settings

    root = args.root or settings.ROOT_FOLDER
    print(f"Migrating from {root} to SQLite catalog...")
    if args.dry_run:
        print("  (dry-run mode — no changes will be written)")

    counts = migrate(root_folder=root, db_path=args.db, dry_run=args.dry_run)

    print("Migration complete:")
    print(f"  Series:   {counts['series']}")
    print(f"  Seasons:  {counts['seasons']}")
    print(f"  Movies:   {counts['movies']}")
    print(f"  Files:    {counts['files']}")
    print(f"  States:   {counts['states']}")


def run_export_json() -> None:
    """Export one catalog folder to the transitional JSON format."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="py-stremio export-json")
    parser.add_argument("folder", type=Path, help="Managed season or movie folder")
    args = parser.parse_args(sys.argv[2:])

    from py_stremio.storage.migration import export_json

    export_json(args.folder, args.folder)
    print(f"Exported JSON config and state to {args.folder}")


if __name__ == "__main__":
    run()
