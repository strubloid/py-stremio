"""Tests for scanner module."""
import pytest
from pathlib import Path
import tempfile
import shutil

from py_stremio.components.scanner import Scanner, FolderType, ScannedFolder


class TestScanner:
    @pytest.fixture
    def temp_root(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    @pytest.fixture
    def scanner(self, temp_root):
        scanner = Scanner()
        scanner.root = temp_root
        scanner.series_root = temp_root / "series"
        scanner.movies_root = temp_root / "movies"
        return scanner

    def test_ensure_folders_creates_directories(self, scanner, temp_root):
        scanner.ensure_folders()
        assert scanner.series_root.exists()
        assert scanner.movies_root.exists()

    def test_scan_empty_root(self, scanner):
        folders = scanner.scan()
        assert folders == []

    def test_scan_finds_series_folders(self, scanner, temp_root):
        (temp_root / "series" / "MyShow" / "s01").mkdir(parents=True)
        (temp_root / "series" / "MyShow" / "s02").mkdir(parents=True)
        folders = scanner.scan()
        assert len(folders) == 2
        assert all(f.folder_type == FolderType.SERIES for f in folders)

    def test_scan_finds_movie_folders(self, scanner, temp_root):
        (temp_root / "movies" / "Action").mkdir(parents=True)
        (temp_root / "movies" / "Comedy").mkdir(parents=True)
        folders = scanner.scan()
        assert len(folders) == 2
        assert all(f.folder_type == FolderType.MOVIES for f in folders)

    def test_scan_extracts_season_number(self, scanner, temp_root):
        (temp_root / "series" / "Show" / "s05").mkdir(parents=True)
        folders = scanner.scan()
        assert folders[0].season_number == 5

    def test_scan_ignores_non_matching_folders(self, scanner, temp_root):
        (temp_root / "series" / "Show").mkdir(parents=True)
        (temp_root / "series" / "Show" / "season1").mkdir(parents=True)
        (temp_root / "series" / "Show" / "fall").mkdir(parents=True)
        folders = scanner.scan()
        assert len(folders) == 0
