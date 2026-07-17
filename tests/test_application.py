"""Tests for the top-level application workflow."""
from types import SimpleNamespace
import json
import threading

from py_stremio.components import application
from py_stremio.components.library.library_scanner import FolderType, ScannedFolder

BASE_SETTINGS = {
    "PREFERRED_LANGUAGES": ["english"],
    "DRY_RUN": True,
}


def test_run_creates_metadata_rich_series_config_when_config_was_deleted(tmp_path, monkeypatch):
    season_folder = tmp_path / "series" / "House Of The Dragon" / "s01"
    season_folder.mkdir(parents=True)
    (tmp_path / "movies").mkdir()

    test_settings = SimpleNamespace(
        ROOT_FOLDER=tmp_path,
        SERIES_FOLDER=tmp_path / "series",
        MOVIES_FOLDER=tmp_path / "movies",
        **BASE_SETTINGS,
    )
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.library.library_scanner.settings", test_settings)
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata.get_series_metadata",
        lambda title, season: {
            "imdb_id": "tt11198330",
            "title": "House of the Dragon",
            "episode_count": 10,
        },
    )

    application.update_config_imdb_ids(quiet=True)

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
        "languages": ["english"],
        "language": "any",
        "subtitles": "english",
        "provider": "auto",
        "enabled": True,
        "title": "House of the Dragon",
        "imdb_id": "tt11198330",
        "season": 1,
        "episode_count": 10,
        "available_episodes": None,
        "current_episode_download": 1,
        "search_group": "S01",
        "download_all_related": True,
        "working_addons": [],
        "servers": [],
        "disabled_servers": [],
        "metadata_last_checked": config["metadata_last_checked"],
    }
    assert config["metadata_last_checked"]


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
        **BASE_SETTINGS,
    )
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.library.library_scanner.settings", test_settings)
    mock_meta = lambda title, season: {
        "imdb_id": "tt14986406",
        "title": "Bleach: Thousand-Year Blood War",
        "episode_count": 14,
    }
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_series_metadata", mock_meta)
    monkeypatch.setattr("py_stremio.services.metadata.get_series_metadata", mock_meta)

    application.update_config_imdb_ids(quiet=True)

    with open(season_folder / "download-config.json") as f:
        config = json.load(f)
    assert config["episode_count"] == 14
    assert config["current_episode_download"] == 15


def test_metadata_refresh_leaves_config_alone_when_season_unknown_to_imdb(tmp_path, monkeypatch):
    """When metadata can't find a season (e.g. One Piece S22 in IMDb), the
    metadata service should NOT disable the config or clear episode_count.
    Those are user preferences and manual overrides."""
    season_folder = tmp_path / "series" / "Poppa's House" / "s02"
    season_folder.mkdir(parents=True)
    (tmp_path / "movies").mkdir()

    test_settings = SimpleNamespace(
        ROOT_FOLDER=tmp_path,
        SERIES_FOLDER=tmp_path / "series",
        MOVIES_FOLDER=tmp_path / "movies",
        **BASE_SETTINGS,
    )
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.library.library_scanner.settings", test_settings)
    mock_meta = lambda title, season: {
        "imdb_id": "tt26678932",
        "title": "Poppa's House",
        "episode_count": None,
        "season_exists": False,
    }
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_series_metadata", mock_meta)
    monkeypatch.setattr("py_stremio.services.metadata.get_series_metadata", mock_meta)

    application.update_config_imdb_ids(quiet=True)

    with open(season_folder / "download-config.json") as f:
        config = json.load(f)
    # enabled should stay True — metadata service must not manage this flag
    assert config["enabled"] is True
    assert config["imdb_id"] == "tt26678932"
    assert config["season"] == 2
    # episode_count wasn't in the metadata and the metadata service
    # no longer clears user-set values
    assert config.get("episode_count") is None


