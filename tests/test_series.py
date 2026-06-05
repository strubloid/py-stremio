"""Tests for series module."""
import pytest
from pathlib import Path
import tempfile
import shutil

from py_stremio.components.download.provider import DownloadResult
from py_stremio.components.library.series import detect_existing_episodes, plan_missing_episodes, process_series
from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings


class TestDetectExistingEpisodes:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    def test_detects_episodes(self, temp_folder):
        (temp_folder / "Episode 01.mkv").touch()
        (temp_folder / "Episode 02.mp4").touch()
        (temp_folder / "E03.avi").touch()
        episodes = detect_existing_episodes(temp_folder)
        assert episodes == {1, 2, 3}

    def test_ignores_non_video_files(self, temp_folder):
        (temp_folder / "Episode 01.mkv").touch()
        (temp_folder / "readme.txt").touch()
        episodes = detect_existing_episodes(temp_folder)
        assert episodes == {1}

    def test_empty_folder(self, temp_folder):
        episodes = detect_existing_episodes(temp_folder)
        assert episodes == set()


class TestPlanMissingEpisodes:
    def test_plans_missing_episodes(self):
        config = DownloadConfig(
            type="series",
            episode_count=5,
            quality=QualitySettings(),
        )
        existing = {1, 2, 3}
        missing = plan_missing_episodes(config, existing)
        assert missing == [4, 5]

    def test_no_missing_when_complete(self):
        config = DownloadConfig(
            type="series",
            episode_count=3,
            quality=QualitySettings(),
        )
        existing = {1, 2, 3}
        missing = plan_missing_episodes(config, existing)
        assert missing == []

    def test_no_planning_when_episode_count_null(self):
        config = DownloadConfig(type="series", episode_count=None)
        missing = plan_missing_episodes(config, set())
        assert missing == []


def test_process_series_uses_safe_defaults_for_missing_optional_config(monkeypatch, tmp_path):
    season_folder = tmp_path / "some-show" / "s01"
    season_folder.mkdir(parents=True)
    saved_states = []

    class FakeState:
        def is_downloaded(self, filename):
            return False

        def add_download(self, filename, quality, provider):
            self.filename = filename
            self.quality = quality
            self.provider = provider

    class FakeDownloader:
        def __init__(self, folder_path, config):
            self.folder_path = folder_path
            self.config = config

        def download_with_fallback(self, filename, qualities):
            assert filename == "Some Show_S01E01_[1080p].mkv"
            assert qualities == ["1080p", "720p", "480p"]
            return DownloadResult(success=True, filename=filename, quality="1080p", provider="mock")

    monkeypatch.setattr(
        "py_stremio.components.library.series.load_config",
        lambda folder_path: (
            DownloadConfig(type="series", quality=None, title=None, season=None, episode_count=1),
            folder_path / "download-config.json",
        ),
    )
    monkeypatch.setattr("py_stremio.components.library.series.load_state", lambda folder_path: FakeState())
    monkeypatch.setattr("py_stremio.components.library.series.save_state", lambda folder_path, state: saved_states.append(state))
    monkeypatch.setattr("py_stremio.components.library.series.detect_existing_episodes", lambda folder_path: set())
    monkeypatch.setattr("py_stremio.components.library.series.Downloader", FakeDownloader)

    result = process_series(season_folder)

    assert result["downloaded"] == [{"episode": 1, "quality": "1080p"}]
    assert saved_states
