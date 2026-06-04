"""Tests for config-driven download processing."""
import json
from types import SimpleNamespace

from py_stremio.components.config_file import DownloadConfig, QualitySettings, save_config
from py_stremio.components.download_processing import process_season_folder
from py_stremio.components.output import install_thread_stdout_filter, restore_thread_stdout_filter


def _download_settings():
    return SimpleNamespace(LIMIT_EPISODES=0, MIN_COMPLETED_VIDEO_SIZE_MB=0)


def test_process_season_folder_downloads_all_missing_episodes_by_default(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=3,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    result = process_season_folder(tmp_path)

    assert calls == [1, 2, 3]
    assert result["downloaded"] == 3


def test_process_season_folder_uses_current_episode_download_as_start_episode(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=4,
        current_episode_download=3,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(tmp_path)

    assert calls == [3, 4]


def test_process_season_folder_persists_next_episode_after_each_success(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=3,
        current_episode_download=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    saved_during_download = []

    def fake_search_and_download(**kwargs):
        with open(tmp_path / "download-config.json") as f:
            saved_during_download.append(json.load(f).get("current_episode_download"))
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(tmp_path)

    with open(tmp_path / "download-config.json") as f:
        saved = json.load(f)
    assert saved_during_download == [1, 2, 3]
    assert saved["current_episode_download"] == 4


def test_process_season_folder_repairs_stale_season_config_from_folder_path(tmp_path, monkeypatch):
    season_folder = tmp_path / "series" / "House Of The Dragon" / "s02"
    season_folder.mkdir(parents=True)
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=1,
        current_episode_download=1,
        search_group="S01",
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(season_folder / "download-config.json", config)
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append((kwargs["season"], kwargs["episode"]))
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(season_folder)

    with open(season_folder / "download-config.json") as f:
        saved = json.load(f)
    assert calls == [(2, 1)]
    assert saved["season"] == 2
    assert saved["search_group"] == "S02"


def test_process_season_folder_quiet_output_suppresses_worker_prints(tmp_path, monkeypatch, capsys):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=2,
        episode_count=2,
        current_episode_download=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)

    def fake_search_and_download(**kwargs):
        print(f"NOISY LOOKUP S02E{kwargs['episode']:02d}")
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())
    _, restore_stdout = install_thread_stdout_filter()
    try:
        process_season_folder(tmp_path, max_workers=2, quiet_output=True)
    finally:
        restore_thread_stdout_filter(restore_stdout)

    assert "NOISY LOOKUP" not in capsys.readouterr().out


def test_process_season_folder_uses_shared_worker_semaphore_to_cap_active_downloads(tmp_path, monkeypatch):
    import threading

    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=2,
        episode_count=4,
        current_episode_download=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    active = 0
    max_active = 0
    calls = []
    lock = threading.Lock()

    def fake_search_and_download(**kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            calls.append(kwargs["episode"])
        threading.Event().wait(0.01)
        with lock:
            active -= 1
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(tmp_path, max_workers=4, worker_semaphore=threading.Semaphore(2))

    assert sorted(calls) == [1, 2, 3, 4]
    assert max_active == 2


def test_process_season_folder_accepts_download_threads(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House Of The Dragon",
        season=1,
        episode_count=4,
        current_episode_download=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    result = process_season_folder(tmp_path, max_workers=2)

    assert sorted(calls) == [1, 2, 3, 4]
    assert result["downloaded"] == 4


def test_process_season_folder_does_not_redownload_existing_generated_episode_file(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House of the Dragon",
        season=1,
        episode_count=2,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    (tmp_path / "House of the Dragon_s01e01.mkv").write_bytes(b"already downloaded")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": f"episode_{kwargs['episode']}.mkv",
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    result = process_season_folder(tmp_path)

    assert calls == [2]
    assert result["downloaded"] == 1
    assert result["skipped"] == 1


def test_process_season_folder_resumes_partial_part_file(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House of The Dragon",
        season=1,
        episode_count=2,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    partial = tmp_path / "House of The Dragon_s01e02.mkv.part"
    partial.write_bytes(b"partial")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {
            "success": True,
            "filename": str(tmp_path / "House of The Dragon_s01e02.mkv"),
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    process_season_folder(tmp_path)

    assert calls == [1, 2]


def test_process_season_folder_treats_tiny_untracked_generated_file_as_interrupted_download(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="House of the Dragon",
        season=1,
        episode_count=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    interrupted = tmp_path / "House of the Dragon_s01e01.mkv"
    interrupted.write_bytes(b"partial")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        assert (tmp_path / "House of the Dragon_s01e01.mkv.part").exists()
        return {
            "success": True,
            "filename": str(tmp_path / "House of the Dragon_s01e01.mkv"),
            "quality": "1080p",
            "working_urls": [],
        }

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr(
        "py_stremio.components.download_processing.settings",
        SimpleNamespace(LIMIT_EPISODES=0, MIN_COMPLETED_VIDEO_SIZE_MB=100),
    )

    process_season_folder(tmp_path)

    assert calls == [1]


def test_process_season_folder_treats_absolute_numbered_complete_season_as_existing(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        season=3,
        episode_count=14,
        current_episode_download=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    bleach_files = [
        "[Lazier] Bleach Thousand-Year Blood War - 27 (WEB 1080p EAC3) [8749C4A9].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 28 (WEB 1080p EAC3) [AC0C8A2A].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 29 (WEB 1080p EAC3) [7EF57884].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 30 (WEB 1080p EAC3) [2171F7D5].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 31 (WEB 1080p EAC3) [6F85B95C].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 32 (WEB 1080p EAC3) [E0BF7156].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 33 (WEB 1080p EAC3) [5016AD08].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 34 (WEB 1080p AAC) [EBDB3283].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 35 (WEB 1080p AAC) [C72E26CE].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 36 (WEB 1080p AAC) [E73FCD9F].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 37 (WEB 1080p AAC) [72E510BF].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 38 (WEB 1080p AAC) [CD3833B0].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 39 (WEB 1080p AAC) [A7BABE27].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 40 (WEB 1080p AAC) [E323D12D].mkv",
    ]
    for filename in bleach_files:
        (tmp_path / filename).write_bytes(b"already downloaded")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {"success": True, "filename": f"episode_{kwargs['episode']}.mkv", "quality": "1080p", "working_urls": []}

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    result = process_season_folder(tmp_path)

    with open(tmp_path / "download-config.json") as f:
        saved = json.load(f)
    assert calls == []
    assert result == {"downloaded": 0, "skipped": 14, "failed": 0}
    assert saved["current_episode_download"] == 15


def test_process_season_folder_downloads_only_new_episode_after_absolute_numbered_season_grows(tmp_path, monkeypatch):
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        season=3,
        episode_count=15,
        current_episode_download=1,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    bleach_files = [
        "[Lazier] Bleach Thousand-Year Blood War - 27 (WEB 1080p EAC3) [8749C4A9].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 28 (WEB 1080p EAC3) [AC0C8A2A].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 29 (WEB 1080p EAC3) [7EF57884].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 30 (WEB 1080p EAC3) [2171F7D5].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 31 (WEB 1080p EAC3) [6F85B95C].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 32 (WEB 1080p EAC3) [E0BF7156].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 33 (WEB 1080p EAC3) [5016AD08].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 34 (WEB 1080p AAC) [EBDB3283].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 35 (WEB 1080p AAC) [C72E26CE].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 36 (WEB 1080p AAC) [E73FCD9F].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 37 (WEB 1080p AAC) [72E510BF].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 38 (WEB 1080p AAC) [CD3833B0].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 39 (WEB 1080p AAC) [A7BABE27].mkv",
        "[Lazier] Bleach Thousand-Year Blood War - 40 (WEB 1080p AAC) [E323D12D].mkv",
    ]
    for filename in bleach_files:
        (tmp_path / filename).write_bytes(b"already downloaded")
    calls = []

    def fake_search_and_download(**kwargs):
        calls.append(kwargs["episode"])
        return {"success": True, "filename": f"episode_{kwargs['episode']}.mkv", "quality": "1080p", "working_urls": []}

    monkeypatch.setattr(
        "py_stremio.components.download_processing.search_and_download",
        fake_search_and_download,
    )
    monkeypatch.setattr("py_stremio.components.download_processing.settings", _download_settings())

    result = process_season_folder(tmp_path)

    assert calls == [15]
    assert result["downloaded"] == 1
    assert result["skipped"] == 14
