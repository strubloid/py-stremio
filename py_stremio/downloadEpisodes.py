"""Download episodes based on state and config files."""
from pathlib import Path
import sys
import re

from .config_file import load_config, save_config
from .state import load_state, save_state
from .utils import parse_episode_number
from .settings import settings
from .stremio_client import search_and_download


def find_season_folders(root_folder: Path) -> list[Path]:
    """Find all season folders with state/config files."""
    season_folders = []
    series_root = root_folder / "series"
    if not series_root.exists():
        return season_folders
    for show_folder in series_root.iterdir():
        if not show_folder.is_dir():
            continue
        for season_folder in show_folder.iterdir():
            if not season_folder.is_dir():
                continue
            state_file = season_folder / ".download-state.json"
            config_file = season_folder / "download-config.json"
            if state_file.exists() or config_file.exists():
                season_folders.append(season_folder)
    return season_folders


def find_movie_folders(root_folder: Path) -> list[Path]:
    """Find all movie folders with state/config files."""
    movie_folders = []
    movies_root = root_folder / "movies"
    if not movies_root.exists():
        return movie_folders
    for group_folder in movies_root.iterdir():
        if not group_folder.is_dir():
            continue
        state_file = group_folder / ".download-state.json"
        config_file = group_folder / "download-config.json"
        if state_file.exists() or config_file.exists():
            movie_folders.append(group_folder)
    return movie_folders


def scan_folder_for_episodes(folder_path: Path) -> list[dict]:
    """Scan folder and return list of episode files with their info."""
    episodes = []
    if not folder_path.exists():
        return episodes

    for file_path in folder_path.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in [".mkv", ".mp4", ".avi", ".mov"]:
            episode_num = parse_episode_number(file_path.name)
            episodes.append({
                "path": file_path,
                "filename": file_path.name,
                "episode": episode_num,
            })
    return sorted(episodes, key=lambda x: x["episode"] or 0)


def process_season_folder(folder_path: Path) -> dict:
    """Process a season folder - download missing episodes from Stremio."""
    config, config_path = load_config(folder_path)
    state = load_state(folder_path)

    if not config.enabled:
        return {"skipped": True, "reason": "disabled"}

    if not config.title:
        return {"skipped": True, "reason": "no title in config"}

    season = config.season or 1
    quality = config.quality.preferred if config.quality else "1080p"
    imdb_id = config.imdb_id

    episodes = scan_folder_for_episodes(folder_path)
    existing_episodes = {ep["episode"] for ep in episodes if ep["episode"]}

    all_episodes = list(range(1, (config.episode_count or 20) + 1))
    missing = [e for e in all_episodes if e not in existing_episodes and not state.is_downloaded(f"episode_{e}.mkv")]

    # Limit episodes per run
    missing = missing[:settings.LIMIT_EPISODES]

    downloaded = 0
    skipped = 0
    failed = 0

    servers = config.servers.copy() if config.servers else []

    for episode_num in missing:
        print(f"  Downloading {config.title} S{season:02d}E{episode_num:02d}")

        result = search_and_download(
            title=config.title,
            imdb_id=imdb_id,
            season=season,
            episode=episode_num,
            folder_path=str(folder_path),
            preferred_quality=quality,
            working_addons=servers
        )

        if result.get("success"):
            filename = result.get("filename", f"episode_{episode_num}.mkv")
            state.add_download(filename, result.get("quality", quality), "stremio")
            downloaded += 1
        else:
            state.mark_failed(f"episode_{episode_num}", result.get("error", "failed"), 1)
            failed += 1

        if result.get("working_urls"):
            for url in result["working_urls"]:
                if url not in servers:
                    servers.append(url)
                    print(f"    ✓ Found working server: {url}")

    if servers and servers != config.servers:
        config.servers = servers
        save_config(config_path, config)
        print(f"  Saved {len(servers)} working servers to config")

    for ep in episodes:
        if not state.is_downloaded(ep["filename"]):
            state.add_download(ep["filename"], quality, "stremio")
            skipped += 1

    save_state(folder_path, state)

    return {
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
    }


def process_movie_folder(folder_path: Path) -> dict:
    """Process a movie folder - download missing content from Stremio."""
    config, _ = load_config(folder_path)
    state = load_state(folder_path)

    if not config.enabled:
        return {"skipped": True, "reason": "disabled"}

    files = list(folder_path.iterdir())
    video_files = [f for f in files if f.is_file() and f.suffix.lower() in [".mkv", ".mp4", ".avi", ".mov"]]

    if video_files:
        for file_path in video_files:
            if not state.is_downloaded(file_path.name):
                quality = config.quality.preferred if config.quality else "1080p"
                state.add_download(file_path.name, quality, "stremio")
        save_state(folder_path, state)
        return {"downloaded": 0, "skipped": len(video_files)}

    title = config.search_group or config.title or folder_path.name
    quality = config.quality.preferred if config.quality else "1080p"

    print(f"  Searching for movie: {title}")

    result = search_and_download(
        title=title,
        season=None,
        episode=None,
        folder_path=str(folder_path),
        preferred_quality=quality
    )

    if result.get("success"):
        filename = result.get("filename", f"{title}.mkv")
        state.add_download(filename, result.get("quality", quality), "stremio")
        save_state(folder_path, state)
        return {"downloaded": 1, "skipped": 0}
    else:
        return {"downloaded": 0, "skipped": 0, "failed": 1, "error": result.get("error")}


def run_downloads(root_folder: Path | None = None) -> dict:
    """Run all downloads based on state and config files."""
    if root_folder is None:
        root_folder = Path(settings.ROOT_FOLDER)

    results = {
        "series": [],
        "movies": [],
        "total_downloaded": 0,
        "total_skipped": 0,
        "total_failed": 0,
    }

    season_folders = find_season_folders(root_folder)
    for folder in season_folders:
        print(f"Processing series: {folder.name}")
        result = process_season_folder(folder)
        results["series"].append({"folder": str(folder), **result})
        results["total_downloaded"] += result.get("downloaded", 0)
        results["total_skipped"] += result.get("skipped", 0)
        results["total_failed"] += result.get("failed", 0)

    movie_folders = find_movie_folders(root_folder)
    for folder in movie_folders:
        print(f"Processing movies: {folder.name}")
        result = process_movie_folder(folder)
        results["movies"].append({"folder": str(folder), **result})
        results["total_downloaded"] += result.get("downloaded", 0)
        results["total_skipped"] += result.get("skipped", 0)
        results["total_failed"] += result.get("failed", 0)

    return results


def main():
    """CLI entry point."""
    root = sys.argv[1] if len(sys.argv) > 1 else settings.ROOT_FOLDER
    root_path = Path(root)

    if not root_path.exists():
        print(f"Error: Root folder does not exist: {root}")
        sys.exit(1)

    print(f"Starting downloads from: {root_path}")
    results = run_downloads(root_path)

    print("\n=== Download Summary ===")
    print(f"Total Downloaded: {results['total_downloaded']}")
    print(f"Total Skipped: {results['total_skipped']}")
    print(f"Total Failed: {results['total_failed']}")


if __name__ == "__main__":
    main()