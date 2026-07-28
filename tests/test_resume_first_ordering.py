"""Regression tests for the resume-first queue ordering.

When a user restarts ``py-stremio`` after an interruption (Ctrl+C,
crash, OOM), episodes that already have a ``.part`` file on disk
should be picked up BEFORE the rest of the missing episodes. Without
this ordering the per-episode addon search runs first, the worker
gets stuck on a fresh look-up, and the resume candidates have to
wait for the workers to free up.

These tests exercise the queue-building and state-marker helpers in
``processing.py`` directly so they do not need a full mock of the
download pipeline.
"""

import json

import pytest

from py_stremio.components.configs.config_file import (
    DownloadConfig,
    QualitySettings,
    save_config,
)
from py_stremio.components.download.processing import (
    _partition_missing_by_in_progress,
    _part_path_for_episode,
    _sync_in_progress_with_disk,
    setup_season_folder,
)
from py_stremio.components.state.app_state import (
    DownloadState,
    load_state,
    save_state,
)


def _write_config_and_state(tmp_path, episode_count: int) -> tuple:
    season_folder = tmp_path / "series" / "Test Show" / "s01"
    season_folder.mkdir(parents=True)
    config = DownloadConfig(
        type="series",
        title="Test Show",
        imdb_id="tt1234567",
        season=1,
        episode_count=episode_count,
        quality=QualitySettings(preferred="1080p"),
        servers=["https://torrentio.strem.fun/manifest.json"],
    )
    save_config(season_folder / "download-config.json", config)
    state = DownloadState(folder_path=season_folder)
    save_state(season_folder, state)
    return season_folder, config, state


def test_partition_missing_moves_resume_episodes_to_front():
    in_progress = [3, 7]
    missing = [1, 2, 3, 4, 5, 6, 7, 8]
    resume_first, fresh = _partition_missing_by_in_progress(missing, in_progress)
    assert resume_first == [3, 7]
    assert fresh == [1, 2, 4, 5, 6, 8]


def test_partition_missing_keeps_order_when_no_resume_candidates():
    missing = [1, 2, 3, 4]
    resume_first, fresh = _partition_missing_by_in_progress(missing, [])
    assert resume_first == []
    assert fresh == [1, 2, 3, 4]


def test_partition_missing_with_all_resume_candidates():
    missing = [2, 4, 6]
    in_progress = [2, 4, 6]
    resume_first, fresh = _partition_missing_by_in_progress(missing, in_progress)
    assert resume_first == [2, 4, 6]
    assert fresh == []


def test_part_path_for_episode_returns_existing_part(tmp_path):
    season_folder = tmp_path / "series" / "X" / "s01"
    season_folder.mkdir(parents=True)
    config = DownloadConfig(
        type="series", title="X", imdb_id="tt1", season=1,
        episode_count=2, quality=QualitySettings(),
    )
    (season_folder / "X_s01e02.mkv.part").write_bytes(b"x" * 4096)

    part_path = _part_path_for_episode(season_folder, config, 1, 2)
    assert part_path is not None
    assert part_path.name == "X_s01e02.mkv.part"
    assert part_path.stat().st_size == 4096


def test_part_path_for_episode_returns_none_when_no_part(tmp_path):
    season_folder = tmp_path / "series" / "X" / "s01"
    season_folder.mkdir(parents=True)
    config = DownloadConfig(
        type="series", title="X", imdb_id="tt1", season=1,
        episode_count=2, quality=QualitySettings(),
    )
    assert _part_path_for_episode(season_folder, config, 1, 2) is None


def test_sync_in_progress_with_disk_marks_episodes_with_part_files(tmp_path):
    season_folder, config, state = _write_config_and_state(tmp_path, episode_count=5)
    (season_folder / "Test Show_s01e02.mkv.part").write_bytes(b"x" * 1000)
    (season_folder / "Test Show_s01e04.mkv.part").write_bytes(b"x" * 2000)

    in_progress = _sync_in_progress_with_disk(
        season_folder, config, 1, state, config.episode_count
    )
    assert in_progress == [2, 4]
    assert state.is_in_progress("episode_2")
    assert state.is_in_progress("episode_4")
    assert state.in_progress["episode_2"]["part_bytes"] == 1000
    assert state.in_progress["episode_4"]["part_bytes"] == 2000


