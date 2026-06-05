"""Tests for movies module."""
import pytest
from pathlib import Path
import tempfile
import shutil

from py_stremio.components.configs.config_file import DownloadConfig
from py_stremio.components.download.provider import DownloadResult
from py_stremio.components.library.movie import detect_existing_movies, process_movies


class TestDetectExistingMovies:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    def test_detects_movies(self, temp_folder):
        (temp_folder / "Movie A.mkv").touch()
        (temp_folder / "Movie B.mp4").touch()
        movies = detect_existing_movies(temp_folder)
        assert "Movie A" in movies
        assert "Movie B" in movies

    def test_ignores_non_video_files(self, temp_folder):
        (temp_folder / "Movie.mkv").touch()
        (temp_folder / "cover.jpg").touch()
        movies = detect_existing_movies(temp_folder)
        assert len(movies) == 1

    def test_empty_folder(self, temp_folder):
        movies = detect_existing_movies(temp_folder)
        assert movies == set()


def test_process_movies_uses_default_quality_when_config_quality_is_missing(monkeypatch, tmp_path):
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
            assert filename == "Movie Folder_[1080p].mkv"
            assert qualities == ["1080p", "720p", "480p"]
            return DownloadResult(success=True, filename=filename, quality="1080p", provider="mock")

    monkeypatch.setattr(
        "py_stremio.components.library.movie.load_config",
        lambda folder_path: (DownloadConfig(type="movies", quality=None, search_group=None), folder_path / "download-config.json"),
    )
    monkeypatch.setattr("py_stremio.components.library.movie.load_state", lambda folder_path: FakeState())
    monkeypatch.setattr("py_stremio.components.library.movie.save_state", lambda folder_path, state: saved_states.append(state))
    monkeypatch.setattr("py_stremio.components.library.movie.Downloader", FakeDownloader)

    result = process_movies(tmp_path / "movie-folder")

    assert result["downloaded"] == [{"quality": "1080p"}]
    assert saved_states
