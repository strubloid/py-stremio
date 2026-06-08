"""Tests for state module."""
import pytest
from pathlib import Path
import tempfile
import json
import shutil

from py_stremio.components.state.app_state import DownloadState, DownloadRecord, load_state, save_state


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
        assert record.addon_url == ""
        assert record.server == ""

    def test_record_with_server(self):
        record = DownloadRecord(
            filename="test.mkv",
            quality="1080p",
            provider="stremio",
            server="https://torrentio.strem.fun",
        )
        assert record.server == "https://torrentio.strem.fun"


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
        state.add_download("test.mkv", "1080p", "mock", server="https://addon.example")
        assert state.is_downloaded("test.mkv")
        assert state.total_downloaded == 1
        assert state.get_server("test.mkv") == "https://addon.example"
        assert state.get_addon_url("test.mkv") == "https://addon.example"

    def test_add_download_without_server(self, state):
        state.add_download("test.mkv", "1080p", "mock")
        assert state.is_downloaded("test.mkv")
        assert state.get_server("test.mkv") == ""
        assert state.get_addon_url("test.mkv") == ""

    def test_is_downloaded_false(self, state):
        assert not state.is_downloaded("nonexistent.mkv")

    def test_mark_failed(self, state):
        state.mark_failed("test.mkv", "Connection error", 1)
        assert state.was_attempted("test.mkv") == 1

    def test_get_addon_url_missing_file(self, state):
        assert state.get_addon_url("nonexistent.mkv") == ""

    def test_get_server_missing_file(self, state):
        assert state.get_server("nonexistent.mkv") == ""

    def test_add_download_sets_timestamp(self, state):
        """Timestamp should be set to current time when adding a download."""
        state.add_download("test.mkv", "1080p", "mock")
        record = state.items["test.mkv"]
        assert record.timestamp is not None
        assert len(record.timestamp) > 0  # non-empty isoformat string


class TestStatePersistence:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    def test_save_and_load_state(self, temp_folder):
        state = DownloadState(folder_path=temp_folder)
        state.add_download("test.mkv", "1080p", "mock", server="https://torrentio.strem.fun")
        state.mark_failed("fail.mkv", "Error", 2)
        save_state(temp_folder, state)

        loaded = load_state(temp_folder)
        assert loaded.is_downloaded("test.mkv")
        assert loaded.get_server("test.mkv") == "https://torrentio.strem.fun"
        assert loaded.was_attempted("fail.mkv") == 2
        assert loaded.total_downloaded == 1

    def test_load_nonexistent_creates_new_state(self, temp_folder):
        state = load_state(temp_folder)
        assert state.total_downloaded == 0
        assert len(state.items) == 0

    def test_save_and_load_state_without_server(self, temp_folder):
        """State without server should load fine (backward compat with addon_url only)."""
        state = DownloadState(folder_path=temp_folder)
        state.add_download("old.mkv", "720p", "mock")
        save_state(temp_folder, state)

        loaded = load_state(temp_folder)
        assert loaded.is_downloaded("old.mkv")
        assert loaded.get_server("old.mkv") == ""

    def test_load_old_state_addon_url_migrated_to_server(self, temp_folder):
        """Old state with addon_url but no server should populate server on load."""
        # Write an old-format state file manually (only addon_url, no server)
        old_data = {
            "items": {
                "test.mkv": {
                    "filename": "test.mkv",
                    "quality": "1080p",
                    "provider": "stremio",
                    "addon_url": "https://torrentio.strem.fun",
                    "timestamp": "2026-01-01T00:00:00",
                    "attempts": 1,
                }
            },
            "last_scan": "",
            "total_downloaded": 1,
            "failed_items": {},
        }
        state_path = temp_folder / ".download-state.json"
        with open(state_path, "w") as f:
            json.dump(old_data, f, indent=2)

        loaded = load_state(temp_folder)
        assert loaded.get_server("test.mkv") == "https://torrentio.strem.fun"
        assert loaded.get_addon_url("test.mkv") == "https://torrentio.strem.fun"

    def test_save_includes_both_addon_url_and_server(self, temp_folder):
        """Saved JSON should contain both addon_url and server fields."""
        state = DownloadState(folder_path=temp_folder)
        state.add_download("test.mkv", "1080p", "mock", server="https://torrentio.strem.fun")
        save_state(temp_folder, state)

        state_path = temp_folder / ".download-state.json"
        with open(state_path) as f:
            data = json.load(f)
        record = data["items"]["test.mkv"]
        assert "addon_url" in record
        assert "server" in record
        assert record["server"] == "https://torrentio.strem.fun"