def test_metadata_refresh_updates_existing_episode_list_when_config_already_has_episode_count(tmp_path, monkeypatch):
    from py_stremio.components.configs.config_file import DownloadConfig, save_config

    season_folder = tmp_path / "series" / "Rick and Morty" / "s00"
    season_folder.mkdir(parents=True)
    (tmp_path / "movies").mkdir()
    save_config(
        season_folder / "download-config.json",
        DownloadConfig(
            type="series",
            title="Rick and Morty",
            imdb_id="tt2861424",
            season=0,
            episode_count=8,
            current_episode_download=1,
        ),
    )
    test_settings = SimpleNamespace(
        ROOT_FOLDER=tmp_path,
        SERIES_FOLDER=tmp_path / "series",
        MOVIES_FOLDER=tmp_path / "movies",
        **BASE_SETTINGS,
    )
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.library.library_scanner.settings", test_settings)
    mock_meta = lambda title, season: {
        "imdb_id": "tt2861424",
        "title": "Rick and Morty",
        "episode_count": 2,
        "available_episodes": [1, 2],
        "season_exists": True,
    }
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_series_metadata", mock_meta)
    monkeypatch.setattr("py_stremio.services.metadata.get_series_metadata", mock_meta)

    application.update_config_imdb_ids(quiet=True)

    with open(season_folder / "download-config.json") as f:
        config = json.load(f)
    assert config["episode_count"] == 2
    assert config["available_episodes"] == [1, 2]


def test_full_run_metadata_uses_fresh_cache_without_network_lookup(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from py_stremio.components.configs.config_file import DownloadConfig, save_config
    from py_stremio.services.metadata import MetadataService

    season_folder = tmp_path / "series" / "Rick and Morty" / "s01"
    season_folder.mkdir(parents=True)
    save_config(
        season_folder / "download-config.json",
        DownloadConfig(
            type="series",
            title="Rick and Morty",
            imdb_id="tt2861424",
            season=1,
            episode_count=11,
            available_episodes=list(range(1, 12)),
            languages=["english"],
            metadata_last_checked=datetime.now(timezone.utc).isoformat(),
        ),
    )
    folder = ScannedFolder(season_folder, FolderType.SERIES, season_folder.parent, season_number=1)

    def fail_network_lookup(title, season):
        raise AssertionError("fresh metadata cache should skip Cinemeta lookup")

    monkeypatch.setattr("py_stremio.services.metadata.get_series_metadata", fail_network_lookup)

    updated = MetadataService().run(folders=[folder], quiet=True, use_cache=True)

    assert updated == 0


def test_full_run_metadata_refreshes_incomplete_cached_config(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from py_stremio.components.configs.config_file import DownloadConfig, save_config
    from py_stremio.services.metadata import MetadataService

    season_folder = tmp_path / "series" / "Futurama" / "s05"
    season_folder.mkdir(parents=True)
    save_config(
        season_folder / "download-config.json",
        DownloadConfig(
            type="series",
            title="Futurama",
            imdb_id="tt0149460",
            season=5,
            episode_count=None,
            available_episodes=None,
            languages=["english"],
            metadata_last_checked=datetime.now(timezone.utc).isoformat(),
        ),
    )
    folder = ScannedFolder(season_folder, FolderType.SERIES, season_folder.parent, season_number=5)
    calls = []

    def mock_meta(title, season):
        calls.append((title, season))
        return {
            "imdb_id": "tt0149460",
            "title": "Futurama",
            "episode_count": 16,
            "available_episodes": list(range(1, 17)),
            "season_exists": True,
        }

    monkeypatch.setattr("py_stremio.services.metadata.get_series_metadata", mock_meta)

    updated = MetadataService().run(folders=[folder], quiet=True, use_cache=True)

    assert updated == 1
    assert calls == [("Futurama", 5)]
    with open(season_folder / "download-config.json") as f:
        config = json.load(f)
    assert config["episode_count"] == 16
    assert config["available_episodes"] == list(range(1, 17))


def test_metadata_refresh_forces_network_even_when_cache_is_fresh(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from py_stremio.components.configs.config_file import DownloadConfig, save_config
    from py_stremio.services.metadata import MetadataService

    season_folder = tmp_path / "series" / "Rick and Morty" / "s01"
    season_folder.mkdir(parents=True)
    save_config(
        season_folder / "download-config.json",
        DownloadConfig(
            type="series",
            title="Rick and Morty",
            imdb_id="tt2861424",
            season=1,
            episode_count=11,
            available_episodes=list(range(1, 12)),
            languages=["english"],
            metadata_last_checked=datetime.now(timezone.utc).isoformat(),
        ),
    )
    folder = ScannedFolder(season_folder, FolderType.SERIES, season_folder.parent, season_number=1)
    calls = []

    def mock_meta(title, season):
        calls.append((title, season))
        return {
            "imdb_id": "tt2861424",
            "title": "Rick and Morty",
            "episode_count": 12,
            "available_episodes": list(range(1, 13)),
            "season_exists": True,
        }

    monkeypatch.setattr("py_stremio.services.metadata.get_series_metadata", mock_meta)

    updated = MetadataService().run(folders=[folder], quiet=True, use_cache=False)

    assert updated == 1
    assert calls == [("Rick and Morty", 1)]
    with open(season_folder / "download-config.json") as f:
        config = json.load(f)
    assert config["episode_count"] == 12


def test_scan_library_creates_current_year_next_season_folder(tmp_path, monkeypatch, capsys):
    series_root = tmp_path / "series"
    movies_root = tmp_path / "movies"
    (series_root / "Rick and Morty" / "s08").mkdir(parents=True)
    movies_root.mkdir(parents=True)
    test_settings = SimpleNamespace(
        ROOT_FOLDER=tmp_path,
        SERIES_FOLDER=series_root,
        MOVIES_FOLDER=movies_root,
        **BASE_SETTINGS,
    )
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.library.library_scanner.settings", test_settings)
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService._current_year",
        lambda self: 2026,
    )
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata.get_current_year_series_seasons",
        lambda title, year: [
            {"imdb_id": "tt2861424", "title": "Rick and Morty", "season": 9, "episode_count": 10}
        ] if title == "Rick and Morty" and year == 2026 else [],
    )

    folders = application.scan_library()

    assert (series_root / "Rick and Morty" / "s09").is_dir()
    assert any(folder.path == series_root / "Rick and Morty" / "s09" for folder in folders)
    output = capsys.readouterr().out
    assert "created Rick and Morty S09" in output


def test_scan_library_creates_current_year_season_for_empty_tracked_series(tmp_path, monkeypatch, capsys):
    series_root = tmp_path / "series"
    movies_root = tmp_path / "movies"
    (series_root / "Taskmaster").mkdir(parents=True)
    movies_root.mkdir(parents=True)
    test_settings = SimpleNamespace(
        ROOT_FOLDER=tmp_path,
        SERIES_FOLDER=series_root,
        MOVIES_FOLDER=movies_root,
        **BASE_SETTINGS,
    )
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.library.library_scanner.settings", test_settings)
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService._current_year",
        lambda self: 2026,
    )
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata.get_current_year_series_seasons",
        lambda title, year: [
            {"imdb_id": "tt4934214", "title": "Taskmaster", "season": 21, "episode_count": 9}
        ] if title == "Taskmaster" and year == 2026 else [],
    )

    folders = application.scan_library()

    assert (series_root / "Taskmaster" / "s21").is_dir()
    assert any(folder.path == series_root / "Taskmaster" / "s21" for folder in folders)
    output = capsys.readouterr().out
    assert "created Taskmaster S21" in output


