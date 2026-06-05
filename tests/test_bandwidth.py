"""Tests for bandwidth limiting helpers."""

from py_stremio.components.download.bandwidth_service import BandwidthLimiter, build_limiter


def test_build_limiter_uses_percentage_of_max_speed_mbps():
    limiter = build_limiter(percent=50, max_speed_mbps=200)

    assert limiter is not None
    assert limiter.bytes_per_second == 12_500_000


def test_build_limiter_disables_at_100_percent():
    assert build_limiter(percent=100, max_speed_mbps=200) is None


def test_limiter_sleeps_when_window_exceeds_budget(monkeypatch):
    sleeps = []
    times = iter([0.0, 0.0])
    limiter = BandwidthLimiter(bytes_per_second=10, now=lambda: next(times), sleep=lambda seconds: sleeps.append(seconds))

    limiter.wait_for(15)

    assert sleeps == [0.5]
