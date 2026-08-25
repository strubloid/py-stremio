"""Regression tests for the cross-run retry-budget skip and the
``No streams found`` / ``Preflight found no working addons``
indeterminate classification in the season-folder pipeline.

Background:
    ``90 Day: The Single Life S02E04`` and several other 90 Day Fiancé
    episodes used to be re-queued on every run even after a full run
    had burned through every retry round. The preflight was rate-limit
    saturated, the per-episode search returned ``"No streams found"``
    with ``permanent_failure=True``, and ``_missing_episodes`` ignored
    the ``state.failed_items`` record — so the cycle repeated.

The two new behaviours covered here:

1. ``_missing_episodes`` consults ``state.was_attempted()`` and skips
   any episode that has already reached ``MAX_DOWNLOAD_ATTEMPTS``
   failures across previous runs.

2. When the preflight was indeterminate (rate-limit cascade), the
   per-episode failure reason ``"No streams found"`` is now classified
   as a transient (TTL'd) marker instead of a permanent failure —
   matching the existing treatment of ``"Preflight found no working
   addons"``.

3. ``PY_STREMIO_RETRY_FAILED=true`` (or ``--retry-failed`` on the CLI)
   forces every failed episode back into the missing list for the
   current run, regardless of the accumulated failure budget.
"""

from types import SimpleNamespace

import pytest
from datetime import datetime, timedelta, timezone

from py_stremio.components.configs.config_file import (
    DownloadConfig,
    QualitySettings,
    save_config,
)
from py_stremio.components.download import processing
from py_stremio.components.download.processing import (
    _auto_reset_stale_failed_items,
    _missing_episodes,
    _TRANSIENT_NO_STREAMS_REASONS,
    process_season_folder,
)
from py_stremio.components.state.app_state import DownloadState, load_state


# ── Settings + helpers ──────────────────────────────────────────────


def _settings(max_attempts: int = 5, *, reset_days: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        LIMIT_EPISODES=0,
        MIN_COMPLETED_VIDEO_SIZE_MB=100,
        MAX_DOWNLOAD_ATTEMPTS=max_attempts,
        FAILED_ITEM_AUTO_RESET_DAYS=reset_days,
        DOWNLOAD_STALL_TIMEOUT=60.0,
        PREFERRED_LANGUAGES=["english"],
        DRY_RUN=False,
    )


def _season_config(tmp_path, *, episode_count: int = 6, season: int = 2) -> DownloadConfig:
    config = DownloadConfig(
        type="series",
        title="90 Day: The Single Life",
        imdb_id="tt13837776",
        season=season,
        episode_count=episode_count,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)
    return config


# ── mark_failed cross-run counter ───────────────────────────────────


class TestMarkFailedCrossRunCounter:
    """``mark_failed`` must increment the per-episode attempt count
    across runs so a subsequent run's ``_missing_episodes`` can see
    the cumulative budget burn."""

    def test_first_call_starts_at_one(self, tmp_path):
        state = DownloadState(folder_path=tmp_path)
        state.mark_failed("episode_4", "No streams found")
        assert state.was_attempted("episode_4") == 1

    def test_repeated_calls_increment(self, tmp_path):
        state = DownloadState(folder_path=tmp_path)
        for _ in range(5):
            state.mark_failed("episode_4", "No streams found")
        assert state.was_attempted("episode_4") == 5

    def test_legacy_explicit_attempt_still_works(self, tmp_path):
        """The legacy ``mark_failed(key, error, attempt=3)`` form must
        still record the caller-supplied value (backward compat with
        the legacy ``downloader.py`` path)."""
        state = DownloadState(folder_path=tmp_path)
        state.mark_failed("episode_4.mkv", "failed", 3)
        assert state.was_attempted("episode_4.mkv") == 3

    def test_explicit_attempt_does_not_undercut_existing_counter(self, tmp_path):
        """If the caller passes an explicit ``attempt`` value SMALLER
        than the existing counter, prefer the existing counter —
        otherwise the cross-run budget would silently shrink and the
        skip never fires."""
        state = DownloadState(folder_path=tmp_path)
        state.mark_failed("episode_4", "first")
        state.mark_failed("episode_4", "second")  # attempt=2
        state.mark_failed("episode_4", "third", 1)  # should NOT drop to 1
        assert state.was_attempted("episode_4") >= 2

    def test_add_download_clears_cross_run_counter(self, tmp_path):
        """A successful download clears the failure record so the
        episode can re-enter the missing list on the next run."""
        state = DownloadState(folder_path=tmp_path)
        for _ in range(5):
            state.mark_failed("episode_4", "No streams found")
        assert state.was_attempted("episode_4") == 5
        state.add_download("90 Day_ The Single Life_s02e04.mkv", "1080p", "stremio")
        assert state.was_attempted("episode_4") == 0


