"""DownloadService — orchestrate downloads across series/movie folders."""
import inspect
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from py_stremio.components.configs.app_settings import settings
from py_stremio.components.configs.config_file import load_config
from py_stremio.components.download.bandwidth_service import build_limiter
from py_stremio.components.download.control_panel import create_control_panel
from py_stremio.components.download.speed_probe import resolve_max_speed_mbps
from py_stremio.components.download.processing import process_movie_folder as process_movies
from py_stremio.components.download.processing import process_season_folder as process_series
from py_stremio.components.library.library_scanner import Scanner, FolderType, ScannedFolder
from py_stremio.components.library.media_file import detect_existing_season_episodes
from py_stremio.components.reports.output_writer import install_thread_stdout_filter, suppress_current_thread_output, restore_thread_stdout_filter
from py_stremio.components.reports.report import ReportData, print_and_send_report
from py_stremio.services.progress import (
    ACCENT, GREEN, YELLOW, RED, DIM, RESET, build_table, make_progress_printer,
)
from py_stremio.utils.cancellation import clear_shutdown, request_shutdown, shutdown_executor_now, shutdown_requested


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


class DownloadService:
    """Download missing episodes/movies across folders with parallel support."""

    def __init__(self):
        self.scanner = Scanner()

    def run(
        self,
        folders: list[ScannedFolder] | None = None,
        quiet: bool = True,
        max_workers: int = 1,
        speed_percent: int | None = None,
    ) -> ReportData:
        """Download missing items for folders and return a report."""
        clear_shutdown()
        if folders is None:
            folders = self.scanner.scan()
        folders = self._dedupe_duplicate_series_seasons(folders)

        print(_c("\n⬇ Downloads", ACCENT))
        if speed_percent is None:
            speed_percent = settings.INTERNET_SPEED_LIMIT if hasattr(settings, "INTERNET_SPEED_LIMIT") else getattr(settings, "INTERNET_SPEED_LIMIT", 100)
        assert speed_percent is not None, "speed_percent must resolve to int"

        max_speed_mbps = resolve_max_speed_mbps(default_mbps=getattr(settings, "INTERNET_MAX_SPEED_MBPS", 100))
        bandwidth_limiter = build_limiter(speed_percent, max_speed_mbps, max_workers=max_workers)
        print(f"  Threads: {max_workers} · speed: {speed_percent}%")

        # Create interactive control panel
        control_panel, workers_ref, speed_ref = create_control_panel(
            bandwidth_limiter, max_workers, speed_percent, max_speed_mbps, progress_line_count=0
        )

        report_folders: list[dict[str, Any]] = []
        total_downloaded = 0
        total_failed = 0
        processed = 0
        skipped = 0

        runnable: list[ScannedFolder] = []
        restore_stdout = None
        if quiet:
            progress_stream, restore_stdout = install_thread_stdout_filter()
        else:
            progress_stream = sys.stdout
        
        # Wrap progress printer to track active lines for control panel positioning
        base_progress = make_progress_printer(progress_stream)
        active_line_count = [0]  # mutable ref
        
        def progress(event: dict[str, Any]) -> None:
            base_progress(event)
            # Track active lines for control panel positioning
            if event.get("type") == "episode_start":
                active_line_count[0] += 1
                control_panel.update_progress_lines(active_line_count[0])
            elif event.get("type") == "episode_done":
                active_line_count[0] = max(0, active_line_count[0] - 1)
                control_panel.update_progress_lines(active_line_count[0])
        
        worker_semaphore = threading.Semaphore(max_workers) if max_workers > 1 else None

        def folder_display(folder: ScannedFolder) -> str:
            display_name = folder.path.parent.name if folder.folder_type == FolderType.SERIES else folder.path.name
            suffix = f" S{folder.season_number:02d}" if folder.season_number is not None else ""
            return f"{display_name}{suffix}"

        table = self._series_completion_overviews(folders)
        if table:
            print(table)

        for folder in folders:
            if folder.folder_type not in (FolderType.SERIES, FolderType.MOVIES):
                skipped += 1
                print(_c("    skipped", DIM))
                continue
            runnable.append(folder)

        def process_folder(folder: ScannedFolder) -> tuple[ScannedFolder, dict[str, Any]]:
            per_folder_workers = workers_ref[0]  # Use mutable ref for dynamic updates
            return folder, self._run_processor(
                folder,
                quiet=quiet,
                progress_callback=progress,
                max_workers=per_folder_workers,
                bandwidth_limiter=bandwidth_limiter,
                worker_semaphore=worker_semaphore,
            )

        def record_result(folder: ScannedFolder, result: dict[str, Any]) -> None:
            nonlocal processed, skipped, total_downloaded, total_failed
            if result.get("skipped") is True:
                skipped += 1
                if folder.folder_type != FolderType.SERIES:
                    print(_c(f"  {folder_display(folder)} skipped ({result.get('reason', 'disabled')})", YELLOW), file=sys.stderr)
                report_folders.append({
                    "name": folder.path.name,
                    "type": folder.folder_type.value,
                    "path": str(folder.path),
                    "skipped": True,
                    "reason": result.get("reason", "unknown"),
                    "downloaded": [],
                    "failed": [],
                })
                return

            processed += 1
            downloaded_count = _result_count(result.get("downloaded", 0))
            failed_count = _result_count(result.get("failed", 0))
            total_downloaded += downloaded_count
            total_failed += failed_count

            if downloaded_count or failed_count or folder.folder_type != FolderType.SERIES:
                status = _c(f"✓ {downloaded_count} downloaded", GREEN) if failed_count == 0 else _c(f"! {failed_count} failed", RED)
                if downloaded_count and failed_count:
                    status = f"{_c(f'✓ {downloaded_count}', GREEN)} / {_c(f'! {failed_count}', RED)}"
                print(f"  {folder_display(folder)} {status}", file=sys.stderr)

            report_folders.append({
                "name": folder.path.name,
                "type": folder.folder_type.value,
                "path": str(folder.path),
                "downloaded": _result_items(result.get("downloaded", []), "downloaded", downloaded_count),
                "failed": _result_items(result.get("failed", []), "failed", failed_count),
                "failed_reasons": result.get("failed_reasons", []),
                "downloaded_count": downloaded_count,
                "failed_count": failed_count,
            })

        try:
            if max_workers > 1 and len(runnable) > 1:
                executor = ThreadPoolExecutor(max_workers=max_workers)
                futures = []
                try:
                    futures = [executor.submit(process_folder, folder) for folder in runnable]
                    for future in as_completed(futures):
                        if shutdown_requested():
                            break
                        folder, result = future.result()
                        record_result(folder, result)
                except KeyboardInterrupt:
                    request_shutdown()
                    shutdown_executor_now(executor, futures)
                    raise
                else:
                    executor.shutdown(wait=True)
            else:
                for folder in runnable:
                    if shutdown_requested():
                        break
                    folder, result = process_folder(folder)
                    record_result(folder, result)

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
            return report
        finally:
            restore_thread_stdout_filter(restore_stdout)
            control_panel.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dedupe_duplicate_series_seasons(self, folders: list[ScannedFolder]) -> list[ScannedFolder]:
        """Drop duplicate series season folders with the same IMDb/title identity.

        Auto-created canonical-title folders can coexist with older user folders
        (for example `Jury Duty/s02` and empty `Jury Duty Presents/s02`). When
        both configs point to the same IMDb ID and season, only one should appear
        in the overview and download queue. Prefer the folder that already has
        media files.
        """
        best: dict[tuple[str, int], tuple[ScannedFolder, tuple[int, int]]] = {}
        passthrough: list[ScannedFolder] = []

        for folder in folders:
            if folder.folder_type != FolderType.SERIES:
                passthrough.append(folder)
                continue
            try:
                config, _ = load_config(folder.path)
            except Exception:
                passthrough.append(folder)
                continue

            identity = (config.imdb_id or config.title or folder.path.parent.name).casefold().strip()
            season = config.season if config.season is not None else folder.season_number
            if not identity or season is None:
                passthrough.append(folder)
                continue

            episode_count = config.episode_count or 0
            existing_count = len(detect_existing_season_episodes(folder.path, episode_count)) if episode_count > 0 else 0
            # Score: prefer folders with existing media, then enabled configs.
            score = (existing_count, 1 if config.enabled else 0)
            key = (identity, int(season))
            current = best.get(key)
            if current is None or score > current[1]:
                best[key] = (folder, score)

        chosen_series = {folder.path for folder, _score in best.values()}
        deduped: list[ScannedFolder] = []
        for folder in folders:
            if folder.folder_type == FolderType.SERIES:
                if folder.path in chosen_series:
                    deduped.append(folder)
            else:
                deduped.append(folder)
        for folder in passthrough:
            if folder not in deduped:
                deduped.append(folder)
        return deduped

    def _run_processor(
        self,
        folder: ScannedFolder,
        quiet: bool,
        progress_callback=None,
        max_workers: int = 1,
        bandwidth_limiter=None,
        worker_semaphore: threading.Semaphore | None = None,
    ) -> dict[str, Any]:
        processor = process_series if folder.folder_type == FolderType.SERIES else process_movies
        signature = inspect.signature(processor).parameters
        kwargs = {}
        if "progress_callback" in signature:
            kwargs["progress_callback"] = progress_callback
        if "max_workers" in signature:
            kwargs["max_workers"] = max_workers
        if "bandwidth_limiter" in signature:
            kwargs["bandwidth_limiter"] = bandwidth_limiter
        if "worker_semaphore" in signature:
            kwargs["worker_semaphore"] = worker_semaphore
        if "quiet_output" in signature:
            kwargs["quiet_output"] = quiet
        if quiet:
            with suppress_current_thread_output():
                return processor(folder.path, **kwargs)
        return processor(folder.path, **kwargs)

    def _series_overview_key(self, folder: ScannedFolder, config) -> tuple[str, str]:
        title = config.title or folder.path.parent.name.replace("-", " ").replace("_", " ").title()
        stable_id = config.imdb_id or title.casefold()
        return stable_id, title

    def _series_completion_overviews(self, folders: list[ScannedFolder]) -> str:
        """Build one library/checking table per series, aggregated across seasons."""
        series: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for folder in folders:
            if folder.folder_type != FolderType.SERIES:
                continue
            try:
                config, _ = load_config(folder.path)
            except Exception:
                continue
            stable_id, title = self._series_overview_key(folder, config)
            if stable_id not in series:
                series[stable_id] = {"title": title, "downloaded": 0, "total": 0, "unavailable": 0}
                order.append(stable_id)
            item = series[stable_id]
            item["title"] = title
            if not config.enabled and not config.episode_count:
                item["unavailable"] += 1
                continue
            if not config.episode_count or config.episode_count <= 0:
                continue
            existing = detect_existing_season_episodes(folder.path, config.episode_count)
            item["downloaded"] += min(len(existing), config.episode_count)
            item["total"] += config.episode_count

        rows: list[list[str]] = []
        for stable_id in order:
            item = series[stable_id]
            title = item["title"]
            downloaded = item["downloaded"]
            total = item["total"]
            if total:
                if downloaded >= total:
                    status = "✓"
                else:
                    percent = int(round((downloaded / total) * 100))
                    status = f"→ {percent}%"
                rows.append([title, f"{downloaded}/{total}", status])
            elif item["unavailable"]:
                rows.append([title, "--", "not available"])
            else:
                rows.append([title, "--", "pending"])

        if not rows:
            return ""
        return build_table(
            ["Series", "Episodes", "Status"],
            rows,
            colors=[ACCENT],
        )


def _result_count(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return len(value)
    return 0


def _result_items(value: Any, label: str, count: int) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if count:
        return [f"{count} {label}"]
    return []
