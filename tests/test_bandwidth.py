"""Tests for bandwidth limiting helpers."""

from py_stremio.components.download.bandwidth_service import (
    BandwidthLimiter,
    FairBandwidthLimiter,
    build_limiter,
)


def test_build_limiter_uses_percentage_of_max_speed_mbps():
    limiter = build_limiter(percent=50, max_speed_mbps=200)

    assert limiter is not None
    assert limiter.bytes_per_second == 12_500_000


def test_build_limiter_disables_at_100_percent():
    limiter = build_limiter(percent=100, max_speed_mbps=200)
    assert limiter is not None
    # 100% speed returns a limiter with 0 bps (no throttling), always
    # ready to be adjusted downward at runtime.
    if isinstance(limiter, FairBandwidthLimiter):
        assert limiter.total_bytes_per_second == 0
    else:
        assert limiter.bytes_per_second == 0


def test_zero_percent_is_clamped_instead_of_becoming_unlimited():
    limiter = build_limiter(percent=0, max_speed_mbps=100)

    assert isinstance(limiter, BandwidthLimiter)
    assert limiter.bytes_per_second == 125_000


def test_limiter_sleeps_when_window_exceeds_budget(monkeypatch):
    sleeps = []
    times = iter([0.0, 0.0])
    limiter = BandwidthLimiter(bytes_per_second=10, now=lambda: next(times), sleep=lambda seconds: sleeps.append(seconds))

    limiter.wait_for(15)

    assert sleeps == [0.5]


def test_build_limiter_uses_fair_limiter_for_multiple_workers():
    limiter = build_limiter(percent=40, max_speed_mbps=100, max_workers=3)

    assert isinstance(limiter, FairBandwidthLimiter)
    assert limiter.total_bytes_per_second == 5_000_000


def test_single_thread_full_speed():
    sleeps = []
    limiter = FairBandwidthLimiter(
        total_bytes_per_second=5_000_000,
        now=lambda: 0.0,
        sleep=lambda seconds: sleeps.append(seconds),
    )

    limiter.register_thread(1)
    limiter.wait_for(1, 5_000_000)

    assert limiter.get_fair_share_bps() == 5_000_000
    assert sleeps == []


def test_two_threads_equal_share():
    sleeps = []
    limiter = FairBandwidthLimiter(
        total_bytes_per_second=5_000_000,
        now=lambda: 0.0,
        sleep=lambda seconds: sleeps.append(seconds),
    )

    limiter.register_thread(1)
    limiter.register_thread(2)
    limiter.wait_for(1, 2_500_000)
    limiter.wait_for(2, 2_500_001)

    assert limiter.get_fair_share_bps() == 2_500_000
    assert sleeps == [1 / 2_500_000]


def test_three_threads_equal_share():
    limiter = FairBandwidthLimiter(total_bytes_per_second=5_000_000, now=lambda: 0.0)

    limiter.register_thread(1)
    limiter.register_thread(2)
    limiter.register_thread(3)
    shares = [limiter._active_threads[thread_id].fair_share_bps for thread_id in (1, 2, 3)]

    assert shares == [1_666_666, 1_666_666, 1_666_666]


def test_dynamic_redistribution():
    limiter = FairBandwidthLimiter(total_bytes_per_second=5_000_000, now=lambda: 0.0)

    limiter.register_thread(1)
    assert limiter.get_fair_share_bps() == 5_000_000

    limiter.register_thread(2)
    assert limiter.get_fair_share_bps() == 2_500_000

    limiter.register_thread(3)
    assert limiter.get_fair_share_bps() == 1_666_666

    limiter.unregister_thread(2)
    assert limiter.get_fair_share_bps() == 2_500_000


def test_burst_handling_allows_short_bursts_within_thread_window():
    sleeps = []
    limiter = FairBandwidthLimiter(
        total_bytes_per_second=5_000_000,
        now=lambda: 0.0,
        sleep=lambda seconds: sleeps.append(seconds),
    )
    limiter.register_thread(1)
    limiter.register_thread(2)

    limiter.wait_for(1, 1_000_000)
    limiter.wait_for(1, 1_500_000)

    assert sleeps == []


def test_control_panel_speed_change_recalculates_immediately():
    limiter = FairBandwidthLimiter(total_bytes_per_second=5_000_000, now=lambda: 0.0)
    limiter.register_thread(1)
    limiter.register_thread(2)

    limiter.wait_for(1, 1_000_000)
    limiter.update_total_limit(10_000_000)

    assert limiter.get_fair_share_bps() == 5_000_000
    # Smooth-rate state after the rate change:
    # - Each thread's accumulator is reset, so the new 5MB/s fair share
    #   is in effect immediately (no leftover bytes from the 2.5MB/s
    #   window that would carry over as instantaneous debt).
    assert limiter._active_threads[1].bytes_in_window == 0
    assert limiter._active_threads[2].bytes_in_window == 0
    assert limiter._active_threads[1].fair_share_bps == 5_000_000
    assert limiter._active_threads[2].fair_share_bps == 5_000_000