def test_sync_in_progress_prunes_stale_markers(tmp_path):
    season_folder, config, state = _write_config_and_state(tmp_path, episode_count=5)
    # Mark an episode as in-progress in state but the .part file is
    # missing — this simulates a crashed run that wrote the marker
    # but never wrote the .part file.
    state.mark_in_progress("episode_3", part_bytes=999)
    # Drop a .part for episode 5 — this should be the only survivor.
    (season_folder / "Test Show_s01e05.mkv.part").write_bytes(b"x")

    in_progress = _sync_in_progress_with_disk(
        season_folder, config, 1, state, config.episode_count
    )
    assert in_progress == [5]
    # Stale marker is pruned.
    assert not state.is_in_progress("episode_3")


def test_sync_in_progress_returns_empty_when_no_part_files(tmp_path):
    season_folder, config, state = _write_config_and_state(tmp_path, episode_count=5)
    in_progress = _sync_in_progress_with_disk(
        season_folder, config, 1, state, config.episode_count
    )
    assert in_progress == []
    assert state.in_progress == {}


def test_setup_season_folder_orders_resume_episodes_first(tmp_path, monkeypatch):
    """End-to-end: the missing list returned by ``setup_season_folder``
    must start with the episodes that have ``.part`` files on disk."""
    season_folder, config, _ = _write_config_and_state(tmp_path, episode_count=6)
    # Resume candidate: episodes 3 and 5 have partial files.
    (season_folder / "Test Show_s01e03.mkv.part").write_bytes(b"x" * 1000)
    (season_folder / "Test Show_s01e05.mkv.part").write_bytes(b"x" * 2000)
    # Bypass the preflight: provide a cached server so the test does
    # not need to monkey-patch the network layer.
    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    task = setup_season_folder(season_folder, quiet_output=True)
    assert task is not None
    # The first two episodes in the queue are the resume candidates.
    assert task.missing_episodes[:2] == [3, 5]
    # The rest of the missing episodes follow in their natural order.
    assert task.missing_episodes[2:] == [1, 2, 4, 6]
    # The task also exposes the in-progress set for the run.
    assert sorted(task.in_progress_episodes) == [3, 5]


def test_setup_season_folder_no_resume_when_no_part_files(tmp_path):
    season_folder, config, _ = _write_config_and_state(tmp_path, episode_count=3)
    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    task = setup_season_folder(season_folder, quiet_output=True)
    assert task is not None
    assert task.missing_episodes == [1, 2, 3]
    assert task.in_progress_episodes == []


def test_setup_season_folder_persists_in_progress_markers(tmp_path):
    """The in_progress markers must be persisted to .download-state.json
    so the NEXT process can read them and resume first."""
    season_folder, config, _ = _write_config_and_state(tmp_path, episode_count=4)
    (season_folder / "Test Show_s01e02.mkv.part").write_bytes(b"x" * 512)
    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    setup_season_folder(season_folder, quiet_output=True)

    with open(season_folder / ".download-state.json") as f:
        data = json.load(f)
    assert "in_progress" in data
    assert "episode_2" in data["in_progress"]
    assert data["in_progress"]["episode_2"]["part_bytes"] == 512


def test_setup_season_folder_prunes_stale_marker_from_previous_run(tmp_path):
    """A state file that contains a stale in_progress marker (because
    the previous process died before the .part file was created) must
    be cleaned up by the next run."""
    season_folder, config, state = _write_config_and_state(tmp_path, episode_count=3)
    # Simulate a stale marker from a previous run.
    state.mark_in_progress("episode_1", part_bytes=999)
    save_state(season_folder, state)

    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    setup_season_folder(season_folder, quiet_output=True)

    # The stale marker is gone; the on-disk scan did not find any
    # matching .part file so the in_progress set is empty.
    reloaded = load_state(season_folder)
    assert reloaded.in_progress == {}


