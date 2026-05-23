"""Tests for config_file module."""
import pytest
from pathlib import Path
import tempfile
import json
import shutil

from py_stremio.components.config_file import (
    DownloadConfig,
    QualitySettings,
    create_series_config,
    create_movies_config,
    load_config,
    save_config,
    get_default_config,
)


class TestQualitySettings:
    def test_default_fallbacks(self):
        q = QualitySettings()
        assert q.preferred == "1080p"
        assert q.fallbacks == ["720p", "480p"]

    def test_custom_fallbacks(self):
        q = QualitySettings(preferred="720p", fallbacks=["1080p", "480p"])
        assert q.fallbacks == ["1080p", "480p"]


class TestDownloadConfig:
    def test_series_config_creation(self):
        cfg = create_series_config(Path("/series/show/s03"))
        assert cfg.type == "series"
        assert cfg.season == 3

    def test_movies_config_creation(self):
        cfg = create_movies_config(Path("/movies/batman"))
        assert cfg.type == "movies"


class TestConfigFileIO:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    def test_load_creates_default_config(self, temp_folder):
        config, path = load_config(temp_folder)
        assert path.exists()
        assert config.type == "movies"

    def test_save_and_load_config(self, temp_folder):
        config = DownloadConfig(
            type="series",
            title="Test Show",
            season=2,
            quality=QualitySettings(preferred="720p"),
        )
        config_path = temp_folder / "download-config.json"
        save_config(config_path, config)
        loaded, _ = load_config(temp_folder)
        assert loaded.title == "Test Show"
        assert loaded.season == 2
        assert loaded.quality.preferred == "720p"

    def test_load_existing_config(self, temp_folder):
        data = {
            "type": "series",
            "title": "Existing Show",
            "season": 1,
            "enabled": False,
            "quality": {"preferred": "480p", "fallbacks": ["720p"]},
        }
        config_path = temp_folder / "download-config.json"
        with open(config_path, "w") as f:
            json.dump(data, f)
        config, _ = load_config(temp_folder)
        assert config.title == "Existing Show"
        assert config.enabled is False