def test_fair_limiter_accepts_stream_download_call_shape():
    sleeps = []
    limiter = FairBandwidthLimiter(
        total_bytes_per_second=10,
        now=lambda: 0.0,
        sleep=lambda seconds: sleeps.append(seconds),
    )

    limiter.register_thread(123)
    limiter.wait_for(15, thread_id=123)

    assert sleeps == [0.5]


def test_simple_limiter_accepts_stream_download_thread_id_keyword():
    sleeps = []
    limiter = BandwidthLimiter(bytes_per_second=10, now=lambda: 0.0, sleep=lambda seconds: sleeps.append(seconds))

    limiter.wait_for(15, thread_id=123)

    assert sleeps == [0.5]


def test_detected_max_speed_is_appended_to_env_when_missing(tmp_path, monkeypatch):
    from py_stremio.components.download import speed_probe

    env_path = tmp_path / ".env"
    env_path.write_text("ROOT_FOLDER=/tmp/media\n", encoding="utf-8")
    monkeypatch.delenv("INTERNET_MAX_SPEED_MBPS", raising=False)
    monkeypatch.setattr(speed_probe, "measure_download_speed_mbps", lambda: 237.4)

    speed = speed_probe.resolve_max_speed_mbps(env_path=env_path, default_mbps=100)

    assert speed == 237.4
    assert "ROOT_FOLDER=/tmp/media" in env_path.read_text(encoding="utf-8")
    assert "INTERNET_MAX_SPEED_MBPS=237.4" in env_path.read_text(encoding="utf-8")


def test_existing_env_max_speed_is_used_without_speed_test(tmp_path, monkeypatch):
    from py_stremio.components.download import speed_probe

    env_path = tmp_path / ".env"
    env_path.write_text("INTERNET_MAX_SPEED_MBPS=123.5\n", encoding="utf-8")
    monkeypatch.delenv("INTERNET_MAX_SPEED_MBPS", raising=False)

    def fail_measure():
        raise AssertionError("existing .env value should skip speed test")

    monkeypatch.setattr(speed_probe, "measure_download_speed_mbps", fail_measure)

    assert speed_probe.resolve_max_speed_mbps(env_path=env_path, default_mbps=100) == 123.5
    assert env_path.read_text(encoding="utf-8") == "INTERNET_MAX_SPEED_MBPS=123.5\n"


def test_bandwidth_limiter_smooth_rate_enforces_budget_over_sustained_run():
    """The old window-based limiter over-shot the budget by 24-30% in
    bursts because the delay calculation ignored elapsed time.  The
    continuous token-bucket implementation should land on the configured
    rate (within the rounding error of integer byte math) over a
    multi-second run with chunks arriving faster than the budget.
    """
    import threading

    target_bps = 1_000_000  # 1 MB/s
    chunk_size = 64_000      # 64 KB chunks delivered as fast as possible
    run_seconds = 3.0

    limiter = FairBandwidthLimiter(total_bytes_per_second=target_bps)
    thread_id = threading.get_ident()
    limiter.register_thread(thread_id)

    start = limiter.now()
    deadline = start + run_seconds
    total = 0
    while limiter.now() < deadline:
        limiter.wait_for(chunk_size, thread_id=thread_id)
        total += chunk_size
    elapsed = limiter.now() - start

    mbps = total / elapsed
    # Allow 5% headroom: chunk arrival jitter and the integer-bytes math
    # shouldn't push us more than a few percent over the configured rate.
    assert mbps <= target_bps * 1.05, f"got {mbps / 1_000_000:.2f} MB/s, expected ~1.00 MB/s"
    # And we shouldn't have starved either — should be close to the budget.
    assert mbps >= target_bps * 0.80, f"got {mbps / 1_000_000:.2f} MB/s, expected ~1.00 MB/s"


def test_bandwidth_limiter_fair_share_smooth_rate_under_concurrent_threads():
    """Multiple threads sharing a budget should land on the configured
    aggregate rate without bursty overshoot.
    """
    import threading

    target_bps = 5_000_000  # 5 MB/s aggregate
    run_seconds = 3.0
    num_threads = 5

    limiter = FairBandwidthLimiter(total_bytes_per_second=target_bps)

    counts = {"bytes": 0}
    counts_lock = threading.Lock()
    stop = threading.Event()

    def worker(tid: int) -> None:
        limiter.register_thread(tid)
        chunk_size = 32_000
        while not stop.is_set():
            limiter.wait_for(chunk_size, thread_id=tid)
            with counts_lock:
                counts["bytes"] += chunk_size

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    start = limiter.now()
    for t in threads:
        t.start()
    # Let the limiter's wall-clock advance so the token bucket refills
    while limiter.now() - start < run_seconds:
        limiter.sleep(0.05)
    stop.set()
    for t in threads:
        t.join()

    elapsed = limiter.now() - start
    mbps = counts["bytes"] / elapsed
    assert mbps <= target_bps * 1.05, f"got {mbps / 1_000_000:.2f} MB/s, expected ~5.00 MB/s"
    assert mbps >= target_bps * 0.80, f"got {mbps / 1_000_000:.2f} MB/s, expected ~5.00 MB/s"
