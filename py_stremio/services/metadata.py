"""MetadataService — enrich series folders with Cinemeta/IMDb metadata."""
import json

from py_stremio.components.configs.app_settings import settings
from py_stremio.components.configs.config_file import load_config
from py_stremio.components.library.library_scanner import Scanner, FolderType
from py_stremio.components.library.media_file import infer_next_episode_download
from py_stremio.components.stremio.stremio_client import get_series_imdb_id
from py_stremio.components.stremio.stremio_metadata import get_series_metadata
from py_stremio.utils.media import parse_season_from_folder


ACCENT = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


class MetadataService:
    """Fetch and update IMDb IDs, episode counts, and titles for series folders."""

    def __init__(self):
        self.scanner = Scanner()

    def run(self, folders: list | None = None, quiet: bool = False) -> int:
        """Update metadata for all series folders. Returns number of configs updated."""
        if folders is None:
            folders = self.scanner.scan()
        updated = 0

        for folder in folders:
            if folder.folder_type != FolderType.SERIES:
                continue

            try:
                changed = self._update_folder_metadata(folder, quiet)
                if changed:
                    updated += 1
            except Exception as e:
                print(f"  ! Error updating {folder.path / 'download-config.json'}: {e}")

        if not quiet:
            print(_c(f"  ✓ Metadata refresh complete ({updated} updated)", GREEN))
        return updated

    def _update_folder_metadata(self, folder, quiet: bool) -> bool:
        """Update a single folder's download-config.json. Returns True if changed."""
        config_model, config_path = load_config(folder.path)
        config = {
            "type": config_model.type,
            "quality": {
                "preferred": config_model.quality.preferred,
                "fallbacks": config_model.quality.fallbacks,
                "allow_higher": config_model.quality.allow_higher,
                "allow_lower": config_model.quality.allow_lower,
            } if config_model.quality else None,
            "languages": config_model.languages,
            "language": config_model.language,
            "subtitles": config_model.subtitles,
            "provider": config_model.provider,
            "enabled": config_model.enabled,
            "title": config_model.title,
            "imdb_id": config_model.imdb_id,
            "season": config_model.season,
            "episode_count": config_model.episode_count,
            "available_episodes": config_model.available_episodes,
            "current_episode_download": config_model.current_episode_download,
            "search_group": config_model.search_group,
            "download_all_related": config_model.download_all_related,
            "working_addons": config_model.working_addons,
            "servers": config_model.servers,
        }

        changed = False

        # Inject preferred languages from settings if config doesn't have them
        if settings.PREFERRED_LANGUAGES and not config.get("languages"):
            config["languages"] = list(settings.PREFERRED_LANGUAGES)
            changed = True

        next_existing_episode = infer_next_episode_download(folder.path, config.get("episode_count"))
        if next_existing_episode and next_existing_episode > int(config.get("current_episode_download") or 1):
            config["current_episode_download"] = next_existing_episode
            config_model.current_episode_download = next_existing_episode
            changed = True

        title = config.get("title")
        season = config.get("season")

        if not title:
            title = folder.path.parent.name.replace("-", " ").replace("_", " ").title()
            config["title"] = title
            changed = True

        if season is None:
            parsed_season = parse_season_from_folder(folder.path.name)
            season = parsed_season if parsed_season is not None else (folder.season_number if folder.season_number is not None else 1)
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
            season_exists = metadata.get("season_exists")
            episode_count = metadata.get("episode_count")
            if season_exists is False:
                if config.get("enabled") is not False:
                    config["enabled"] = False
                    changed = True
                if config.get("episode_count") is not None:
                    config["episode_count"] = None
                    changed = True
                if config.get("available_episodes") != []:
                    config["available_episodes"] = []
                    changed = True
                if not quiet:
                    print(f"     ! {config.get('title')} S{season:02d} has no episodes in metadata; disabled")
            else:
                if episode_count and config.get("episode_count") != episode_count:
                    config["episode_count"] = episode_count
                    changed = True
                if "available_episodes" in metadata and config.get("available_episodes") != metadata.get("available_episodes"):
                    config["available_episodes"] = metadata.get("available_episodes")
                    changed = True
                if season_exists is True and config.get("enabled") is False:
                    config["enabled"] = True
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

        return changed
