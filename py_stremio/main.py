"""Main entry point for py-stremio download manager."""
import json
from datetime import datetime
from typing import Any

from .settings import settings
from .scanner import Scanner, FolderType
from .series import process_series
from .movies import process_movies
from .report import ReportData, print_and_send_report


def update_config_imdb_ids() -> None:
    """Update all download-config.json files with missing IMDB IDs."""
    from .scanner import Scanner
    from .stremio_client import get_series_imdb_id
    from .utils import parse_season_from_folder
    from pathlib import Path

    scanner = Scanner()
    folders = scanner.scan()
    
    for folder in folders:
        if folder.folder_type != FolderType.SERIES:
            continue
            
        config_path = folder.path / "download-config.json"
        if not config_path.exists():
            continue
            
        try:
            with open(config_path) as f:
                config = json.load(f)
            
            if config.get("imdb_id"):
                continue
            
            title = config.get("title")
            season = config.get("season")
            changed = False

            if not title:
                title = folder.path.parent.name.replace("-", " ").replace("_", " ").title()
                config["title"] = title
                changed = True
            
            if not season:
                season = parse_season_from_folder(folder.path.name) or folder.season_number or 1
                config["season"] = season
                changed = True
                
            print(f"\nUpdating IMDB ID for: {folder.path}")
            imdb_id = get_series_imdb_id(title, season)
            if imdb_id:
                print(f" Found IMDB ID: {imdb_id}")
                config["imdb_id"] = imdb_id
                config["type"] = "series"
                changed = True
            else:
                print(f" Could not fetch IMDB ID for: {title} S{season}")

            if changed:
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2)
        except Exception as e:
            print(f" Error updating {config_path}: {e}")

def run() -> None:
    """Main execution function."""
    print(f"\nPy-Stremio Download Manager")
    print(f"Mode: {'DRY RUN' if settings.DRY_RUN else 'LIVE'}")
    print(f"Root folder: {settings.ROOT_FOLDER}")

    scanner = Scanner()
    scanner.ensure_folders()

    folders = scanner.scan()
    print(f"\nFound {len(folders)} folder(s) to process")

    update_config_imdb_ids()

    report_folders: list[dict[str, Any]] = []
    total_downloaded = 0
    total_failed = 0
    processed = 0
    skipped = 0

    for folder in folders:
        print(f"\nProcessing: {folder.path}")

        result: dict[str, Any]
        if folder.folder_type == FolderType.SERIES:
            result = process_series(folder.path)
        elif folder.folder_type == FolderType.MOVIES:
            result = process_movies(folder.path)
        else:
            continue

        downloaded = result.get("downloaded", [])
        failed = result.get("failed", [])

        if result.get("skipped") is True:
            skipped += 1
            folder_info: dict[str, Any] = {
                "name": folder.path.name,
                "type": folder.folder_type.value,
                "path": str(folder.path),
                "downloaded": [],
                "failed": [],
            }
        else:
            processed += 1
            total_downloaded += len(downloaded)
            total_failed += len(failed)
            folder_info = {
                "name": folder.path.name,
                "type": folder.folder_type.value,
                "path": str(folder.path),
                "downloaded": [f"{d.get('episode', d.get('quality', 'unknown'))}" for d in downloaded],
                "failed": [f"{d.get('episode', 'item')}: {d.get('error', 'unknown')}" for d in failed],
            }

        report_folders.append(folder_info)

    report = ReportData(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_folders=len(folders),
        processed_folders=processed,
        skipped_folders=skipped,
        total_downloaded=total_downloaded,
        total_failed=total_failed,
        folders=report_folders,
        dry_run=settings.DRY_RUN,
    )

    print_and_send_report(report)


if __name__ == "__main__":
    run()