# ── _missing_episodes retry budget ──────────────────────────────────


class TestMissingEpisodesSkipsExhausted:
    """``_missing_episodes`` must drop episodes whose cross-run
    failure counter has already reached ``MAX_DOWNLOAD_ATTEMPTS`` —
    otherwise we re-queue the same broken episode forever."""

    def test_episode_at_budget_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=5))
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        # Three consecutive failed runs for S02E04 → attempt=3.
        # Not yet at the budget — must still appear in missing.
        state.mark_failed("episode_4", "No streams found")
        state.mark_failed("episode_4", "No streams found")
        state.mark_failed("episode_4", "No streams found")
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 in missing
        # Push it over the budget.
        state.mark_failed("episode_4", "No streams found")
        state.mark_failed("episode_4", "No streams found")
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 not in missing, (
            "episode at MAX_DOWNLOAD_ATTEMPTS=5 must not be re-queued. "
            "Without this skip the broken episode burns an entire run on "
            "every cron invocation."
        )
        # Other episodes with no failure history must still be queued.
        assert 1 in missing
        assert 5 in missing

    def test_skip_notice_is_emitted_per_folder(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=2))
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        for _ in range(2):
            state.mark_failed("episode_4", "No streams found")
            state.mark_failed("episode_5", "No streams found")
        _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        captured = capsys.readouterr().out
        assert "S02E04" in captured
        assert "S02E05" in captured
        assert "MAX_DOWNLOAD_ATTEMPTS=2" in captured

    def test_max_attempts_zero_disables_skip(self, tmp_path, monkeypatch):
        """``MAX_DOWNLOAD_ATTEMPTS=0`` means "no retry budget" — every
        episode is re-queued even if it has been retried a hundred
        times. Use this when the user wants to brute-force a stuck
        folder."""
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=0))
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        for _ in range(10):
            state.mark_failed("episode_4", "No streams found")
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 in missing

    def test_successful_download_re_admits_episode(self, tmp_path, monkeypatch):
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=2))
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        for _ in range(2):
            state.mark_failed("episode_4", "No streams found")
        # S02E04 was previously burnt out — not in missing list.
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 not in missing
        # The user manually deletes the stale record → next run admits it.
        state.failed_items.pop("episode_4", None)
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 in missing


# ── Retry-failed escape hatch ──────────────────────────────────────


