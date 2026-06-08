"""ScanService — folder scanning and auto-create missing seasons."""
from datetime import datetime
from typing import Any

from py_stremio.components.configs.app_settings import settings
from py_stremio.components.library.library_scanner import Scanner, FolderType, ScannedFolder
from py_stremio.utils.media import parse_season_from_folder


class ScanService:
    """Scan local folders, identify series/movies, auto-create current-year seasons."""

    def __init__(self):
        self.scanner = Scanner()

    def run(self) -> list[ScannedFolder]:
        """Run the full scan: ensure folders exist, auto-create seasons, scan."""
        self.scanner.ensure_folders()
        self._create_current_year_season_folders(self.scanner)
        return self.scanner.scan()

    def run_with_metadata(self, metadata: Any, quiet: bool = False) -> list[ScannedFolder]:
        """Run the combined library-sync path used by the full run.

        The interactive "run all" flow should feel like one library preparation
        step instead of a silent scan followed by a second metadata phase.  Keep
        the standalone scan/update actions separate, but for full runs update
        metadata as soon as the scan result is available and return that same
        folder list to the downloader.
        """
        folders = self.run()
        metadata.run(folders=folders, quiet=quiet, use_cache=True)
        return folders

    def scan_only(self) -> list[ScannedFolder]:
        """Just scan existing folders without auto-creating seasons."""
        self.scanner.ensure_folders()
        return self.scanner.scan()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_year(self) -> int:
        return datetime.now().year

    def _existing_series_seasons(self, series_path) -> set[int]:
        return {
            season
            for season in (parse_season_from_folder(path.name) for path in series_path.iterdir() if path.is_dir())
            if season is not None
        }

    def _create_current_year_season_folders(self, scanner: Scanner, quiet: bool = False) -> list[ScannedFolder]:
        """Create missing current-year season folders for already tracked series."""
        from py_stremio.components.stremio.stremio_metadata import get_current_year_series_seasons

        created: list[ScannedFolder] = []
        year = self._current_year()
        if not scanner.series_root.exists():
            return created

        for series_path in scanner.series_root.iterdir():
            if not series_path.is_dir():
                continue
            existing = self._existing_series_seasons(series_path)
            latest_existing = max(existing) if existing else 0
            for season_info in get_current_year_series_seasons(series_path.name, year):
                season = int(season_info.get("season") or 0)
                if season <= latest_existing or season in existing:
                    continue
                season_path = series_path / f"s{season:02d}"
                season_path.mkdir(parents=True, exist_ok=True)
                folder = scanner._create_series_folder(season_path)
                if folder:
                    created.append(folder)
                if not quiet:
                    title = season_info.get("title") or series_path.name
                    print(f"  + created {title} S{season:02d}")
        return created
