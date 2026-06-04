"""Tests for the top-level application workflow."""
from types import SimpleNamespace
import json

from py_stremio.components import application


def test_run_creates_metadata_rich_series_config_when_config_was_deleted(tmp_path, monkeypatch):
    season_folder = tmp_path / "series" / "House Of The Dragon" / "s01"
    season_folder.mkdir(parents=True)
    (tmp_path / "movies").mkdir()

    test_settings = SimpleNamespace(
        ROOT_FOLDER=tmp_path,
        SERIES_FOLDER=tmp_path / "series",
        MOVIES_FOLDER=tmp_path / "movies",
        DRY_RUN=True,
    )
    monkeypatch.setattr("py_stremio.components.application.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.scanner.settings", test_settings)
    monkeypatch.setattr(
        "py_stremio.components.stremio_metadata.get_series_metadata",
        lambda title, season: {
            "imdb_id": "tt11198330",
            "title": "House of the Dragon",
            "episode_count": 10,
        },
    )
    monkeypatch.setattr(application, "process_series", lambda folder: {"downloaded": [], "failed": [], "skipped": 0})
    monkeypatch.setattr(application, "print_and_send_report", lambda report: None)

    application.run()

    with open(season_folder / "download-config.json") as f:
        config = json.load(f)

    assert config == {
        "type": "series",
        "quality": {
            "preferred": "1080p",
            "fallbacks": ["720p", "480p"],
            "allow_higher": False,
            "allow_lower": True,
        },
        "language": "any",
        "subtitles": "any",
        "provider": "auto",
        "enabled": True,
        "title": "House of the Dragon",
        "imdb_id": "tt11198330",
        "season": 1,
        "episode_count": 10,
        "current_episode_download": 1,
        "search_group": "S01",
        "download_all_related": True,
        "working_addons": [],
        "servers": [],
    }
