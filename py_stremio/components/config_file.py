"""Configuration file management."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json

from .utils import parse_season_from_folder


@dataclass
class QualitySettings:
    preferred: str = "1080p"
    fallbacks: list[str] | None = None
    allow_higher: bool = False
    allow_lower: bool = True

    def __post_init__(self):
        if self.fallbacks is None:
            self.fallbacks = ["720p", "480p"]


@dataclass
class DownloadConfig:
    type: str
    quality: QualitySettings | None = field(default_factory=QualitySettings)
    languages: list[str] | None = None
    language: str = "any"
    subtitles: str = "any"
    provider: str = "auto"
    enabled: bool = True

    title: str | None = None
    imdb_id: str | None = None
    season: int | None = None
    episode_count: int | None = None
    available_episodes: list[int] | None = None
    current_episode_download: int = 1
    search_group: str | None = None
    download_all_related: bool = True
    working_addons: list[str] = field(default_factory=list)
    servers: list[str] = field(default_factory=list)


def create_series_config(folder_path: Path) -> DownloadConfig:
    """Create a default series config from folder path."""
    parsed_season = parse_season_from_folder(folder_path.name)
    season = parsed_season if parsed_season is not None else 1
    return DownloadConfig(
        type="series",
        title=folder_path.parent.name.replace("-", " ").replace("_", " ").title(),
        season=season,
        imdb_id=None,
        search_group=f"S{season:02d}",
    )


def create_movies_config(folder_path: Path) -> DownloadConfig:
    """Create a default movies config from folder path."""
    return DownloadConfig(
        type="movies",
        search_group=folder_path.name.replace("-", " ").replace("_", " ").title(),
    )


def is_series_season_folder(folder_path: Path) -> bool:
    """Return True for folders shaped like series/{show}/S01."""
    return folder_path.parent.parent.name == "series" and parse_season_from_folder(folder_path.name) is not None


def get_default_config(folder_path: Path) -> DownloadConfig:
    """Get appropriate default config based on folder shape."""
    from .settings import settings
    cfg = create_series_config(folder_path) if is_series_season_folder(folder_path) else create_movies_config(folder_path)
    if settings.PREFERRED_LANGUAGES and cfg.languages is None:
        cfg.languages = list(settings.PREFERRED_LANGUAGES)
    return cfg


def repair_series_season_config(folder_path: Path, config: DownloadConfig) -> bool:
    """Fix stale or malformed configs inside series season folders."""
    if not is_series_season_folder(folder_path):
        return False

    changed = False
    series_defaults = create_series_config(folder_path)
    configured_season = config.season
    if config.type != "series":
        config.type = "series"
        changed = True
    if not config.title:
        config.title = series_defaults.title
        changed = True
    if config.season != series_defaults.season:
        config.season = series_defaults.season
        changed = True
    search_group_season = parse_season_from_folder(config.search_group or "")
    if not config.search_group or (
        search_group_season is not None
        and configured_season is not None
        and search_group_season == configured_season
        and search_group_season != series_defaults.season
    ):
        config.search_group = f"S{config.season:02d}"
        changed = True
    return changed


def load_config(folder_path: Path) -> tuple[DownloadConfig, Path]:
    """Load config from folder, creating default if missing."""
    config_path = folder_path / "download-config.json"
    if not config_path.exists():
        config = get_default_config(folder_path)
        save_config(config_path, config)
        return config, config_path
    with open(config_path) as f:
        data = json.load(f)
    quality_data = data.pop("quality", None)
    quality = QualitySettings(**quality_data) if quality_data else QualitySettings()
    data["current_episode_download"] = max(1, int(data.get("current_episode_download") or 1))
    config = DownloadConfig(quality=quality, **data)
    if repair_series_season_config(folder_path, config):
        save_config(config_path, config)
    return config, config_path


def save_config(config_path: Path, config: DownloadConfig) -> None:
    """Save config to file."""
    data = asdict(config)
    if data.get("quality") and isinstance(data["quality"], dict):
        data["quality"] = data["quality"]
    else:
        data["quality"] = asdict(data["quality"]) if data.get("quality") else None
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)