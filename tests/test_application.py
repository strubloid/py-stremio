"""Tests for the top-level application workflow."""
from types import SimpleNamespace
import json
import threading

from py_stremio.components import application
from py_stremio.components.scanner import FolderType, ScannedFolder


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


def test_metadata_refresh_creates_config_at_next_episode_when_absolute_numbered_season_exists(tmp_path, monkeypatch):
    season_folder = tmp_path / "series" / "Bleach Thousand-Year Blood War" / "s03"
    season_folder.mkdir(parents=True)
    (tmp_path / "movies").mkdir()
    for absolute_episode in range(27, 41):
        filename = f"[Lazier] Bleach Thousand-Year Blood War - {absolute_episode} (WEB 1080p EAC3).mkv"
        (season_folder / filename).write_bytes(b"already downloaded")

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
            "imdb_id": "tt14986406",
            "title": "Bleach: Thousand-Year Blood War",
            "episode_count": 14,
        },
    )

    application.update_config_imdb_ids(quiet=True)

    with open(season_folder / "download-config.json") as f:
        config = json.load(f)
    assert config["episode_count"] == 14
    assert config["current_episode_download"] == 15


def test_download_folders_starts_next_season_when_thread_capacity_exists(tmp_path, monkeypatch):
    folders = [
        ScannedFolder(tmp_path / "series" / "Show" / "s01", FolderType.SERIES, tmp_path / "series", 1),
        ScannedFolder(tmp_path / "series" / "Show" / "s02", FolderType.SERIES, tmp_path / "series", 2),
    ]
    started: list[str] = []
    seen_kwargs: list[dict] = []
    first_saw_second_before_finishing = []
    lock = threading.Lock()

    def fake_run_processor(folder, **kwargs):
        with lock:
            started.append(folder.path.name)
            seen_kwargs.append(kwargs)
        if folder.season_number == 1:
            threading.Event().wait(0.05)
            with lock:
                first_saw_second_before_finishing.append("s02" in started)
        return {"downloaded": [], "failed": [], "skipped": 0}

    monkeypatch.setattr(application, "_run_processor", fake_run_processor)
    monkeypatch.setattr(application, "print_and_send_report", lambda report: None)

    application.download_folders(folders=folders, max_workers=2)

    assert first_saw_second_before_finishing == [True]
    assert [kwargs["max_workers"] for kwargs in seen_kwargs] == [2, 2]
    assert seen_kwargs[0]["worker_semaphore"] is seen_kwargs[1]["worker_semaphore"]
    assert seen_kwargs[0]["worker_semaphore"] is not None
