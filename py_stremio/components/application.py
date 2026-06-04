"""Application workflow for py-stremio download manager."""
import contextlib
import inspect
import io
import json
import sys
from datetime import datetime
from typing import Any

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


def _progress_line(event: dict[str, Any]) -> str:
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
    return f"  • {title} {episode_label} {bar}  (episode {current}/{total})"


def _make_progress_printer(stream) -> Any:
    last_len = 0

    def printer(event: dict[str, Any]) -> None:
        nonlocal last_len
        line = _progress_line(event)
        padding = " " * max(0, last_len - len(line))
        print(f"\r{line}{padding}", end="", file=stream, flush=True)
        last_len = len(line)
        if event.get("type") == "episode_done":
            print(file=stream, flush=True)
            last_len = 0

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

            if config.get("imdb_id") and config.get("episode_count") and config.get("type") == "series":
                save_config(config_path, config_model)
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


def _run_processor(folder: ScannedFolder, quiet: bool, progress_callback=None) -> dict[str, Any]:
    processor = process_series if folder.folder_type == FolderType.SERIES else process_movies
    kwargs = {"progress_callback": progress_callback} if "progress_callback" in inspect.signature(processor).parameters else {}
    if quiet:
        with contextlib.redirect_stdout(io.StringIO()):
            return processor(folder.path, **kwargs)
    return processor(folder.path, **kwargs)


def download_folders(folders: list[ScannedFolder] | None = None, quiet: bool = True) -> ReportData:
    """Download missing items for folders and print a compact modern report."""
    if folders is None:
        folders = Scanner().scan()

    print(_c("\n⬇ Downloads", ACCENT))
    report_folders: list[dict[str, Any]] = []
    total_downloaded = 0
    total_failed = 0
    processed = 0
    skipped = 0

    for folder in folders:
        label = "series" if folder.folder_type == FolderType.SERIES else "movies"
        display_name = folder.path.parent.name if folder.folder_type == FolderType.SERIES else folder.path.name
        suffix = f" S{folder.season_number:02d}" if folder.season_number else ""
        print(f"  • {display_name}{suffix}")

        if folder.folder_type not in (FolderType.SERIES, FolderType.MOVIES):
            print(_c("    skipped", DIM))
            continue

        progress = _make_progress_printer(sys.stdout)
        result = _run_processor(folder, quiet=quiet, progress_callback=progress)
        if result.get("skipped") is True:
            skipped += 1
            print(_c(f"skipped ({result.get('reason', 'disabled')})", YELLOW))
            report_folders.append({
                "name": folder.path.name,
                "type": folder.folder_type.value,
                "path": str(folder.path),
                "skipped": True,
                "reason": result.get("reason", "unknown"),
                "downloaded": [],
                "failed": [],
            })
            continue

        processed += 1
        downloaded_count = _result_count(result.get("downloaded", 0))
        failed_count = _result_count(result.get("failed", 0))
        total_downloaded += downloaded_count
        total_failed += failed_count

        status = _c(f"✓ {downloaded_count} downloaded", GREEN) if failed_count == 0 else _c(f"! {failed_count} failed", RED)
        if downloaded_count and failed_count:
            status = f"{_c(f'✓ {downloaded_count}', GREEN)} / {_c(f'! {failed_count}', RED)}"
        print(status)

        report_folders.append({
            "name": folder.path.name,
            "type": folder.folder_type.value,
            "path": str(folder.path),
            "downloaded": _result_items(result.get("downloaded", []), "downloaded", downloaded_count),
            "failed": _result_items(result.get("failed", []), "failed", failed_count),
            "downloaded_count": downloaded_count,
            "failed_count": failed_count,
        })

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


def run_pipeline(download: bool = True, quiet: bool = True) -> None:
    """Run the standard scan → metadata → optional download pipeline."""
    _banner()
    folders = scan_library()
    print(_c("\n🧠 Metadata", ACCENT))
    update_config_imdb_ids(quiet=False)
    if download:
        download_folders(folders, quiet=quiet)


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
        download_folders(quiet=True)
    elif choice == "4" or choice == "":
        folders = scan_library()
        print(_c("\n🧠 Metadata", ACCENT))
        update_config_imdb_ids(quiet=False)
        download_folders(folders, quiet=True)
    elif choice == "5":
        print("Bye.")
    else:
        print(_c("Unknown option. Choose 1-5.", RED))


def run(interactive: bool | None = None) -> None:
    """CLI entry point.

    Interactive terminals show a menu. Non-interactive runs keep the historical
    scan → metadata → download behavior so tests/scripts do not block on input.
    """
    args = set(sys.argv[1:])
    if "--scan" in args:
        _banner()
        scan_library()
        return
    if "--metadata" in args or "--config" in args:
        _banner()
        print(_c("\n🧠 Metadata", ACCENT))
        update_config_imdb_ids(quiet=False)
        return
    if "--download" in args or "--run" in args or "--all" in args:
        run_pipeline(download=True, quiet=True)
        return

    if interactive is None:
        interactive = sys.stdin.isatty()
    if interactive:
        run_menu()
    else:
        run_pipeline(download=True, quiet=True)
