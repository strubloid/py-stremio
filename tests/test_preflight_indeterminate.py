"""Regression tests for the preflight addon discovery and the rate-limit
saturation state introduced to fix the
"Preflight found no working addons" cascade bug."""

from unittest.mock import MagicMock

import pytest

from py_stremio.components.addons import addon_search_service as ass_module
from py_stremio.components.addons.addon_search_service import (
    PreflightResult,
    _coerce_preflight,
    preflight_discover_working_addons,
)
from py_stremio.components.addons.rate_limiter import RateLimiter
from py_stremio.components.addons import rate_limiter as rl


@pytest.fixture(autouse=True)
def _restore_rate_limiter_constants():
    saved = {
        "MAX_REQUESTS_PER_HOST": rl._MAX_REQUESTS_PER_HOST,
        "WINDOW_SECONDS": rl._WINDOW_SECONDS,
        "MAX_SLEEP_ON_CAP": rl._MAX_SLEEP_ON_CAP,
    }
    try:
        yield
    finally:
        rl._MAX_REQUESTS_PER_HOST = saved["MAX_REQUESTS_PER_HOST"]
        rl._WINDOW_SECONDS = saved["WINDOW_SECONDS"]
        rl._MAX_SLEEP_ON_CAP = saved["MAX_SLEEP_ON_CAP"]


@pytest.fixture
def real_preflight(monkeypatch):
    """Restore the real preflight function (overridden by conftest) for this test.

    The conftest patches the module attribute at import time. The preflight
    function imported into THIS test module is the MagicMock. We re-import
    from the live module so the real implementation is used.
    """
    import importlib
    saved = ass_module.preflight_discover_working_addons
    importlib.reload(ass_module)
    real_fn = ass_module.preflight_discover_working_addons
    monkeypatch.setattr(ass_module, "preflight_discover_working_addons", real_fn)
    # Also rebind the test module's local import.
    globals()["preflight_discover_working_addons"] = real_fn
    yield real_fn
    ass_module.preflight_discover_working_addons = saved
    globals()["preflight_discover_working_addons"] = saved


# ── Coercion helper ────────────────────────────────────────────────────


def test_coerce_preflight_accepts_existing_result():
    result = PreflightResult(alive=["a", "b"], dead=["c"])
    coerced = _coerce_preflight(result)
    assert coerced is result


def test_coerce_preflight_accepts_list_as_alive_bucket():
    coerced = _coerce_preflight(["https://x.test"])
    assert coerced.alive == ["https://x.test"]
    assert coerced.indeterminate == []
    assert coerced.dead == []


def test_coerce_preflight_accepts_empty_list():
    coerced = _coerce_preflight([])
    assert not coerced.has_working
    assert not coerced.has_unknown


def test_coerce_preflight_accepts_none_as_empty():
    coerced = _coerce_preflight(None)
    assert not coerced.has_working
    assert not coerced.has_unknown


# ── PreflightResult dataclass ──────────────────────────────────────────


def test_preflight_result_bool_is_alive_only():
    assert bool(PreflightResult(alive=["x"])) is True
    assert bool(PreflightResult(indeterminate=["x"])) is False
    assert bool(PreflightResult(dead=["x"])) is False
    assert bool(PreflightResult()) is False


def test_preflight_result_url_set_unions_buckets():
    result = PreflightResult(alive=["a"], indeterminate=["b"], dead=["c"])
    assert result.to_url_set() == {"a", "b", "c"}


# ── preflight_discover_working_addons with rate-limit ──────────────────


def _make_fake_addon(url: str, behavior):
    """Return a fake addon whose get_streams runs *behavior* and get_url returns *url*."""
    addon = MagicMock()
    addon.get_streams.side_effect = behavior
    addon.get_url.return_value = url
    return addon


def test_preflight_classifies_rate_limited_addon_as_indeterminate(monkeypatch, real_preflight):
    from py_stremio.components.addons import cloudscraper_client
    from py_stremio.components.addons.cloudscraper_client import CloudscraperError

    limiter = RateLimiter()
    fake_url = "https://torrentio-rate-limited.test/manifest.json"
    normalized = "https://torrentio-rate-limited.test"

    def boom(*args, **kwargs):
        raise CloudscraperError("Rate limit cap saturated: torrentio-rate-limited.test — 50 requests in last 300s, would need to wait 9999s")

    # Pre-saturate the limiter so is_saturated() returns True for the fake host.
    rl._MAX_REQUESTS_PER_HOST = 1
    rl._WINDOW_SECONDS = 60.0
    rl._MAX_SLEEP_ON_CAP = 0.0
    with limiter.request(fake_url):
        pass
    # Now the next request to that host would raise 'cap saturated'.

    fake_addon = _make_fake_addon(fake_url, boom)
    fake_manager = MagicMock()
    fake_manager.addons = [fake_addon]

    monkeypatch.setattr(
        "py_stremio.components.addons.create_addon_manager",
        lambda: fake_manager,
    )

    result = preflight_discover_working_addons("series", "tt123:1:1")

    assert normalized in result.indeterminate, (
        "rate-limited addons must be reported as 'indeterminate', not 'dead' — "
        f"otherwise the preflight cascades into 'no working addons'. got {result}"
    )
    assert result.has_working is False
    assert result.has_unknown is True


