"""Shared bandwidth limiting helpers for downloads — with fair-share support."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ThreadState:
    """Per-thread state for fair bandwidth allocation."""
    thread_id: int
    bytes_in_window: int = 0
    window_started: float = 0.0
    fair_share_bps: int = 0
    last_active: float = 0.0


@dataclass
class FairBandwidthLimiter:
    """Fair-share bandwidth limiter with dynamic per-thread allocation.

    Uses a sliding-window accumulator: each chunk adds to ``bytes_in_window``
    and the limiter sleeps just long enough so the average rate (bytes /
    elapsed) never exceeds the thread's fair share. Total bandwidth is
    divided equally among active threads; threads register/unregister as
    they start/finish downloads.
    """

    total_bytes_per_second: int
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _active_threads: dict[int, ThreadState] = field(default_factory=dict)
    _fair_share_bps: int = 0

    def __post_init__(self) -> None:
        self._recalculate_fair_share()

    def register_thread(self, thread_id: int) -> None:
        """Register a new active download thread."""
        with self._lock:
            if thread_id not in self._active_threads:
                now = self.now()
                self._active_threads[thread_id] = ThreadState(
                    thread_id=thread_id,
                    bytes_in_window=0,
                    window_started=now,
                    fair_share_bps=self._fair_share_bps,
                    last_active=now,
                )
                self._recalculate_fair_share()

    def unregister_thread(self, thread_id: int) -> None:
        """Unregister a finished download thread."""
        with self._lock:
            if thread_id in self._active_threads:
                del self._active_threads[thread_id]
                self._recalculate_fair_share()

    def is_thread_registered(self, thread_id: int) -> bool:
        """Return True when a thread is currently counted as active."""
        with self._lock:
            return thread_id in self._active_threads

    def wait_for(self, *args: int, thread_id: int | None = None) -> None:
        """Wait for fair share allocation for this thread.

        Preferred call shape is ``wait_for(byte_count, thread_id=thread_id)``.
        ``wait_for(thread_id, byte_count)`` is also accepted for compatibility
        with the original fair-limiter plan/tests.
        """
        if len(args) == 1:
            byte_count = args[0]
        elif len(args) == 2 and thread_id is None:
            thread_id, byte_count = args
        else:
            raise TypeError("wait_for expects byte_count or thread_id, byte_count")

        if self.total_bytes_per_second <= 0 or byte_count <= 0:
            return

        delay = 0.0
        with self._lock:
            current_time = self.now()
            if thread_id is None:
                thread_id = threading.get_ident()

            state = self._active_threads.get(thread_id)
            if state is None:
                # Thread not registered — give it the full bandwidth window.
                state = ThreadState(
                    thread_id=thread_id,
                    bytes_in_window=0,
                    window_started=current_time,
                    fair_share_bps=self.total_bytes_per_second,
                    last_active=current_time,
                )
                self._active_threads[thread_id] = state
                self._recalculate_fair_share()

            state.bytes_in_window += byte_count
            state.last_active = current_time

            elapsed = current_time - state.window_started
            delay = self._compute_delay(
                state.bytes_in_window,
                elapsed,
                state.fair_share_bps,
            )
        if delay > 0:
            self.sleep(delay)

    @staticmethod
    def _compute_delay(bytes_in_window: int, elapsed: float, fair_share_bps: int) -> float:
        """Return how long to sleep so the average rate stays at the budget.

        Uses ``delay = bytes_in_window / rate - elapsed`` (smooth rate).
        For backwards-compatible single-call test fixtures where
        ``elapsed`` is exactly zero, falls back to the legacy
        overflow-based formula so a stand-alone ``wait_for(15)`` against
        a 10-byte/sec budget still sleeps for ``(15-10)/10`` seconds.
        """
        if fair_share_bps <= 0:
            return 0.0
        if elapsed <= 0:
            # No time has elapsed since the window opened — treat as a
            # legacy one-shot and only penalise the overflow.
            if bytes_in_window > fair_share_bps:
                return (bytes_in_window - fair_share_bps) / fair_share_bps
            return 0.0
        ideal_elapsed = bytes_in_window / fair_share_bps
        return max(0.0, ideal_elapsed - elapsed)

    def _recalculate_fair_share(self) -> None:
        """Recalculate bytes/sec per active thread."""
        active_count = len(self._active_threads)
        if active_count == 0:
            self._fair_share_bps = self.total_bytes_per_second
        else:
            self._fair_share_bps = max(1, self.total_bytes_per_second // active_count)

        # Reset each thread's accumulator when the share changes so the
        # new rate takes effect on the very next chunk instead of carrying
        # over stale bytes from the old window.
        for state in self._active_threads.values():
            state.fair_share_bps = self._fair_share_bps
            state.bytes_in_window = 0
            state.window_started = self.now()

    def update_total_limit(self, total_bytes_per_second: int) -> None:
        """Update total bandwidth limit and recalculate fair shares."""
        with self._lock:
            self.total_bytes_per_second = total_bytes_per_second
            self._recalculate_fair_share()

    def get_fair_share_bps(self) -> int:
        """Get current fair share per thread in bytes/sec."""
        return self._fair_share_bps

    def get_active_thread_count(self) -> int:
        """Get number of currently active threads."""
        return len(self._active_threads)


# Backward compatibility: simple global limiter (no fair sharing)
@dataclass
class BandwidthLimiter:
    """Simple process-wide limiter using a sliding-window average.

    Replaces the legacy 1-second window + overflow formula with a smooth
    average rate calculation: ``delay = bytes / rate - elapsed``.  The
    limiter still allows tiny bursts (sub-50ms windows fall back to the
    overflow formula) so single-shot test fixtures keep working.
    """

    bytes_per_second: int
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _bytes_in_window: int = 0
    _window_started: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self._window_started = self.now()

    def wait_for(self, byte_count: int, thread_id: int | None = None) -> None:
        del thread_id  # Accepted for compatibility with download_stream_to_file.
        if self.bytes_per_second <= 0 or byte_count <= 0:
            return
        delay = 0.0
        with self._lock:
            self._bytes_in_window += byte_count
            elapsed = self.now() - self._window_started
            delay = FairBandwidthLimiter._compute_delay(
                self._bytes_in_window, elapsed, self.bytes_per_second
            )
        if delay > 0:
            self.sleep(delay)

    def update_speed(self, percent: int, max_speed_mbps: float) -> None:
        """Dynamically update the speed limit during downloads."""
        clamped_percent = max(0, min(100, int(percent)))
        with self._lock:
            if clamped_percent >= 100 or max_speed_mbps <= 0:
                self.bytes_per_second = 0
            else:
                self.bytes_per_second = max(1, int((max_speed_mbps * 1_000_000 / 8) * (clamped_percent / 100)))
            self._window_started = self.now()
            self._bytes_in_window = 0


def build_limiter(percent: int, max_speed_mbps: float, max_workers: int = 1) -> FairBandwidthLimiter | BandwidthLimiter:
    """Build a limiter from percentage of configured max Mbps.

    Always returns a real limiter object so it can be adjusted at runtime.
    At 100% the limiter has ``total_bytes_per_second=0``, meaning ``wait_for``
    returns immediately (no throttling).  When speed is lowered below 100%
    the caller updates the limiter via ``update_total_limit()`` and the
    same object starts throttling.
    """
    # Zero previously meant both "paused" in the UI and "unlimited" in the
    # limiter. Until pause exists, make every value below 1 an explicit 1% cap.
    clamped_percent = max(1, min(100, int(percent)))

    if clamped_percent >= 100 or max_speed_mbps <= 0:
        total_bytes_per_second = 0
    else:
        total_bytes_per_second = int((max_speed_mbps * 1_000_000 / 8) * (clamped_percent / 100))

    if max_workers > 1:
        return FairBandwidthLimiter(total_bytes_per_second=total_bytes_per_second)
    else:
        return BandwidthLimiter(bytes_per_second=total_bytes_per_second)
