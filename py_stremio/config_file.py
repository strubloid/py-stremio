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
    quality: QualitySettings | None = None
    language: str = "any"
    subtitles: str = "any"
    provider: str = "auto"
    enabled: bool = True

    title: str | None = None
    imdb_id: str | None = None
    season: int | None = None
    episode_count: int | None = None
    search_group: str | None = None
    download_all_related: bool = True
    working_addons: list[str] = field(default_factory=list)
    servers: list[str] = field(default_factory=list)


def create_series_config(folder_path: Path) -> DownloadConfig:
    """Create a default series config from folder path."""
    season = parse_season_from_folder(folder_path.name) or 1
    return DownloadConfig(
        type="series",
        title=folder_path.parent.name.replace("-", " ").replace("_", " ").title(),
        season=season,
        imdb_id=None,
    )


def create_movies_config(folder_path: Path) -> DownloadConfig:
    """Create a default movies config from folder path."""
    return DownloadConfig(
        type="movies",
        search_group=folder_path.name.replace("-", " ").replace("_", " ").title(),
    )


def get_default_config(folder_path: Path) -> DownloadConfig:
    """Get appropriate default config based on parent folder."""
    parent = folder_path.parent.name
    if parent == "series":
        return create_series_config(folder_path)
    return create_movies_config(folder_path)


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
    config = DownloadConfig(quality=quality, **data)
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