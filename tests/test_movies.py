"""Tests for movies module."""
import pytest
from pathlib import Path
import tempfile
import shutil

from py_stremio.components.library.movie import detect_existing_movies


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
