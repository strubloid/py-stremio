"""Main entry point for py-stremio download manager."""
from datetime import datetime
from typing import Any

from .settings import settings
from .scanner import Scanner, FolderType
from .series import process_series
from .movies import process_movies
from .report import ReportData, print_and_send_report


def run() -> None:
    """Main execution function."""
    print(f"\nPy-Stremio Download Manager")
    print(f"Mode: {'DRY RUN' if settings.DRY_RUN else 'LIVE'}")
    print(f"Root folder: {settings.ROOT_FOLDER}")

    scanner = Scanner()
    scanner.ensure_folders()

    folders = scanner.scan()
    print(f"\nFound {len(folders)} folder(s) to process")

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