def test_preflight_classifies_normal_failure_as_dead(monkeypatch, real_preflight):
    from py_stremio.components.addons.cloudscraper_client import CloudscraperError

    fake_url = "https://always-500.test/manifest.json"
    normalized = "https://always-500.test"

    def boom(*args, **kwargs):
        raise CloudscraperError("500 Internal Server Error")

    fake_addon = _make_fake_addon(fake_url, boom)
    fake_manager = MagicMock()
    fake_manager.addons = [fake_addon]

    monkeypatch.setattr(
        "py_stremio.components.addons.create_addon_manager",
        lambda: fake_manager,
    )

    result = preflight_discover_working_addons("series", "tt123:1:1")

    assert normalized in result.dead
    assert not result.has_unknown


def test_preflight_reports_live_addon_in_alive_bucket(monkeypatch, real_preflight):
    from py_stremio.components.addons.models import StreamInfo

    fake_url = "https://working-addon.test/manifest.json"
    normalized = "https://working-addon.test"
    fake_addon = MagicMock()
    fake_addon.get_streams.return_value = [
        StreamInfo(
            name="Test",
            url="https://dl.test/file.mkv",
            title="Some.Show.S01E01.1080p.WEB.x264",
            addon_url=fake_url,
        )
    ]
    fake_addon.get_url.return_value = fake_url
    fake_manager = MagicMock()
    fake_manager.addons = [fake_addon]

    monkeypatch.setattr(
        "py_stremio.components.addons.create_addon_manager",
        lambda: fake_manager,
    )

    result = preflight_discover_working_addons(
        "series", "tt123:1:1", title="Some Show", season=1, episode=1, imdb_id="tt123"
    )

    assert normalized in result.alive
    assert not result.has_unknown
    assert not result.dead


# ── processing.py integration: preflight indeterminate does NOT skip ────


def test_season_folder_with_indeterminate_preflight_does_not_skip_search(tmp_path, monkeypatch):
    """Regression: when the preflight is indeterminate (rate-limited) the
    per-episode search must NOT be skipped — otherwise the season is
    permanently blocked until the user runs py-stremio in a fresh
    process."""
    from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings, save_config
    from py_stremio.components.download import processing

    config = DownloadConfig(
        type="series",
        title="Test Show",
        imdb_id="tt1234567",
        season=1,
        episode_count=2,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)

    # Always read PreflightResult from the processing module — a previous
    # test may have reloaded the addon_search_service module and produced
    # a different class object. The processing module's
    # ``_coerce_preflight`` was bound at import time so we need the same
    # PreflightResult class the production code uses.
    LivePreflightResult = processing._coerce_preflight.__globals__["PreflightResult"]

    preflight = LivePreflightResult(
        alive=[],
        indeterminate=["https://torrentio.test/manifest.json"],
        dead=[],
    )
    skip_flags: list[bool] = []

    def fake_preflight(*args, **kwargs):
        return preflight

    monkeypatch.setattr(
        processing,
        "preflight_discover_working_addons",
        fake_preflight,
    )

    def fake_search_and_download(**kwargs):
        skip_flags.append(kwargs["skip_full_search"])
        return {
            "success": False,
            "error": "still rate-limited",
            "working_urls": [],
            "permanent_failure": True,
        }

    monkeypatch.setattr(
        processing, "search_and_download", fake_search_and_download
    )

    monkeypatch.setattr(processing, "settings", _fake_settings())

    # Avoid the 3-second retry sleep in the preflight.
    monkeypatch.setattr(processing, "_PREFLIGHT_BACKOFF_SECONDS", 0.0)

    processing.process_season_folder(tmp_path, max_workers=1)

    assert skip_flags, "expected at least one per-episode search"
    assert all(flag is False for flag in skip_flags), (
        "When the preflight is indeterminate, skip_full_search must be False "
        "so the per-episode pipeline gets a chance to find a free slot."
    )


def test_season_folder_with_dead_preflight_does_skip_search(tmp_path, monkeypatch):
    """When the preflight is empty AND the addons are confirmed dead
    (not just rate-limited), the per-episode search can be safely
    skipped."""
    from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings, save_config
    from py_stremio.components.download import processing

    config = DownloadConfig(
        type="series",
        title="Unknown Show",
        imdb_id="tt9999999",
        season=1,
        episode_count=2,
        quality=QualitySettings(preferred="1080p"),
    )
    save_config(tmp_path / "download-config.json", config)

    LivePreflightResult = processing._coerce_preflight.__globals__["PreflightResult"]
    preflight = LivePreflightResult(alive=[], indeterminate=[], dead=["https://x.test/manifest.json"])
    skip_flags: list[bool] = []

    monkeypatch.setattr(
        processing,
        "preflight_discover_working_addons",
        lambda *args, **kwargs: preflight,
    )

    def fake_search_and_download(**kwargs):
        skip_flags.append(kwargs["skip_full_search"])
        return {
            "success": False,
            "error": "Preflight found no working addons",
            "working_urls": [],
            "permanent_failure": True,
        }

    monkeypatch.setattr(
        processing, "search_and_download", fake_search_and_download
    )

    monkeypatch.setattr(processing, "settings", _fake_settings())
    monkeypatch.setattr(processing, "_PREFLIGHT_BACKOFF_SECONDS", 0.0)

    processing.process_season_folder(tmp_path, max_workers=1)

    assert skip_flags
    assert all(flag is True for flag in skip_flags), (
        "When the preflight finds only dead addons, skip_full_search must "
        "stay True to avoid burning 30+ seconds per missing episode."
    )


# ── Local helper ──────────────────────────────────────────────────────


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