def test_legacy_colon_part_file_is_recognized_as_resume(tmp_path):
    """The pre-fix pipeline wrote ``.part`` files with the unsanitised
    (colon-bearing) filename. The new sync helper must still recognise
    them so the resume-first ordering works for libraries that were
    built before the sanitization fix.
    """
    season_folder = tmp_path / "series" / "Bleach Thousand-Year Blood War" / "s04"
    season_folder.mkdir(parents=True)
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        imdb_id="tt14986406",
        season=4,
        episode_count=4,
        quality=QualitySettings(preferred="1080p"),
        servers=["https://torrentio.strem.fun/manifest.json"],
    )
    save_config(season_folder / "download-config.json", config)
    state = DownloadState(folder_path=season_folder)
    save_state(season_folder, state)
    # Legacy .part file with the unsanitised colon name.
    (season_folder / "Bleach: Thousand-Year Blood War_s04e02.mkv.part").write_bytes(b"x" * 1024)

    in_progress = _sync_in_progress_with_disk(
        season_folder, config, 4, state, config.episode_count
    )
    assert in_progress == [2]
    assert state.is_in_progress("episode_2")


# ── In-progress marking around the actual download call ─────────────


def test_download_marks_in_progress_before_search_and_clears_on_success(
    tmp_path, monkeypatch
):
    """The download path must mark the episode in_progress before
    opening the network stream, then clear it once the download
    succeeds."""
    from py_stremio.components.download import processing
    from py_stremio.utils.cancellation import clear_shutdown

    clear_shutdown()

    season_folder, config, _ = _write_config_and_state(tmp_path, episode_count=2)
    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    download_markers: list[bool] = []

    def fake_search_and_download(**kwargs):
        # Capture the in_progress state at the moment the download
        # attempt begins.
        state = load_state(season_folder)
        download_markers.append(state.is_in_progress(f"episode_{kwargs['episode']}"))
        return {
            "success": True,
            "filename": f"Test Show_s01k{kwargs['episode']:02d}.mkv".replace("k", "e"),
            "quality": "1080p",
            "working_urls": ["https://torrentio.strem.fun/manifest.json"],
            "successful_url": "https://torrentio.strem.fun/manifest.json",
        }

    monkeypatch.setattr(processing, "search_and_download", fake_search_and_download)
    monkeypatch.setattr(processing, "settings", _fake_settings())

    processing.process_season_folder(season_folder, max_workers=1)

    # The in_progress marker was set at the moment search_and_download
    # was called for every episode.
    assert download_markers == [True, True]
    # After a successful download the marker is cleared.
    reloaded = load_state(season_folder)
    assert reloaded.in_progress == {}


def test_download_clears_in_progress_on_permanent_failure(tmp_path, monkeypatch):
    """A permanent failure must also drop the in_progress marker so
    the next run does not see a stale marker pointing to a deleted
    .part file."""
    from py_stremio.components.download import processing

    season_folder, config, _ = _write_config_and_state(tmp_path, episode_count=1)
    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    def fake_search_and_download(**kwargs):
        return {
            "success": False,
            "error": "All streams failed",
            "working_urls": [],
            "permanent_failure": True,
        }

    monkeypatch.setattr(processing, "search_and_download", fake_search_and_download)
    monkeypatch.setattr(processing, "settings", _fake_settings())

    processing.process_season_folder(season_folder, max_workers=1)

    reloaded = load_state(season_folder)
    # The in_progress marker was set during the attempt and then
    # cleared by ``mark_failed``.
    assert reloaded.in_progress == {}


def _fake_settings():
    from dataclasses import dataclass, field

    @dataclass
    class _S:
        MAX_DOWNLOAD_ATTEMPTS: int = 5
        LIMIT_EPISODES: int = 0
        MIN_COMPLETED_VIDEO_SIZE_MB: int = 100
        DOWNLOAD_STALL_TIMEOUT: float = 60.0
        PREFERRED_LANGUAGES: list = field(default_factory=list)
        DRY_RUN: bool = False

    return _S()


