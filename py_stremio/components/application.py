"""Application workflow for py-stremio download manager."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import inspect
import json
import sys
import threading
import time
from datetime import datetime
from typing import Any

from .bandwidth import build_limiter
from .output import install_thread_stdout_filter, restore_thread_stdout_filter, suppress_current_thread_output
from .settings import settings
from .scanner import Scanner, FolderType, ScannedFolder
from .download_processing import process_movie_folder as process_movies
from .download_processing import process_season_folder as process_series
from .report import ReportData, print_and_send_report


ACCENT = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"


def _supports_color() -> bool:
    return sys.stdout.isatty()


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if _supports_color() else text


def _format_bytes(byte_count: int) -> str:
    if byte_count < 1024:
        return f"{byte_count} B"
    if byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f} KB"
    mb = byte_count / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"


def render_progress_bar(current: int, total: int, width: int = 24) -> str:
    """Render a compact 0-100% progress bar."""
    if total <= 0:
        return f"[{'?' * width}] {_format_bytes(current)}"
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(width * ratio))
    percent = int(round(ratio * 100))
    return f"[{'█' * filled}{'-' * (width - filled)}] {percent}% {_format_bytes(current)} / {_format_bytes(total)}"


def _color(text: str, color: str, enabled: bool) -> str:
    return f"{color}{text}{RESET}" if enabled else text


def _speed_label(rate_bps: int | float | None) -> str:
    if not rate_bps or rate_bps <= 0:
        return ""
    return f" · {_format_bytes(int(rate_bps))}/s"


def _color_bar(bar: str, enabled: bool) -> str:
    if not enabled or not bar.startswith("[") or "]" not in bar:
        return bar
    close = bar.index("]")
    segment = bar[1:close]
    rest = bar[close + 1:]
    filled_count = segment.count("█")
    filled = _color("█" * filled_count, GREEN, True)
    empty = _color(segment[filled_count:], DIM, True)
    return f"[{filled}{empty}]{_color(rest, YELLOW, True)}"


def _progress_line(event: dict[str, Any], color: bool = False) -> str:
    title = event.get("title") or "Download"
    season = event.get("season")
    episode = event.get("episode")
    current = event.get("current", 0)
    total = event.get("total", 0)
    episode_label = f"S{season:02d}E{episode:02d}" if season and episode else "movie"
    if event.get("type") == "bytes":
        bar = render_progress_bar(event.get("downloaded", 0), event.get("bytes_total", 0))
    elif event.get("type") == "episode_start":
        bar = render_progress_bar(0, 100)
    elif event.get("type") == "episode_done":
        downloaded = event.get("downloaded")
        bytes_total = event.get("bytes_total")
        if downloaded is not None and bytes_total:
            bar = render_progress_bar(downloaded, bytes_total)
        else:
            bar = render_progress_bar(100, 100)
    else:
        bar = render_progress_bar(current, total)
    title_label = _color(str(title), ACCENT, color)
    episode_label = _color(episode_label, GREEN, color)
    bar = _color_bar(bar, color)
    speed = _color(_speed_label(event.get("rate_bps")), GREEN, color)
    episode_position = _color(f"episode {current}/{total}", DIM, color)
    return f"  {_color('•', GREEN, color)} {title_label} {episode_label} {bar}{speed}  ({episode_position})"


def _progress_key(event: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (event.get("title"), event.get("season"), event.get("episode"))


def _make_progress_printer(stream) -> Any:
    """Return a progress renderer that keeps concurrent episodes on separate lines."""
    active_lines: dict[tuple[Any, Any, Any], str] = {}
    order: list[tuple[Any, Any, Any]] = []
    rendered_count = 0
    last_redraw_at = 0.0
    min_redraw_interval = 0.10
    lock = threading.Lock()
    use_ansi_block = bool(getattr(stream, "isatty", lambda: False)())

    def redraw(force: bool = False) -> None:
        nonlocal rendered_count, last_redraw_at
        now = time.monotonic()
        if not force and use_ansi_block and now - last_redraw_at < min_redraw_interval:
            return
        previous_count = rendered_count
        if use_ansi_block and previous_count:
            stream.write("\033[F" * previous_count)
        for key in order:
            line = active_lines[key]
            if use_ansi_block:
                stream.write(f"\r\033[K{line}\n")
            else:
                stream.write(f"{line}\n")
        if use_ansi_block and previous_count > len(order):
            extra_lines = previous_count - len(order)
            for _ in range(extra_lines):
                stream.write("\r\033[K\n")
            stream.write("\033[F" * extra_lines)
        stream.flush()
        rendered_count = len(order) if use_ansi_block else 0
        last_redraw_at = now

    def printer(event: dict[str, Any]) -> None:
        with lock:
            key = _progress_key(event)
            if event.get("type") == "episode_done":
                active_lines.pop(key, None)
                if key in order:
                    order.remove(key)
                redraw(force=True)
                return
            is_new_line = key not in active_lines
            if is_new_line:
                order.append(key)
            active_lines[key] = _progress_line(event, color=use_ansi_block)
            redraw(force=is_new_line or event.get("type") == "episode_start")

    return printer


def _banner() -> None:
    mode = "DRY RUN" if settings.DRY_RUN else "LIVE"
    print()
    print(_c("╭────────────────────────────────────╮", ACCENT))
    print(_c("│  ✦ Py-Stremio Download Manager ✦   │", ACCENT))
    print(_c("╰────────────────────────────────────╯", ACCENT))
    print(f"  Mode: {_c(mode, GREEN if settings.DRY_RUN else YELLOW)}")
    print(f"  Root: {settings.ROOT_FOLDER}")


def _menu() -> None:
    print()
    print(_c("Choose a step", ACCENT))
    print("  1  🔎 Scan library")
    print("  2  🧠 Refresh configs + metadata")
    print("  3  ⬇  Download missing episodes/movies")
    print("  4  ✨ Run all: scan → metadata → download")
    print("  5  🚪 Exit")


def scan_library() -> list[ScannedFolder]:
    """Scan configured folders and print a compact folder overview."""
    scanner = Scanner()
    scanner.ensure_folders()
    folders = scanner.scan()

    print(_c("\n🔎 Scan", ACCENT))
    if not folders:
        print("  No folders found yet.")
        return folders

    print(f"  Found {len(folders)} folder(s)")
    for index, folder in enumerate(folders, start=1):
        label = "series" if folder.folder_type == FolderType.SERIES else "movies"
        season = f" · S{folder.season_number:02d}" if folder.season_number else ""
        print(f"  {index:>2}. {label:<6} {folder.path.parent.name if label == 'series' else folder.path.name}{season}")
    return folders


def update_config_imdb_ids(quiet: bool = False) -> None:
    """Create/update series download-config.json files with metadata."""
    from .config_file import load_config, save_config
    from .media_files import infer_next_episode_download
    from .stremio_client import get_series_imdb_id
    from .stremio_metadata import get_series_metadata
    from .utils import parse_season_from_folder

    scanner = Scanner()
    folders = scanner.scan()
    updated = 0

    for folder in folders:
        if folder.folder_type != FolderType.SERIES:
            continue

        try:
            config_model, config_path = load_config(folder.path)
            config = {
                "type": config_model.type,
                "quality": {
                    "preferred": config_model.quality.preferred,
                    "fallbacks": config_model.quality.fallbacks,
                    "allow_higher": config_model.quality.allow_higher,
                    "allow_lower": config_model.quality.allow_lower,
                } if config_model.quality else None,
                "language": config_model.language,
                "subtitles": config_model.subtitles,
                "provider": config_model.provider,
                "enabled": config_model.enabled,
                "title": config_model.title,
                "imdb_id": config_model.imdb_id,
                "season": config_model.season,
                "episode_count": config_model.episode_count,
                "current_episode_download": config_model.current_episode_download,
                "search_group": config_model.search_group,
                "download_all_related": config_model.download_all_related,
                "working_addons": config_model.working_addons,
                "servers": config_model.servers,
            }

            changed = False
            next_existing_episode = infer_next_episode_download(folder.path, config.get("episode_count"))
            if next_existing_episode and next_existing_episode > int(config.get("current_episode_download") or 1):
                config["current_episode_download"] = next_existing_episode
                config_model.current_episode_download = next_existing_episode
                changed = True

            if config.get("imdb_id") and config.get("episode_count") and config.get("type") == "series":
                if changed:
                    with open(config_path, "w") as f:
                        json.dump(config, f, indent=2)
                    updated += 1
                else:
                    save_config(config_path, config_model)
                continue

            title = config.get("title")
            season = config.get("season")

            if not title:
                title = folder.path.parent.name.replace("-", " ").replace("_", " ").title()
                config["title"] = title
                changed = True

            if not season:
                season = parse_season_from_folder(folder.path.name) or folder.season_number or 1
                config["season"] = season
                changed = True

            if not quiet:
                print(f"  🧠 {folder.path.parent.name} S{season:02d}")
            metadata = get_series_metadata(title, season)
            if metadata:
                imdb_id = metadata.get("imdb_id")
                if imdb_id:
                    config["imdb_id"] = imdb_id
                    config["type"] = "series"
                    changed = True
                canonical_title = metadata.get("title")
                if canonical_title and config.get("title") != canonical_title:
                    config["title"] = canonical_title
                    changed = True
                episode_count = metadata.get("episode_count")
                if episode_count and config.get("episode_count") != episode_count:
                    config["episode_count"] = episode_count
                    changed = True
                if not quiet:
                    print(f"     ✓ {config.get('title')} · {config.get('imdb_id')} · {config.get('episode_count') or '?'} eps")
            else:
                imdb_id = get_series_imdb_id(title, season)
                if imdb_id:
                    config["imdb_id"] = imdb_id
                    config["type"] = "series"
                    changed = True
                elif not quiet:
                    print(f"     ! metadata not found for {title} S{season}")

            next_existing_episode = infer_next_episode_download(folder.path, config.get("episode_count"))
            if next_existing_episode and next_existing_episode > int(config.get("current_episode_download") or 1):
                config["current_episode_download"] = next_existing_episode
                changed = True

            if changed:
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2)
                updated += 1
        except Exception as e:
            print(f"  ! Error updating {folder.path / 'download-config.json'}: {e}")

    if not quiet:
        print(_c(f"  ✓ Metadata refresh complete ({updated} updated)", GREEN))


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


def _run_processor(
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


def download_folders(
    folders: list[ScannedFolder] | None = None,
    quiet: bool = True,
    max_workers: int = 1,
    speed_percent: int | None = None,
) -> ReportData:
    """Download missing items for folders and print a compact modern report."""
    if folders is None:
        folders = Scanner().scan()

    print(_c("\n⬇ Downloads", ACCENT))
    speed_percent = getattr(settings, "INTERNET_SPEED_LIMIT", 100) if speed_percent is None else speed_percent
    bandwidth_limiter = build_limiter(speed_percent, getattr(settings, "INTERNET_MAX_SPEED_MBPS", 100))
    print(f"  Threads: {max_workers} · speed: {speed_percent}%")
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
    progress = _make_progress_printer(progress_stream)
    worker_semaphore = threading.Semaphore(max_workers) if max_workers > 1 else None

    def folder_display(folder: ScannedFolder) -> str:
        display_name = folder.path.parent.name if folder.folder_type == FolderType.SERIES else folder.path.name
        suffix = f" S{folder.season_number:02d}" if folder.season_number else ""
        return f"{display_name}{suffix}"

    for folder in folders:
        print(f"  • {_c(folder_display(folder), ACCENT)}")
        if folder.folder_type not in (FolderType.SERIES, FolderType.MOVIES):
            skipped += 1
            print(_c("    skipped", DIM))
            continue
        runnable.append(folder)

    def process_folder(folder: ScannedFolder) -> tuple[ScannedFolder, dict[str, Any]]:
        # The semaphore enforces the global thread limit across every season.
        # Each season may queue more episodes, so when one download finishes the
        # next episode can start immediately instead of waiting for the whole
        # season/folder processor to finish.
        per_folder_workers = max_workers
        return folder, _run_processor(
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
            print(_c(f"  {folder_display(folder)} skipped ({result.get('reason', 'disabled')})", YELLOW))
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

        status = _c(f"✓ {downloaded_count} downloaded", GREEN) if failed_count == 0 else _c(f"! {failed_count} failed", RED)
        if downloaded_count and failed_count:
            status = f"{_c(f'✓ {downloaded_count}', GREEN)} / {_c(f'! {failed_count}', RED)}"
        print(f"  {folder_display(folder)} {status}")

        report_folders.append({
            "name": folder.path.name,
            "type": folder.folder_type.value,
            "path": str(folder.path),
            "downloaded": _result_items(result.get("downloaded", []), "downloaded", downloaded_count),
            "failed": _result_items(result.get("failed", []), "failed", failed_count),
            "downloaded_count": downloaded_count,
            "failed_count": failed_count,
        })

    if max_workers > 1 and len(runnable) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_folder, folder) for folder in runnable]
            for future in as_completed(futures):
                folder, result = future.result()
                record_result(folder, result)
    else:
        for folder in runnable:
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
    restore_thread_stdout_filter(restore_stdout)
    return report


def run_pipeline(download: bool = True, quiet: bool = True, max_workers: int = 1, speed_percent: int | None = None) -> None:
    """Run the standard scan → metadata → optional download pipeline."""
    _banner()
    folders = scan_library()
    print(_c("\n🧠 Metadata", ACCENT))
    update_config_imdb_ids(quiet=False)
    if download:
        download_folders(folders, quiet=quiet, max_workers=max_workers, speed_percent=speed_percent)


def _ask_download_threads() -> int:
    default = max(1, getattr(settings, "DOWNLOAD_THREADS", 1))
    answer = input(_c(f"Download threads [{default}] › ", ACCENT)).strip()
    if not answer:
        return default
    try:
        return max(1, int(answer))
    except ValueError:
        return default


def run_menu() -> None:
    """Interactive terminal menu for py-stremio."""
    _banner()
    _menu()
    choice = input(_c("Select 1-5 › ", ACCENT)).strip()

    if choice == "1":
        scan_library()
    elif choice == "2":
        print(_c("\n🧠 Metadata", ACCENT))
        update_config_imdb_ids(quiet=False)
    elif choice == "3":
        download_folders(quiet=True, max_workers=_ask_download_threads())
    elif choice == "4" or choice == "":
        folders = scan_library()
        print(_c("\n🧠 Metadata", ACCENT))
        update_config_imdb_ids(quiet=False)
        download_folders(folders, quiet=True, max_workers=_ask_download_threads())
    elif choice == "5":
        print("Bye.")
    else:
        print(_c("Unknown option. Choose 1-5.", RED))


def run(interactive: bool | None = None) -> None:
    """CLI entry point.

    Interactive terminals show a menu. Non-interactive runs keep the historical
    scan → metadata → download behavior so tests/scripts do not block on input.
    """
    raw_args = sys.argv[1:]
    args = set(raw_args)
    positional = [arg for arg in raw_args if not arg.startswith("--")]
    action = positional[0] if positional else None
    speed_percent = int(positional[1]) if len(positional) > 1 and positional[1].isdigit() else None
    max_workers = max(1, getattr(settings, "DOWNLOAD_THREADS", 1))

    if "--scan" in args or action == "1":
        _banner()
        scan_library()
        return
    if "--metadata" in args or "--config" in args or action == "2":
        _banner()
        print(_c("\n🧠 Metadata", ACCENT))
        update_config_imdb_ids(quiet=False)
        return
    if "--download" in args or action == "3":
        _banner()
        download_folders(quiet=True, max_workers=max_workers, speed_percent=speed_percent)
        return
    if "--run" in args or "--all" in args or action == "4":
        run_pipeline(download=True, quiet=True, max_workers=max_workers, speed_percent=speed_percent)
        return

    if interactive is None:
        interactive = sys.stdin.isatty()
    if interactive:
        run_menu()
    else:
        run_pipeline(download=True, quiet=True, max_workers=max_workers, speed_percent=speed_percent)
