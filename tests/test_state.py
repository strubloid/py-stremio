"""Tests for state module."""
from datetime import datetime, timedelta, timezone
import pytest
from pathlib import Path
import tempfile
import json
import shutil

from py_stremio.components.state.app_state import (
    DownloadState,
    DownloadRecord,
    IN_PROGRESS_MAX_AGE_SECONDS,
    PREFLIGHT_INDETERMINATE_TTL_SECONDS,
    load_state,
    save_state,
)


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


class TestPreflightIndeterminate:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    @pytest.fixture
    def state(self, temp_folder):
        return DownloadState(folder_path=temp_folder)

    def test_mark_and_check_indeterminate(self, state):
        state.mark_preflight_indeterminate("episode_1", "rate-limited")
        assert state.is_preflight_indeterminate("episode_1") is True
        assert state.is_preflight_indeterminate("episode_2") is False

    def test_indeterminate_does_not_count_as_failed(self, state):
        state.mark_preflight_indeterminate("episode_1", "rate-limited")
        # mark_failed() and was_attempted() must not see indeterminate entries
        assert state.was_attempted("episode_1") == 0

    def test_indeterminate_expires_after_ttl(self, state):
        state.mark_preflight_indeterminate("episode_1", "rate-limited")
        # Manually backdate the timestamp to simulate expiry.
        past = (
            datetime.now(timezone.utc) - timedelta(seconds=PREFLIGHT_INDETERMINATE_TTL_SECONDS + 60)
        ).isoformat()
        state.preflight_indeterminate["episode_1"]["timestamp"] = past
        assert state.is_preflight_indeterminate("episode_1") is False
        # Expired entries are dropped on read.
        assert "episode_1" not in state.preflight_indeterminate

    def test_clear_preflight_indeterminate_specific_key(self, state):
        state.mark_preflight_indeterminate("episode_1", "rate-limited")
        state.mark_preflight_indeterminate("episode_2", "rate-limited")
        state.clear_preflight_indeterminate("episode_1")
        assert state.is_preflight_indeterminate("episode_1") is False
        assert state.is_preflight_indeterminate("episode_2") is True

    def test_clear_preflight_indeterminate_all(self, state):
        state.mark_preflight_indeterminate("episode_1", "rate-limited")
        state.mark_preflight_indeterminate("episode_2", "rate-limited")
        state.clear_preflight_indeterminate()
        assert state.preflight_indeterminate == {}

    def test_save_load_round_trip(self, temp_folder):
        state = DownloadState(folder_path=temp_folder)
        state.mark_preflight_indeterminate("episode_3", "rate-limited")
        save_state(temp_folder, state)

        with open(temp_folder / ".download-state.json") as f:
            data = json.load(f)
        assert "preflight_indeterminate" in data
        assert "episode_3" in data["preflight_indeterminate"]

        loaded = load_state(temp_folder)
        assert loaded.is_preflight_indeterminate("episode_3") is True

    def test_load_state_without_preflight_indeterminate_is_backward_compatible(self, temp_folder):
        """Old state files written before this field existed must still load."""
        old_data = {
            "items": {},
            "last_scan": "",
            "total_downloaded": 0,
            "failed_items": {},
        }
        with open(temp_folder / ".download-state.json", "w") as f:
            json.dump(old_data, f)

        loaded = load_state(temp_folder)
        assert loaded.preflight_indeterminate == {}


class TestClearFailedOnSuccess:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    @pytest.fixture
    def state(self, temp_folder):
        return DownloadState(folder_path=temp_folder)

    def test_add_download_clears_matching_failed_item(self, state):
        """A successful download must remove any stale failure record for
        the same episode so the state file no longer claims 'failed' for
        an item that is now on disk."""
        state.mark_failed("Rick and Morty_s09e10.mkv", "no streams", 1)
        state.add_download("Rick and Morty_s09e10.mkv", "1080p", "stremio")
        assert state.was_attempted("Rick and Morty_s09e10.mkv") == 0

    def test_add_download_clears_legacy_episode_key(self, state):
        state.mark_failed("episode_10.mkv", "no streams", 1)
        state.add_download("Rick and Morty_s09e10.mkv", "1080p", "stremio")
        # The legacy episode_N.mkv form is also cleared.
        assert state.was_attempted("episode_10.mkv") == 0

    def test_add_download_does_not_clear_unrelated_failure(self, state):
        state.mark_failed("episode_5.mkv", "no streams", 1)
        state.add_download("Rick and Morty_s09e10.mkv", "1080p", "stremio")
        # A different episode's failure record is left alone.
        assert state.was_attempted("episode_5.mkv") == 1

    def test_add_download_without_episode_number_keeps_failure(self, state):
        state.mark_failed("movie_orphan.mkv", "no streams", 1)
        state.add_download("Random.File.mkv", "1080p", "stremio")
        # No S##E## token in either filename — nothing is cleared.
        assert state.was_attempted("movie_orphan.mkv") == 1