def test_scan_library_does_not_create_missing_old_season_from_previous_year(tmp_path, monkeypatch):
    series_root = tmp_path / "series"
    movies_root = tmp_path / "movies"
    (series_root / "Rick and Morty" / "s08").mkdir(parents=True)
    movies_root.mkdir(parents=True)
    test_settings = SimpleNamespace(
        ROOT_FOLDER=tmp_path,
        SERIES_FOLDER=series_root,
        MOVIES_FOLDER=movies_root,
        **BASE_SETTINGS,
    )
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings", test_settings)
    monkeypatch.setattr("py_stremio.components.library.library_scanner.settings", test_settings)
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService._current_year",
        lambda self: 2026,
    )
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata.get_current_year_series_seasons",
        lambda title, year: [],
    )

    application.scan_library()

    assert not (series_root / "Rick and Morty" / "s09").exists()


def test_download_folders_lists_series_overview_instead_of_each_season(tmp_path, monkeypatch, capsys):
    series_root = tmp_path / "series"
    house_s01 = series_root / "House Of The Dragon" / "s01"
    house_s02 = series_root / "House Of The Dragon" / "s02"
    poppa_s01 = series_root / "Poppas House" / "s01"
    poppa_s02 = series_root / "Poppas House" / "s02"
    for folder in (house_s01, house_s02, poppa_s01, poppa_s02):
        folder.mkdir(parents=True)
    for episode in range(1, 11):
        (house_s01 / f"House.Of.The.Dragon.S01E{episode:02d}.mkv").write_bytes(b"done")
    for episode in range(1, 9):
        (house_s02 / f"House.Of.The.Dragon.S02E{episode:02d}.mkv").write_bytes(b"done")
    for episode in range(1, 19):
        (poppa_s01 / f"Poppas.House.S01E{episode:02d}.mkv").write_bytes(b"done")

    from py_stremio.components.configs.config_file import DownloadConfig, save_config

    save_config(house_s01 / "download-config.json", DownloadConfig(type="series", title="House of the Dragon", season=1, episode_count=10))
    save_config(house_s02 / "download-config.json", DownloadConfig(type="series", title="House of the Dragon", season=2, episode_count=8))
    save_config(poppa_s01 / "download-config.json", DownloadConfig(type="series", title="Poppa's House", season=1, episode_count=18))
    save_config(poppa_s02 / "download-config.json", DownloadConfig(type="series", title="Poppa's House", season=2, episode_count=None, enabled=False))
    folders = [
        ScannedFolder(house_s01, FolderType.SERIES, series_root, 1),
        ScannedFolder(house_s02, FolderType.SERIES, series_root, 2),
        ScannedFolder(poppa_s01, FolderType.SERIES, series_root, 1),
        ScannedFolder(poppa_s02, FolderType.SERIES, series_root, 2),
    ]
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService._run_processor",
        lambda self, folder, **kwargs: {"downloaded": 0, "failed": 0, "skipped": 0},
    )
    monkeypatch.setattr("py_stremio.services.download.print_and_send_report", lambda report: None)

    application.download_folders(folders=folders, max_workers=1)

    output = capsys.readouterr().out
    # Table now used instead of text lines
    assert "House of the Dragon" in output
    assert "Poppa's House" in output
    assert "18/18" in output
    assert "✓" in output
    assert "House Of The Dragon S01" not in output
    assert "House Of The Dragon S02" not in output
    assert "Poppas House S01" not in output
    assert "Poppas House S02" not in output


