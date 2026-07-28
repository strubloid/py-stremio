"""Regression tests for addon HTTP rate limiting."""

import threading
import time

import pytest

from py_stremio.components.addons import rate_limiter as rl
from py_stremio.components.addons.rate_limiter import RateLimiter


@pytest.fixture(autouse=True)
def _restore_module_constants():
    """Snapshot the rate-limiter module constants and restore them after the test.

    The windowed-cap tests mutate ``_MAX_REQUESTS_PER_HOST`` and
    ``_WINDOW_SECONDS`` on the module. Save and restore them so the rest
    of the test suite is unaffected.
    """
    saved = {
        "MIN_GAP": rl.MIN_GAP,
        "MAX_REQUESTS_PER_HOST": rl._MAX_REQUESTS_PER_HOST,
        "WINDOW_SECONDS": rl._WINDOW_SECONDS,
        "MAX_SLEEP_ON_CAP": rl._MAX_SLEEP_ON_CAP,
        "DISABLE_DELAYS": rl._DISABLE_DELAYS,
    }
    try:
        yield
    finally:
        rl.MIN_GAP = saved["MIN_GAP"]
        rl._MAX_REQUESTS_PER_HOST = saved["MAX_REQUESTS_PER_HOST"]
        rl._WINDOW_SECONDS = saved["WINDOW_SECONDS"]
        rl._MAX_SLEEP_ON_CAP = saved["MAX_SLEEP_ON_CAP"]
        rl._DISABLE_DELAYS = saved["DISABLE_DELAYS"]


def test_report_success_inside_request_context_does_not_deadlock():
    limiter = RateLimiter()
    url = "https://example-rate-limiter.test/stream/series/tt123:1:1.json"
    done = threading.Event()
    errors: list[BaseException] = []

    def worker():
        try:
            with limiter.request(url):
                limiter.report_success(url)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=1.0)

    assert done.is_set(), "rate limiter deadlocked when report_success re-entered the host lock"
    assert errors == []


def test_report_429_inside_request_context_does_not_deadlock():
    limiter = RateLimiter()
    url = "https://example-rate-limiter-429.test/stream/series/tt123:1:1.json"
    done = threading.Event()
    errors: list[BaseException] = []

    def worker():
        try:
            with limiter.request(url):
                limiter.report_429(url)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=1.0)

    assert done.is_set(), "rate limiter deadlocked when report_429 re-entered the host lock"
    assert errors == []


def test_request_skips_host_during_429_cooldown_without_waiting():
    limiter = RateLimiter()
    url = "https://example-rate-limiter-cooldown.test/stream/series/tt123:1:1.json"

    with limiter.request(url):
        limiter.report_429(url)

    with pytest.raises(RuntimeError, match="cooling down"):
        with limiter.request(url):
            pass


def _make_limiter_with_short_window(max_requests: int, window_seconds: float):
    """Return a fresh limiter with the cap configured to (max_requests, window_seconds)."""
    rl._MAX_REQUESTS_PER_HOST = max_requests
    rl._WINDOW_SECONDS = window_seconds
    rl._DISABLE_DELAYS = True
    return RateLimiter()


def test_windowed_cap_refills_when_oldest_request_leaves_window():
    """Old requests must fall out of the window so the budget refills."""
    limiter = _make_limiter_with_short_window(max_requests=3, window_seconds=2.0)
    url = "https://windowed-refill.test/stream/series/tt1:1:1.json"

    real_monotonic = time.monotonic
    fake_now = {"value": 1000.0}
    time.monotonic = lambda: fake_now["value"]  # type: ignore[assignment]
    try:
        for _ in range(3):
            with limiter.request(url):
                pass
            fake_now["value"] += 0.1

        # Cap is full — next request would block; advance time past the window.
        fake_now["value"] += 5.0
        with limiter.request(url):
            pass  # should not raise
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]


def test_windowed_cap_sleeps_until_oldest_request_expires():
    """When the cap is hit, the limiter must wait (not raise) for the oldest
    request to leave the window."""
    limiter = _make_limiter_with_short_window(max_requests=2, window_seconds=2.0)
    url = "https://windowed-sleep.test/stream/series/tt1:1:1.json"

    real_monotonic = time.monotonic
    real_sleep = time.sleep
    fake_now = {"value": 2000.0}
    sleep_calls: list[float] = []
    time.monotonic = lambda: fake_now["value"]  # type: ignore[assignment]
    time.sleep = lambda seconds: (sleep_calls.append(seconds), fake_now.__setitem__("value", fake_now["value"] + seconds))[1]  # type: ignore[assignment]
    try:
        for _ in range(2):
            with limiter.request(url):
                pass
            fake_now["value"] += 0.1

        # Cap is full. The next request must sleep until the oldest entry
        # is 2.0s old — about 1.8s in the future from now (1.9s elapsed).
        with limiter.request(url):
            pass
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]
        time.sleep = real_sleep  # type: ignore[assignment]

    assert sleep_calls, "limiter should have slept while waiting for the window to free up"
    assert all(s <= rl._MAX_SLEEP_ON_CAP for s in sleep_calls)


def test_windowed_cap_raises_when_wait_exceeds_max_sleep():
    """When the cap is fully saturated and the wait would exceed
    ``_MAX_SLEEP_ON_CAP``, raise so the preflight can mark the addon
    'indeterminate' instead of 'dead'."""
    limiter = _make_limiter_with_short_window(max_requests=2, window_seconds=10000.0)
    rl._MAX_SLEEP_ON_CAP = 5.0
    url = "https://windowed-saturated.test/stream/series/tt1:1:1.json"

    real_monotonic = time.monotonic
    fake_now = {"value": 5000.0}
    time.monotonic = lambda: fake_now["value"]  # type: ignore[assignment]
    try:
        for _ in range(2):
            with limiter.request(url):
                pass
            fake_now["value"] += 0.1

        with pytest.raises(RuntimeError, match="cap saturated"):
            with limiter.request(url):
                pass
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]


def test_zero_cap_disables_window_check():
    """Setting ``PY_STREMIO_RATE_LIMIT_CAP=0`` must disable the cap entirely."""
    limiter = _make_limiter_with_short_window(max_requests=0, window_seconds=1.0)
    url = "https://windowed-disabled.test/stream/series/tt1:1:1.json"
    for _ in range(5):
        with limiter.request(url):
            pass


def test_is_saturated_reflects_window_state():
    limiter = _make_limiter_with_short_window(max_requests=2, window_seconds=2.0)
    url = "https://windowed-issaturated.test/stream/series/tt1:1:1.json"

    assert limiter.is_saturated(url) is False
    with limiter.request(url):
        pass
    assert limiter.is_saturated(url) is False
    with limiter.request(url):
        pass
    assert limiter.is_saturated(url) is True


def test_lifetime_counter_still_increments():
    """The lifetime ``request_count`` is kept for diagnostics and must still grow."""
    limiter = _make_limiter_with_short_window(max_requests=5, window_seconds=2.0)
    url = "https://windowed-counter.test/stream/series/tt1:1:1.json"
    for _ in range(3):
        with limiter.request(url):
            pass
    state = limiter._hosts[_extract(url)]
    assert state.request_count == 3


def _extract(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.netloc or parsed.hostname or "").lower()
    return host.split(":")[0]
