"""Tests for config-driven download processing."""
import json
from types import SimpleNamespace

from py_stremio.components.config_file import DownloadConfig, QualitySettings, save_config
from py_stremio.components.download_processing import process_season_folder


def _download_settings():
    return SimpleNamespace(LIMIT_EPISODES=0, MIN_COMPLETED_VIDEO_SIZE_MB=0)


def test_process_season_folder_downloads_all_missing_episodes_by_default(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=3,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    result = process_season_folder(tmp_path)

    assert calls == [1, 2, 3]
    assert result["downloaded"] == 3


def test_process_season_folder_uses_current_episode_download_as_start_episode(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=4,
        current_episode_download=3,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(tmp_path)

    assert calls == [3, 4]


def test_process_season_folder_persists_next_episode_after_each_success(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=3,
        current_episode_download=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    saved_during_download = []

    def fake_search_and_download(**kwargs):
        with open(tmp_path / "download-config.json") as f:
            saved_during_download.append(json.load(f).get("current_episode_download"))
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(tmp_path)

    with open(tmp_path / "download-config.json") as f:
        saved = json.load(f)
    assert saved_during_download == [1, 2, 3]
    assert saved["current_episode_download"] == 4


def test_process_season_folder_does_not_redownload_existing_generated_episode_file(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House of the Dragon",
        season=1,
        episode_count=2,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    (tmp_path / "House of the Dragon_s01e01.mkv").write_bytes(b"already downloaded")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    result = process_season_folder(tmp_path)

    assert calls == [2]
    assert result["downloaded"] == 1
    assert result["skipped"] == 1


def test_process_season_folder_resumes_partial_part_file(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House of The Dragon",
        season=1,
        episode_count=2,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    partial = tmp_path / "House of The Dragon_s01e02.mkv.part"
    partial.write_bytes(b"partial")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": str(tmp_path / "House of The Dragon_s01e02.mkv"),
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(tmp_path)

    assert calls == [1, 2]


def test_process_season_folder_treats_tiny_untracked_generated_file_as_interrupted_download(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House of the Dragon",
        season=1,
        episode_count=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    interrupted = tmp_path / "House of the Dragon_s01e01.mkv"
    interrupted.write_bytes(b"partial")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        assert (tmp_path / "House of the Dragon_s01e01.mkv.part").exists()
        return {
            "success": True,
            "filename": str(tmp_path / "House of the Dragon_s01e01.mkv"),
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr(
        "py_stremio.components.download_processing.settings",
        SimpleNamespace(LIMIT_EPISODES=0, MIN_COMPLETED_VIDEO_SIZE_MB=100),
    )

    process_season_folder(tmp_path)

    assert calls == [1]