def test_download_folders_series_overview_shows_partial_download_percentage(tmp_path, monkeypatch, capsys):
    series_root = tmp_path / "series"
    season_folder = series_root / "Doctor Who (2023)" / "s01"
    season_folder.mkdir(parents=True)
    for episode in range(1, 3):
        (season_folder / f"Doctor.Who.2023.S01E{episode:02d}.mkv").write_bytes(b"done")

    from py_stremio.components.configs.config_file import DownloadConfig, save_config

    save_config(
        season_folder / "download-config.json",
        DownloadConfig(type="series", title="Doctor Who (2023)", season=1, episode_count=8),
    )
    folders = [ScannedFolder(season_folder, FolderType.SERIES, series_root, 1)]
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService._run_processor",
        lambda self, folder, **kwargs: {"downloaded": 0, "failed": 0, "skipped": 0},
    )
    monkeypatch.setattr("py_stremio.services.download.print_and_send_report", lambda report: None)

    application.download_folders(folders=folders, max_workers=1)

    output = capsys.readouterr().out
    assert "Doctor Who (2023)" in output
    assert "2/8" in output
    assert "→ 25%" in output
    assert "Doctor Who (2023) S01" not in output


def test_download_folders_deduplicates_same_imdb_season_preferring_folder_with_files(tmp_path, monkeypatch, capsys):
    series_root = tmp_path / "series"
    real_s02 = series_root / "Jury Duty" / "s02"
    duplicate_s02 = series_root / "Jury Duty Presents" / "s02"
    real_s02.mkdir(parents=True)
    duplicate_s02.mkdir(parents=True)
    for episode in [1, 2, 3, 4, 8]:
        (real_s02 / f"Jury Duty Presents_s02e{episode:02d}.mkv").write_bytes(b"done")

    from py_stremio.components.configs.config_file import DownloadConfig, save_config

    for folder in (real_s02, duplicate_s02):
        save_config(
            folder / "download-config.json",
            DownloadConfig(
                type="series",
                title="Jury Duty Presents",
                imdb_id="tt22074164",
                season=2,
                episode_count=8,
                available_episodes=[1, 2, 3, 4, 5, 6, 7, 8],
            ),
        )

    folders = [
        ScannedFolder(real_s02, FolderType.SERIES, series_root, 2),
        ScannedFolder(duplicate_s02, FolderType.SERIES, series_root, 2),
    ]
    processed = []

    def fake_run_processor(self, folder, **kwargs):
        processed.append(folder.path)
        return {"downloaded": 0, "failed": 0, "skipped": 0}

    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService._run_processor",
        fake_run_processor,
    )
    monkeypatch.setattr("py_stremio.services.download.print_and_send_report", lambda report: None)

    application.download_folders(folders=folders, max_workers=1)

    output = capsys.readouterr().out
    assert processed == [real_s02]
    assert "5/8" in output
    assert "5/16" not in output