class TestInProgress:
    @pytest.fixture
    def temp_folder(self):
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir)

    @pytest.fixture
    def state(self, temp_folder):
        return DownloadState(folder_path=temp_folder)

    def test_mark_and_check_in_progress(self, state):
        state.mark_in_progress("episode_5.mkv", part_bytes=1024)
        assert state.is_in_progress("episode_5.mkv")
        assert state.in_progress["episode_5.mkv"]["part_bytes"] == 1024
        assert state.in_progress["episode_5.mkv"]["started_at"]

    def test_clear_in_progress(self, state):
        state.mark_in_progress("episode_5.mkv", part_bytes=2048)
        state.clear_in_progress("episode_5.mkv")
        assert not state.is_in_progress("episode_5.mkv")

    def test_add_download_clears_in_progress(self, state):
        """A successful download must drop the in-progress marker so the
        next run does not think the episode is still being downloaded."""
        state.mark_in_progress("episode_10.mkv", part_bytes=999)
        state.add_download("Rick and Morty_s09e10.mkv", "1080p", "stremio")
        assert not state.is_in_progress("episode_10.mkv")
        # The sanitised form is also cleared.
        assert not state.is_in_progress("Rick and Morty_s09e10.mkv")

    def test_mark_failed_clears_in_progress(self, state):
        """A permanent failure also clears the in-progress marker — the
        .part file has been deleted by the downloader."""
        state.mark_in_progress("episode_5.mkv", part_bytes=999)
        state.mark_failed("episode_5.mkv", "all streams failed", 1)
        assert not state.is_in_progress("episode_5.mkv")

    def test_prune_drops_marker_when_part_file_missing(self, temp_folder, state):
        """A marker without a matching .part file on disk is stale and
        should be removed by ``prune_stale_in_progress``."""
        state.mark_in_progress("episode_3.mkv", part_bytes=999)
        state.prune_stale_in_progress(folder_path=temp_folder)
        assert "episode_3.mkv" not in state.in_progress

    def test_prune_keeps_marker_when_part_file_exists(self, temp_folder, state):
        (temp_folder / "episode_7.mkv.part").write_bytes(b"x" * 4096)
        state.mark_in_progress("episode_7.mkv", part_bytes=4096)
        state.prune_stale_in_progress(folder_path=temp_folder)
        assert state.is_in_progress("episode_7.mkv")

    def test_prune_drops_marker_older_than_max_age(self, temp_folder, state):
        state.mark_in_progress("episode_8.mkv", part_bytes=999)
        # Backdate the timestamp to past the TTL.
        past = (
            datetime.now(timezone.utc) - timedelta(seconds=IN_PROGRESS_MAX_AGE_SECONDS + 60)
        ).isoformat()
        state.in_progress["episode_8.mkv"]["started_at"] = past
        (temp_folder / "episode_8.mkv.part").write_bytes(b"x")
        state.prune_stale_in_progress(folder_path=temp_folder)
        # Even with the .part file present, an old marker is dropped.
        assert "episode_8.mkv" not in state.in_progress

    def test_prune_respects_keep_keys(self, temp_folder, state):
        state.mark_in_progress("episode_1.mkv", part_bytes=999)
        state.prune_stale_in_progress(
            keep_keys={"episode_1.mkv"}, folder_path=temp_folder
        )
        # keep_keys wins over the filesystem check.
        assert state.is_in_progress("episode_1.mkv")

    def test_save_and_load_in_progress(self, temp_folder):
        state = DownloadState(folder_path=temp_folder)
        state.mark_in_progress("episode_4.mkv", part_bytes=2048)
        save_state(temp_folder, state)

        loaded = load_state(temp_folder)
        assert loaded.is_in_progress("episode_4.mkv")
        assert loaded.in_progress["episode_4.mkv"]["part_bytes"] == 2048

    def test_load_state_without_in_progress_is_backward_compatible(self, temp_folder):
        """Old state files written before this field existed must still load."""
        old_data = {
            "items": {},
            "last_scan": "",
            "total_downloaded": 0,
            "failed_items": {},
        }
        with open(temp_folder / ".download-state.json", "w") as f:
            json.dump(old_data, f)
        loaded = load_state(temp_folder)
        assert loaded.in_progress == {}
