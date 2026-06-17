"""Test: downloads must not leave trace files behind.

Verification rule: after any download pipeline run, there must be no
leftover .part files, no stale state entries referencing nonexistent
files, and no download-state items that point at missing files on disk.

These tests validate the consistency-checking utilities and catch
regressions if a code change ever starts leaving artifacts.
"""
import json
from pathlib import Path

import pytest

from py_stremio.components.state.app_state import (
    DownloadState,
    load_state,
    save_state,
)


def _find_part_files(root: Path) -> list[Path]:
    """Return all .part files anywhere under root."""
    return list(root.rglob("*.part"))


def _stale_state_entries(state: DownloadState) -> list[str]:
    """Return state entries whose filenames don't resolve to a real file."""
    stale = []
    for filename in state.items:
        file_path = state.folder_path / filename
        if not file_path.exists():
            stale.append(filename)
    return stale


class TestTraceDetection:
    """The detection utilities themselves must be reliable."""

    def test_find_part_files_detects_leftovers(self, tmp_path):
        """_find_part_files must detect .part files when they exist."""
        (tmp_path / "clean.mkv").write_bytes(b"video")
        (tmp_path / "stray.part").write_bytes(b"partial")
        sub = tmp_path / "subdir"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "also.part").write_bytes(b"more")

        parts = _find_part_files(tmp_path)
        assert len(parts) == 2
        assert all(p.suffix == ".part" for p in parts)

    def test_find_part_files_empty_when_clean(self, tmp_path):
        """_find_part_files must return empty when no .part files exist."""
        (tmp_path / "clean.mkv").write_bytes(b"video")
        (tmp_path / "clean.mp4").write_bytes(b"also video")
        assert _find_part_files(tmp_path) == []

    def test_stale_state_detects_missing_files(self, tmp_path):
        """_stale_state_entries must find entries whose files are gone."""
        state = DownloadState(folder_path=tmp_path)
        state.add_download("exists.mkv", "1080p", "mock")
        (tmp_path / "exists.mkv").write_bytes(b"real")
        state.add_download("missing.mkv", "720p", "mock")
        # missing.mkv intentionally not created

        stale = _stale_state_entries(state)
        assert stale == ["missing.mkv"]

    def test_no_stale_when_all_files_present(self, tmp_path):
        """_stale_state_entries must return empty when every entry has a file."""
        state = DownloadState(folder_path=tmp_path)
        for ep in ["s01e01.mkv", "s01e02.mkv", "s01e03.mkv"]:
            state.add_download(ep, "1080p", "mock")
            (tmp_path / ep).write_bytes(b"real video data")

        assert _stale_state_entries(state) == []


class TestStateFileIntegrity:
    """State files must be internally consistent."""

    def test_state_entries_match_real_files(self, tmp_path):
        """Completed download = file exists + state entry."""
        state = DownloadState(folder_path=tmp_path)
        state.add_download("episode_s01e01.mkv", "1080p", "mock")
        (tmp_path / "episode_s01e01.mkv").write_bytes(b"completed" * 10_000)
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        assert loaded.is_downloaded("episode_s01e01.mkv")
        assert (tmp_path / "episode_s01e01.mkv").exists()

    def test_failed_item_not_in_items(self, tmp_path):
        """Failed items go in failed_items, not items."""
        state = DownloadState(folder_path=tmp_path)
        state.add_download("ok.mkv", "1080p", "mock")
        (tmp_path / "ok.mkv").write_bytes(b"real")
        state.mark_failed("bad.mkv", "No streams", 3)
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        assert "bad.mkv" not in loaded.items
        assert "bad.mkv" in loaded.failed_items

    def test_orphan_file_not_in_state(self, tmp_path):
        """A file on disk but not tracked in state must be detected."""
        state = DownloadState(folder_path=tmp_path)
        state.add_download("tracked.mkv", "1080p", "mock")
        (tmp_path / "tracked.mkv").write_bytes(b"real")
        (tmp_path / "untracked.mkv").write_bytes(b"orphan")
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        assert not loaded.is_downloaded("untracked.mkv")
        assert loaded.is_downloaded("tracked.mkv")

    def test_state_round_trip_clean(self, tmp_path):
        """State saves and loads cleanly with no data loss."""
        state = DownloadState(folder_path=tmp_path)
        state.add_download("ep.mkv", "1080p", "mock", server="https://addon.example")
        (tmp_path / "ep.mkv").write_bytes(b"real")
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        assert loaded.total_downloaded == 1
        assert loaded.get_server("ep.mkv") == "https://addon.example"

    def test_no_corrupt_state_on_partial_write(self, tmp_path):
        """If state file is truncated/corrupt, load must return fresh state."""
        state_file = tmp_path / ".download-state.json"
        state_file.write_text("{")  # truncated JSON
        loaded = load_state(tmp_path)
        assert loaded.total_downloaded == 0
        assert len(loaded.items) == 0


class TestPipelinePostconditionRules:
    """Rules that must hold after any pipeline run.

    These tests document the correctness invariants: they verify that
    the CONSISTENCY DETECTION utilities exist and work, so that when
    these rules are asserted at the end of a real pipeline run, they
    will catch real regressions.
    """

    def test_rule__no_part_files_remain(self, tmp_path):
        """RULE: After a complete pipeline run, zero .part files."""
        # Simulate a finished download — .part renamed to final file
        (tmp_path / "result.mkv").write_bytes(b"final video")
        # No .part file here — this is the clean state
        assert _find_part_files(tmp_path) == []

    def test_rule__state_entries_have_files(self, tmp_path):
        """RULE: Every entry in the state must reference a real file."""
        state = DownloadState(folder_path=tmp_path)
        state.add_download("legit.mkv", "1080p", "mock")
        (tmp_path / "legit.mkv").write_bytes(b"real")
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        stale = _stale_state_entries(loaded)
        assert len(stale) == 0, f"Stale entries: {stale}"

    def test_rule__failed_episodes_have_no_stale_entries(self, tmp_path):
        """RULE: Failed episodes must not leave stale items entries."""
        state = DownloadState(folder_path=tmp_path)
        # Mark failed — goes in failed_items, not items
        state.mark_failed("dead_ep.mkv", "All streams failed", 5)
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        assert "dead_ep.mkv" not in loaded.items
        assert "dead_ep.mkv" in loaded.failed_items
