"""Tests for state module."""
import pytest
from pathlib import Path
import tempfile
import json
import shutil

from py_stremio.components.state import DownloadState, DownloadRecord, load_state, save_state


class TestDownloadRecord:
    def test_record_creation(self):
        record = DownloadRecord(
            filename="test.mkv",
            quality="1080p",
            provider="mock",
        )
        assert record.filename == "test.mkv"
        assert record.quality == "1080p"
        assert record.provider == "mock"
        assert record.attempts == 1


class TestDownloadState:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    @pytest.fixture
    def state(self, temp_folder):
        return DownloadState(folder_path=temp_folder)

    def test_add_download(self, state):
        state.add_download("test.mkv", "1080p", "mock")
        assert state.is_downloaded("test.mkv")
        assert state.total_downloaded == 1

    def test_is_downloaded_false(self, state):
        assert not state.is_downloaded("nonexistent.mkv")

    def test_mark_failed(self, state):
        state.mark_failed("test.mkv", "Connection error", 1)
        assert state.was_attempted("test.mkv") == 1


class TestStatePersistence:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    def test_save_and_load_state(self, temp_folder):
        state = DownloadState(folder_path=temp_folder)
        state.add_download("test.mkv", "1080p", "mock")
        state.mark_failed("fail.mkv", "Error", 2)
        save_state(temp_folder, state)

        loaded = load_state(temp_folder)
        assert loaded.is_downloaded("test.mkv")
        assert loaded.was_attempted("fail.mkv") == 2
        assert loaded.total_downloaded == 1

    def test_load_nonexistent_creates_new_state(self, temp_folder):
        state = load_state(temp_folder)
        assert state.total_downloaded == 0
        assert len(state.items) == 0