def test_download_folders_starts_next_season_when_thread_capacity_exists(tmp_path, monkeypatch):
    folders = [
        ScannedFolder(tmp_path / "series" / "Show" / "s01", FolderType.SERIES, tmp_path / "series", 1),
        ScannedFolder(tmp_path / "series" / "Show" / "s02", FolderType.SERIES, tmp_path / "series", 2),
    ]
    started: list[str] = []
    seen_kwargs: list[dict] = []
    first_saw_second_before_finishing = []
    lock = threading.Lock()

    def fake_run_processor(self, folder, **kwargs):
        with lock:
            started.append(folder.path.name)
            seen_kwargs.append(kwargs)
        if folder.season_number == 1:
            threading.Event().wait(0.05)
            with lock:
                first_saw_second_before_finishing.append("s02" in started)
        return {"downloaded": [], "failed": [], "skipped": 0}

    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService._run_processor",
        fake_run_processor,
    )
    monkeypatch.setattr("py_stremio.services.download.print_and_send_report", lambda report: None)

    application.download_folders(folders=folders, max_workers=2)

    assert first_saw_second_before_finishing == [True]
    assert [kwargs["max_workers"] for kwargs in seen_kwargs] == [2, 2]
    assert seen_kwargs[0]["worker_semaphore"] is seen_kwargs[1]["worker_semaphore"]
    assert seen_kwargs[0]["worker_semaphore"] is not None


def test_download_folders_ctrl_c_cancels_pending_workers_without_waiting(tmp_path, monkeypatch):
    from py_stremio.services.download import DownloadService
    from py_stremio.utils.cancellation import clear_shutdown

    folders = [
        ScannedFolder(tmp_path / "series" / "Show" / "s01", FolderType.SERIES, tmp_path / "series", 1),
        ScannedFolder(tmp_path / "series" / "Show" / "s02", FolderType.SERIES, tmp_path / "series", 2),
    ]
    shutdown_calls = []
    cancelled = []

    class FakeFuture:
        def __init__(self, folder):
            self.folder = folder

        def result(self):
            return self.folder, {"downloaded": [], "failed": [], "skipped": 0}

        def cancel(self):
            cancelled.append(self.folder.path.name)
            return True

    class FakeExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers
            self.futures = []

        def submit(self, func, folder):
            future = FakeFuture(folder)
            self.futures.append(future)
            return future

        def shutdown(self, wait=True, *, cancel_futures=False):
            shutdown_calls.append((wait, cancel_futures))

    executors = []

    def fake_executor(max_workers):
        executor = FakeExecutor(max_workers)
        executors.append(executor)
        return executor

    def interrupting_as_completed(futures):
        raise KeyboardInterrupt()
        yield from ()

    monkeypatch.setattr("py_stremio.services.download.ThreadPoolExecutor", fake_executor)
    monkeypatch.setattr("py_stremio.services.download.as_completed", interrupting_as_completed)
    monkeypatch.setattr("py_stremio.services.download.print_and_send_report", lambda report: None)

    try:
        DownloadService().run(folders, max_workers=2)
    except KeyboardInterrupt:
        pass
    finally:
        clear_shutdown()

    assert shutdown_calls == [(False, True)]
    assert sorted(cancelled) == ["s01", "s02"]