class TestRetryFailedEscapeHatch:
    """``PY_STREMIO_RETRY_FAILED=true`` (or the CLI ``--retry-failed``
    flag wired up in ``main.py``) must force every failed episode back
    into the missing list for the current run."""

    @pytest.fixture
    def _env(self, monkeypatch):
        monkeypatch.setenv("PY_STREMIO_RETRY_FAILED", "true")
        yield

    def test_env_var_bypasses_budget(self, tmp_path, monkeypatch, _env):
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=2))
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        for _ in range(5):
            state.mark_failed("episode_4", "No streams found")
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 in missing, (
            "PY_STREMIO_RETRY_FAILED=true must override the retry budget "
            "so the user can force a re-attempt after fixing an upstream "
            "issue (e.g. an addon came back online)."
        )

    def test_cli_flag_sets_env_var(self, monkeypatch):
        """``--retry-failed`` on the CLI must translate into the env
        var the processing layer reads. We don't run the full CLI
        here — just the helper from ``main.py`` that performs the
        translation."""
        monkeypatch.setattr("sys.argv", ["py-stremio", "--retry-failed", "4"])
        from py_stremio.main import _apply_retry_failed_flag

        _apply_retry_failed_flag()
        import os

        assert os.environ.get("PY_STREMIO_RETRY_FAILED") == "true"
        assert os.environ.get("PY_STREMIO_CLI_RETRY_FAILED") == "true"


# ── preflight_indeterminate branch covers "No streams found" ───────