def test_process_season_folder_rereads_workers_ref_each_round(tmp_path, monkeypatch):
    """The bottom-bar ``[+/-]`` controls mutate ``workers_ref[0]`` while
    downloads are running.  ``process_season_folder`` must re-read the
    ref before building each round's ``ThreadPoolExecutor`` so the new
    limit takes effect on the next round.  Pre-fix the pool was sized
    once from the ``max_workers`` argument and the user's dial-down was
    silently ignored.
    """
    from py_stremio.components.download import processing
    from py_stremio.utils.cancellation import clear_shutdown

    # Other test files (notably test_menu.test_run_pipeline_ctrl_c_exits_cleanly)
    # set the global shutdown event.  Clear it so the round loop does
    # not bail out before the deferred retry round runs.
    clear_shutdown()

    season_folder, config, _ = _write_config_and_state(tmp_path, episode_count=3)
    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    pool_sizes: list[int] = []
    workers_ref = [3]
    round_observed = {"current": 0}

    def fake_search_and_download(**kwargs):
        if round_observed["current"] == 0:
            # Round 1: dial the limit down to 2 between rounds so the
            # next pool is sized from the new value, not the initial 3.
            workers_ref[0] = 2
        round_observed["current"] += 1
        return {
            "success": False,
            "error": "transient",
            "working_urls": [],
            "permanent_failure": False,
        }

    real_executor = processing.ThreadPoolExecutor

    class _RecordingExecutor(real_executor):
        def __init__(self, max_workers=None, **kwargs):
            pool_sizes.append(max_workers)
            super().__init__(max_workers=max_workers, **kwargs)

    monkeypatch.setattr(processing, "search_and_download", fake_search_and_download)
    monkeypatch.setattr(processing, "settings", _fake_settings())
    monkeypatch.setattr(processing, "ThreadPoolExecutor", _RecordingExecutor)

    processing.process_season_folder(
        season_folder, max_workers=3, workers_ref=workers_ref
    )

    # Round 1 was sized from the initial workers_ref (3); round 2
    # re-read the ref after the dial-down (2).
    assert pool_sizes[0] == 3, f"expected round 1 pool to be sized from initial ref, got {pool_sizes[0]}"
    assert any(size == 2 for size in pool_sizes[1:]), (
        f"expected a later round pool to be sized from the dialed-down ref=2, got {pool_sizes!r}"
    )


def test_process_season_folder_dials_down_to_single_worker_path(tmp_path, monkeypatch):
    """If the user dials the worker count to 0/1 mid-run, the parallel
    branch must stop creating new pools and fall back to the
    single-worker loop so episodes still drain."""
    from py_stremio.components.download import processing
    from py_stremio.utils.cancellation import clear_shutdown

    clear_shutdown()

    season_folder, config, _ = _write_config_and_state(tmp_path, episode_count=2)
    config.servers = ["https://torrentio.strem.fun/manifest.json"]
    save_config(season_folder / "download-config.json", config)

    workers_ref = [2]
    parallel_pools = {"n": 0}
    attempts: list[int] = []

    def fake_search_and_download(**kwargs):
        attempts.append(kwargs["episode"])
        # After the first transient failure, dial the limit down to
        # 1.  The next round must break out of the parallel branch.
        workers_ref[0] = 1
        return {
            "success": False,
            "error": "transient",
            "working_urls": [],
            "permanent_failure": False,
        }

    real_executor = processing.ThreadPoolExecutor

    class _CountingExecutor(real_executor):
        def __init__(self, max_workers=None, **kwargs):
            parallel_pools["n"] += 1
            super().__init__(max_workers=max_workers, **kwargs)

    monkeypatch.setattr(processing, "search_and_download", fake_search_and_download)
    monkeypatch.setattr(processing, "settings", _fake_settings())
    monkeypatch.setattr(processing, "ThreadPoolExecutor", _CountingExecutor)

    processing.process_season_folder(
        season_folder, max_workers=2, workers_ref=workers_ref
    )

    # Exactly one parallel pool was created for round 1; round 2 saw
    # the dialed-down ref=1 and broke out of the parallel branch.
    assert parallel_pools["n"] == 1, (
        f"expected exactly 1 parallel pool before the dial-down, got {parallel_pools['n']}"
    )
    # Round 1 (parallel) attempts both episodes, then the single-worker
    # drain runs MAX_DOWNLOAD_ATTEMPTS=5 more rounds of both episodes
    # for a total of 1*2 + 5*2 = 12 attempts.
    assert len(attempts) == 1 * 2 + 5 * 2, (
        f"expected 1 parallel round + 5 single-worker rounds (12 attempts), got {len(attempts)}"
    )

