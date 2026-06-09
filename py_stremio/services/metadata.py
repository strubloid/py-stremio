"""MetadataService — enrich series folders with Cinemeta/IMDb metadata."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from py_stremio.components.configs.app_settings import settings
from py_stremio.components.configs.config_file import load_config
from py_stremio.components.library.library_scanner import Scanner, FolderType
from py_stremio.components.library.media_file import infer_next_episode_download
from py_stremio.components.stremio.stremio_client import get_series_imdb_id
from py_stremio.components.stremio.stremio_metadata import get_imdb_id, get_series_metadata
from py_stremio.services.progress import ACCENT, GREEN, YELLOW, RED, RESET, build_table
from py_stremio.utils.media import parse_season_from_folder
from py_stremio.utils.atomic_write import atomic_write_json
from py_stremio.utils.cancellation import clear_shutdown, request_shutdown, shutdown_executor_now, shutdown_requested


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


_METADATA_WORKERS = 4


class MetadataService:
    """Fetch and update IMDb IDs, episode counts, and titles for series folders."""

    def __init__(self):
        self.scanner = Scanner()

    def run(self, folders: list | None = None, quiet: bool = False, use_cache: bool = False) -> int:
        """Update metadata for all series and movie folders. Returns number of configs updated."""
        clear_shutdown()
        if folders is None:
            folders = self.scanner.scan()
        updated = 0
        rows: list[list[str]] = []

        series_folders = [f for f in folders if f.folder_type == FolderType.SERIES]
        movie_folders = [f for f in folders if f.folder_type == FolderType.MOVIES]

        # ── Series metadata ────────────────────────────────────────────────
        if len(series_folders) > 1:
            executor = ThreadPoolExecutor(max_workers=min(_METADATA_WORKERS, len(series_folders)))
            future_map = {}
            try:
                future_map = {
                    executor.submit(self._update_folder_metadata, folder, quiet, use_cache=use_cache): folder
                    for folder in series_folders
                }
                for future in as_completed(future_map):
                    if shutdown_requested():
                        break
                    folder = future_map[future]
                    try:
                        changed, status = future.result()
                        if changed:
                            updated += 1
                            if status:
                                rows.append(status)
                    except Exception as e:
                        print(f"  ! Error updating {folder.path / 'download-config.json'}: {e}")
            except KeyboardInterrupt:
                request_shutdown()
                shutdown_executor_now(executor, future_map.keys())
                raise
            else:
                executor.shutdown(wait=True)
        else:
            for folder in series_folders:
                if shutdown_requested():
                    break
                try:
                    changed, status = self._update_folder_metadata(folder, quiet, use_cache=use_cache)
                    if changed:
                        updated += 1
                        if status:
                            rows.append(status)
                except Exception as e:
                    print(f"  ! Error updating {folder.path / 'download-config.json'}: {e}")

        # ── Movie metadata ──────────────────────────────────────────────────
        for folder in movie_folders:
            if shutdown_requested():
                break
            try:
                changed = self._update_movie_metadata(folder, use_cache=use_cache)
                if changed:
                    updated += 1
            except Exception as e:
                print(f"  ! Error updating movie {folder.path / 'download-config.json'}: {e}")

        if not quiet and rows:
            print()
            print(build_table(
                ["Series", "Season", "Episodes", "IMDb", "Status"],
                rows,
                colors=[ACCENT],
            ))

        if not quiet:
            print(_c(f"  ✓ Metadata refresh complete ({updated} updated)", GREEN))
        return updated

    def _update_folder_metadata(self, folder, quiet: bool, use_cache: bool = False) -> tuple[bool, list[str] | None]:
        """Update a single folder's download-config.json. Returns (changed, status_row)."""
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
            "disabled_servers": config_model.disabled_servers,
            "metadata_last_checked": config_model.metadata_last_checked,
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

        # Build display status row (used in table if not quiet)
        status_row: list[str] | None = None
        folder_title = folder.path.parent.name.replace("-", " ").replace("_", " ").title()
        canonical_title = config.get("title") or folder_title
        season_label = f"S{season:02d}"

        if use_cache and self._metadata_cache_fresh(config):
            if changed:
                atomic_write_json(config_path, config, indent=2)
            ep_display = str(config.get("episode_count") or "?")
            imdb_display = config.get("imdb_id") or "--"
            return changed, [canonical_title, season_label, ep_display, imdb_display, "cached"]

        metadata = get_series_metadata(title, season)
        checked_at = datetime.now(timezone.utc).isoformat()
        if metadata:
            imdb_id = metadata.get("imdb_id")
            if imdb_id:
                config["imdb_id"] = imdb_id
                config["type"] = "series"
                changed = True
            canonical_title = metadata.get("title") or canonical_title
            if metadata.get("title") and config.get("title") != metadata.get("title"):
                config["title"] = metadata.get("title")
                changed = True
            season_exists = metadata.get("season_exists")
            episode_count = metadata.get("episode_count")
            if season_exists is False:
                # Don't touch enabled/episode_count/available_episodes — those are
                # user preferences and manual overrides. The data source
                # (Cinemeta / IMDb TSV) sometimes doesn't list seasons for
                # long-running anime (e.g. One Piece), so disabling the config
                # would be destructive.
                status_row = [canonical_title, season_label, "--", "--", "not found"]
            else:
                if episode_count and config.get("episode_count") != episode_count:
                    config["episode_count"] = episode_count
                    changed = True
                if "available_episodes" in metadata and config.get("available_episodes") != metadata.get("available_episodes"):
                    config["available_episodes"] = metadata.get("available_episodes")
                    changed = True
                ep_display = str(episode_count) if episode_count else "?"
                imdb_display = config.get("imdb_id") or "--"
                status_row = [canonical_title, season_label, ep_display, imdb_display, "✓"]
        else:
            imdb_id = get_series_imdb_id(title, season)
            if imdb_id:
                config["imdb_id"] = imdb_id
                config["type"] = "series"
                changed = True
                status_row = [canonical_title, season_label, "--", imdb_id, "not found"]
            else:
                status_row = [canonical_title, season_label, "--", "--", "not found"]

        config["metadata_last_checked"] = checked_at
        changed = True

        next_existing_episode = infer_next_episode_download(folder.path, config.get("episode_count"))
        if next_existing_episode and next_existing_episode > int(config.get("current_episode_download") or 1):
            config["current_episode_download"] = next_existing_episode
            changed = True

        if changed:
            atomic_write_json(config_path, config, indent=2)

        return changed, status_row

    def _update_movie_metadata(self, folder, use_cache: bool = False) -> bool:
        """Update a single movie folder's download-config.json with IMDb ID and title.

        Returns True if the config was changed.
        """
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
            "disabled_servers": config_model.disabled_servers,
            "metadata_last_checked": config_model.metadata_last_checked,
        }

        # Inject preferred languages from settings if config doesn't have them
        changed = False
        if settings.PREFERRED_LANGUAGES and not config.get("languages"):
            config["languages"] = list(settings.PREFERRED_LANGUAGES)
            changed = True

        # Movies don't track episode download progress — null it out
        if config.get("current_episode_download", 0) > 0:
            config["current_episode_download"] = 0
            config_model.current_episode_download = 0
            changed = True

        title = config.get("title") or config.get("search_group") or folder.path.name
        checked_text = config.get("metadata_last_checked")
        use_cached = False
        if use_cache and config.get("imdb_id") and title and checked_text:
            try:
                checked_at = datetime.fromisoformat(str(checked_text).replace("Z", "+00:00"))
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                cache_hours = max(0, int(getattr(settings, "METADATA_CACHE_HOURS", 24)))
                use_cached = datetime.now(timezone.utc) - checked_at < timedelta(hours=cache_hours)
            except ValueError:
                pass

        if use_cached:
            if changed:
                atomic_write_json(config_path, config, indent=2)
            return changed

        # Try to get IMDB ID from Cinemeta
        imdb_id = config.get("imdb_id") or get_imdb_id(title)

        if imdb_id and config.get("imdb_id") != imdb_id:
            config["imdb_id"] = imdb_id
            config_model.imdb_id = imdb_id
            changed = True

        if not config.get("title") and title:
            config["title"] = title
            config_model.title = title
            changed = True

        checked_at = datetime.now(timezone.utc).isoformat()
        config["metadata_last_checked"] = checked_at
        if imdb_id:
            changed = True

        if changed:
            atomic_write_json(config_path, config, indent=2)

        return changed

    def _metadata_cache_fresh(self, config: dict) -> bool:
        """Return True when cached metadata is complete and recent enough for full runs."""
        if not config.get("title") or not config.get("imdb_id") or config.get("season") is None:
            return False
        if not config.get("episode_count"):
            return False
        checked_text = config.get("metadata_last_checked")
        if not checked_text:
            return False
        try:
            checked_at = datetime.fromisoformat(str(checked_text).replace("Z", "+00:00"))
        except ValueError:
            return False
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        cache_hours = max(0, int(getattr(settings, "METADATA_CACHE_HOURS", 24)))
        return datetime.now(timezone.utc) - checked_at < timedelta(hours=cache_hours)
