"""Tests for series module."""
import pytest
from pathlib import Path
import tempfile
import shutil

from py_stremio.components.series import detect_existing_episodes, plan_missing_episodes
from py_stremio.components.config_file import DownloadConfig, QualitySettings


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
