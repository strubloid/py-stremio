"""Regression tests for crash-safe JSON persistence."""
import json

import pytest

from py_stremio.components.configs.config_file import DownloadConfig, save_config
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

    with pytest.raises(OSError, match="simulated unmount"):
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
    with pytest.raises(OSError, match="simulated unmount"):
        save_state(tmp_path, state)

    monkeypatch.setattr(json, "dump", real_dump)
    assert json.loads(state_path.read_text()) == original_data


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