class TestPreflightIndeterminateReasons:
    """The preflight-indeterminate branch must treat both the original
    ``Preflight found no working addons`` and the per-episode
    ``No streams found`` as transient (TTL'd). Otherwise a single
    rate-limit cascade permanently poisons the state file."""

    def test_transient_reasons_constant_includes_both(self):
        assert "Preflight found no working addons" in _TRANSIENT_NO_STREAMS_REASONS
        assert "No streams found" in _TRANSIENT_NO_STREAMS_REASONS

    def test_no_streams_found_with_indeterminate_preflight_marks_transient(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: a per-episode search that returns
        ``No streams found`` while ``preflight_indeterminate`` is True
        must mark the episode in ``preflight_indeterminate`` (TTL'd),
        NOT in ``failed_items`` (permanent)."""

        monkeypatch.setattr(processing, "settings", _settings(max_attempts=5))
        # Avoid the 3-second backoff in setup_season_folder.
        monkeypatch.setattr(processing, "_PREFLIGHT_BACKOFF_SECONDS", 0.0)
        LivePreflightResult = processing._coerce_preflight.__globals__["PreflightResult"]
        monkeypatch.setattr(
            processing,
            "preflight_discover_working_addons",
            lambda *args, **kwargs: LivePreflightResult(
                alive=[],
                indeterminate=["https://torrentio-rate-limited.test/manifest.json"],
                dead=[],
            ),
        )

        def fake_search_and_download(**kwargs):
            return {
                "success": False,
                "error": "No streams found",
                "working_urls": [],
                "permanent_failure": True,
            }

        monkeypatch.setattr(processing, "search_and_download", fake_search_and_download)

        config = DownloadConfig(
            type="series",
            title="90 Day: The Single Life",
            imdb_id="tt13837776",
            season=2,
            episode_count=1,
            quality=QualitySettings(preferred="1080p"),
        )
        save_config(tmp_path / "download-config.json", config)

        result = process_season_folder(tmp_path, max_workers=1)
        assert result["failed"] == 1

        state = load_state(tmp_path)
        assert state.is_preflight_indeterminate("episode_1") is True, (
            "When the preflight was rate-limit saturated and the per-episode "
            "search returns 'No streams found', the episode must be recorded "
            "as indeterminate (TTL'd) so the next run can retry."
        )
        assert state.was_attempted("episode_1") == 0, (
            "An indeterminate marker must NOT count toward "
            "MAX_DOWNLOAD_ATTEMPTS — otherwise a single rate-limit "
            "burst permanently burns the retry budget."
        )

    def test_no_streams_found_without_indeterminate_preflight_marks_failed(
        self, tmp_path, monkeypatch
    ):
        """When the preflight found working addons (i.e. was not
        indeterminate) but the per-episode search still returned
        ``No streams found``, the episode IS genuinely missing and
        must be marked as a regular failure."""
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=5))
        monkeypatch.setattr(processing, "_PREFLIGHT_BACKOFF_SECONDS", 0.0)
        LivePreflightResult = processing._coerce_preflight.__globals__["PreflightResult"]
        monkeypatch.setattr(
            processing,
            "preflight_discover_working_addons",
            lambda *args, **kwargs: LivePreflightResult(
                alive=["https://torrentio.strem.fun/manifest.json"],
                indeterminate=[],
                dead=[],
            ),
        )

        def fake_search_and_download(**kwargs):
            return {
                "success": False,
                "error": "No streams found",
                "working_urls": [],
                "permanent_failure": True,
            }

        monkeypatch.setattr(processing, "search_and_download", fake_search_and_download)

        config = DownloadConfig(
            type="series",
            title="90 Day: The Single Life",
            imdb_id="tt13837776",
            season=2,
            episode_count=1,
            quality=QualitySettings(preferred="1080p"),
        )
        save_config(tmp_path / "download-config.json", config)

        result = process_season_folder(tmp_path, max_workers=1)
        assert result["failed"] == 1

        state = load_state(tmp_path)
        assert state.is_preflight_indeterminate("episode_1") is False
        assert state.was_attempted("episode_1") == 1, (
            "When the preflight was NOT indeterminate the episode must be "
            "recorded as a normal failure so the cross-run budget "
            "increments and the episode is eventually skipped."
        )


# ── Auto-reset stale retry budgets ────────────────────────────────


class TestAutoResetStaleFailedItems:
    """Stuck retry budgets must self-heal after enough time has passed
    (or after a metadata refresh), otherwise a brand-new episode in the
    same season would be permanently blocked by a counter left over
    from a long-dead source."""

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def test_helper_clears_entry_older_than_reset_window(self, tmp_path):
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        old = self._now() - timedelta(days=10)
        state.failed_items["episode_4"] = {
            "error": "No streams found",
            "attempt": 5,
            "timestamp": old.isoformat(),
        }
        cleared = _auto_reset_stale_failed_items(state, config, reset_days=7)
        assert cleared == [4]
        assert "episode_4" not in state.failed_items, (
            "An entry older than the reset window must be cleared so the "
            "episode can re-enter the missing list on the next run."
        )

    def test_helper_keeps_recent_entry(self, tmp_path):
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        recent = self._now() - timedelta(hours=2)
        state.failed_items["episode_4"] = {
            "error": "No streams found",
            "attempt": 5,
            "timestamp": recent.isoformat(),
        }
        cleared = _auto_reset_stale_failed_items(state, config, reset_days=7)
        assert cleared == []
        assert state.was_attempted("episode_4") == 5, (
            "A recent failure must NOT be auto-reset — the budget still "
            "exists to avoid burning runs on a known-broken source."
        )

    def test_helper_respects_reset_days_zero(self, tmp_path):
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        ancient = self._now() - timedelta(days=365)
        state.failed_items["episode_4"] = {
            "error": "No streams found",
            "attempt": 5,
            "timestamp": ancient.isoformat(),
        }
        cleared = _auto_reset_stale_failed_items(state, config, reset_days=0)
        assert cleared == []
        assert state.was_attempted("episode_4") == 5, (
            "FAILED_ITEM_AUTO_RESET_DAYS=0 must disable the self-heal so "
            "users who want strict 'once burned, always skipped' can opt in."
        )

    def test_helper_resets_on_metadata_refresh(self, tmp_path):
        """A metadata refresh is a stronger signal than a fixed timer:
        the metadata service has just re-validated the season, so any
        failure recorded before that refresh is automatically stale."""
        config = _season_config(tmp_path, episode_count=6)
        config.metadata_last_checked = (
            self._now() - timedelta(hours=1)
        ).isoformat()
        state = DownloadState(folder_path=tmp_path)
        # Failure was recorded 2 hours ago — within the 7-day window.
        state.failed_items["episode_4"] = {
            "error": "No streams found",
            "attempt": 5,
            "timestamp": (self._now() - timedelta(hours=2)).isoformat(),
        }
        cleared = _auto_reset_stale_failed_items(state, config, reset_days=7)
        assert cleared == [4]
        assert "episode_4" not in state.failed_items

    def test_helper_skips_episodes_no_longer_in_available_list(self, tmp_path):
        """If the metadata service dropped an episode from
        ``available_episodes`` the failure record must be left alone —
        silently resurrecting an episode the metadata has removed would
        surprise the user."""
        config = _season_config(tmp_path, episode_count=6)
        config.available_episodes = [1, 2, 3, 5, 6]  # 4 removed
        state = DownloadState(folder_path=tmp_path)
        ancient = self._now() - timedelta(days=30)
        state.failed_items["episode_4"] = {
            "error": "No streams found",
            "attempt": 5,
            "timestamp": ancient.isoformat(),
        }
        cleared = _auto_reset_stale_failed_items(state, config, reset_days=7)
        assert cleared == []
        assert state.was_attempted("episode_4") == 5

    def test_missing_episodes_admits_auto_reset_episode(self, tmp_path, monkeypatch, capsys):
        """End-to-end: a stuck episode older than the reset window must
        re-enter the missing list so the downloader actually tries it,
        and a one-line notice is printed so the user can see why."""
        # Other tests in this file mutate ``os.environ["PY_STREMIO_RETRY_FAILED"]``
        # via the CLI-flag helper without a monkeypatch.setenv, so make
        # sure it is NOT set here — otherwise the existing
        # ``PY_STREMIO_RETRY_FAILED`` bypass would mask the auto-reset
        # behaviour we want to assert.
        monkeypatch.delenv("PY_STREMIO_RETRY_FAILED", raising=False)
        monkeypatch.delenv("PY_STREMIO_CLI_RETRY_FAILED", raising=False)
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=5, reset_days=7))
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        ancient = self._now() - timedelta(days=14)
        state.failed_items["episode_4"] = {
            "error": "No streams found",
            "attempt": 5,
            "timestamp": ancient.isoformat(),
        }
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 in missing, (
            "An exhausted failure record older than the reset window must "
            "be auto-cleared so the episode re-enters the missing list. "
            "Otherwise a new episode in the same season can stay stuck "
            "forever (or until the user hand-edits .download-state.json)."
        )
        captured = capsys.readouterr().out
        assert "Auto-reset S02E04" in captured, (
            "The auto-reset must be announced so the user can see why a "
            "previously-skipped episode is being retried."
        )

    def test_missing_episodes_keeps_fresh_exhausted_episode(self, tmp_path, monkeypatch):
        """A failure record that is still inside the reset window must
        continue to be skipped — the self-heal must not undo the
        cross-run budget the moment the threshold is met."""
        # See note in ``test_missing_episodes_admits_auto_reset_episode``
        # — the leak from the CLI-flag test would otherwise bypass the
        # budget entirely via ``PY_STREMIO_RETRY_FAILED``.
        monkeypatch.delenv("PY_STREMIO_RETRY_FAILED", raising=False)
        monkeypatch.delenv("PY_STREMIO_CLI_RETRY_FAILED", raising=False)
        monkeypatch.setattr(processing, "settings", _settings(max_attempts=5, reset_days=7))
        config = _season_config(tmp_path, episode_count=6)
        state = DownloadState(folder_path=tmp_path)
        recent = self._now() - timedelta(hours=6)
        state.failed_items["episode_4"] = {
            "error": "No streams found",
            "attempt": 5,
            "timestamp": recent.isoformat(),
        }
        missing = _missing_episodes(tmp_path, config, state, season=2, existing_episodes=set())
        assert 4 not in missing, (
            "A fresh exhausted episode must stay skipped — the reset "
            "window exists to prevent the system from being stuck, not "
            "to bypass the budget the moment a failure happens."
        )
