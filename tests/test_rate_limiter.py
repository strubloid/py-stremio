"""Regression tests for addon HTTP rate limiting."""

import threading

import pytest

from py_stremio.components.addons.rate_limiter import RateLimiter


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
