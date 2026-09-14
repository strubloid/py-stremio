"""Regression tests for crash-safe JSON persistence."""
import json

import pytest

from py_stremio.components.configs.config_file import DownloadConfig, save_config
from py_stremio.components.errors import error_count, reset_error_reporter
from py_stremio.components.state.app_state import DownloadState, save_state
from py_stremio.utils.atomic_write import atomic_write_text


def test_save_config_preserves_previous_json_when_dump_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "download-config.json"
    save_config(config_path, DownloadConfig(type="series", title="Original", season=1))

    original_data = json.loads(config_path.read_text())
    real_dump = json.dump

    def failing_dump(data, fp, *args, **kwargs):
        fp.write('{"partial":')
        raise OSError("simulated unmount during config save")

    monkeypatch.setattr(json, "dump", failing_dump)

    # Must not raise — disk-full / mount-flake I/O errors must NEVER
    # crash the download pipeline.
    save_config(config_path, DownloadConfig(type="series", title="Updated", season=1))

    monkeypatch.setattr(json, "dump", real_dump)
    assert json.loads(config_path.read_text()) == original_data


def test_save_state_preserves_previous_json_when_dump_fails(tmp_path, monkeypatch):
    state = DownloadState(folder_path=tmp_path)
    state.add_download("original.mkv", "1080p", "stremio", server="https://addon.example")
    save_state(tmp_path, state)

    state_path = tmp_path / ".download-state.json"
    original_data = json.loads(state_path.read_text())
    real_dump = json.dump

    def failing_dump(data, fp, *args, **kwargs):
        fp.write('{"items":')
        raise OSError("simulated unmount during state save")

    monkeypatch.setattr(json, "dump", failing_dump)

    state.add_download("new.mkv", "720p", "stremio", server="https://new.example")
    # Must not raise — the on-disk .part file is the source of truth,
    # so a state-file write failure must never abort the pipeline.
    save_state(tmp_path, state)

    monkeypatch.setattr(json, "dump", real_dump)
    assert json.loads(state_path.read_text()) == original_data


def test_save_state_reports_io_error_without_raising(tmp_path, monkeypatch):
    """A failing state save must be surfaced via the error reporter."""
    reset_error_reporter()
    try:
        state = DownloadState(folder_path=tmp_path)
        save_state(tmp_path, state)

        def failing_dump(data, fp, *args, **kwargs):
            raise OSError("simulated unmount during state save")

        monkeypatch.setattr(json, "dump", failing_dump)

        state.add_download("new.mkv", "1080p", "stremio", server="https://addon.example")
        save_state(tmp_path, state)  # must not raise

        assert error_count() >= 1
    finally:
        reset_error_reporter()


def test_save_config_reports_io_error_without_raising(tmp_path, monkeypatch):
    """A failing config save must be surfaced via the error reporter."""
    reset_error_reporter()
    try:
        config_path = tmp_path / "download-config.json"
        save_config(config_path, DownloadConfig(type="series", title="x", season=1))

        def failing_dump(data, fp, *args, **kwargs):
            raise OSError("simulated unmount during config save")

        monkeypatch.setattr(json, "dump", failing_dump)

        save_config(
            config_path,
            DownloadConfig(type="series", title="y", season=1),
        )  # must not raise

        assert error_count() >= 1
    finally:
        reset_error_reporter()


def test_save_config_leaves_no_temp_files_after_success(tmp_path):
    config_path = tmp_path / "download-config.json"

    save_config(config_path, DownloadConfig(type="series", title="Clean", season=1))

    assert json.loads(config_path.read_text())["title"] == "Clean"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_text_preserves_previous_file_when_write_fails(tmp_path, monkeypatch):
    path = tmp_path / "addons.txt"
    atomic_write_text(path, "original\n")

    def failing_fsync(fd):
        raise OSError("simulated unmount after text write")

    monkeypatch.setattr("py_stremio.utils.atomic_write.os.fsync", failing_fsync)

    with pytest.raises(OSError, match="simulated unmount"):
        atomic_write_text(path, "updated\n")

    assert path.read_text() == "original\n"
