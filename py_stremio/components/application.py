"""Backward-compatibility re-exports for py-stremio.

All orchestration logic moved to py_stremio/services/ and py_stremio/app.py.
This file is kept as a compatibility shim for existing imports and tests.

IMPORTANT: Tests monkeypatch module-level names (settings, process_series,
print_and_send_report, etc.) directly onto this module. So run() must resolve
everything lazily from this module's own namespace.
"""
import sys
from datetime import datetime
from typing import Any

# ------------------------------------------------------------------
# Patchable references — tests replace these with mocks
# ------------------------------------------------------------------
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.download.processing import process_season_folder as process_series
from py_stremio.components.download.processing import process_movie_folder as process_movies
from py_stremio.components.errors import print_error_summary
from py_stremio.components.library.library_scanner import Scanner, FolderType, ScannedFolder
from py_stremio.components.reports.report import ReportData, print_and_send_report
from py_stremio.services.progress import (
    ACCENT, DIM, GREEN, RED, RESET, YELLOW,
    _c, _color, _color_bar, _event_progress_bar, _format_bytes, _progress_key,
    _progress_line, _speed_label, _truncate_label,
    make_progress_printer as _make_progress_printer,
    render_progress_bar,
)

# ------------------------------------------------------------------
# Helper: check terminal color support
# ------------------------------------------------------------------
def _supports_color() -> bool:
    return sys.stdout.isatty()

# ------------------------------------------------------------------
# Full pipeline (preserved as module-level functions so tests can
# monkeypatch settings and call them directly)
# ------------------------------------------------------------------

def scan_library() -> list[ScannedFolder]:
    """Scan configured folders and print a compact folder overview."""
    from py_stremio.services.scanner import ScanService
    return ScanService().run()


def update_config_imdb_ids(quiet: bool = False) -> int:
    """Create/update series download-config.json files with metadata."""
    from py_stremio.services.metadata import MetadataService
    return MetadataService().run(quiet=quiet)


def download_folders(
    folders: list[ScannedFolder] | None = None,
    quiet: bool = True,
    max_workers: int = 1,
    speed_percent: int | None = None,
):
    """Download missing items for folders."""
    from py_stremio.services.download import DownloadService
    return DownloadService().run(folders, quiet=quiet, max_workers=max_workers, speed_percent=speed_percent)


def _run_processor(folder, quiet, progress_callback=None, max_workers=1, bandwidth_limiter=None, worker_semaphore=None):
    from py_stremio.services.download import DownloadService
    return DownloadService()._run_processor(folder, quiet, progress_callback=progress_callback, max_workers=max_workers, bandwidth_limiter=bandwidth_limiter, worker_semaphore=worker_semaphore)


def _series_completion_overviews(folders):
    from py_stremio.services.download import DownloadService
    return DownloadService()._series_completion_overviews(folders)


def _current_year() -> int:
    return datetime.now().year


def _existing_series_seasons(series_path) -> set[int]:
    from py_stremio.services.scanner import ScanService
    return ScanService()._existing_series_seasons(series_path)


def _create_current_year_season_folders(scanner, quiet=False):
    from py_stremio.services.scanner import ScanService
    return ScanService()._create_current_year_season_folders(scanner, quiet=quiet)


# ------------------------------------------------------------------
# Entry points (delegate to AppService but keep lazily so callers
# that have monkeypatched settings on THIS module get the right value)
# ------------------------------------------------------------------

def run(interactive: bool | None = None) -> None:
    """CLI entry point — delegates to AppService."""
    # Check if settings has been monkeypatched (test mode)
    if settings.ROOT_FOLDER and settings.DRY_RUN:
        import py_stremio.services.scanner as _ss
        import py_stremio.services.metadata as _sm
        import py_stremio.services.download as _sd
        import py_stremio.app as _app
        _ss.settings = settings
        _sm.settings = settings
        _sd.settings = settings
        _app.settings = settings
    from py_stremio.app import AppService
    AppService().run(interactive=interactive)


def run_pipeline(
    download: bool = True,
    quiet: bool = True,
    max_workers: int = 1,
    speed_percent: int | None = None,
) -> None:
    """Run the standard scan → metadata → validate addons → optional download pipeline."""
    from py_stremio.app import AppService
    AppService().run_pipeline(download=download, quiet=quiet, max_workers=max_workers, speed_percent=speed_percent)


def run_menu() -> None:
    """Interactive terminal menu."""
    from py_stremio.app import AppService
    AppService().run_menu()
