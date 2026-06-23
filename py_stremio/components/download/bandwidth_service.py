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
    fair_share_bps: int = 0
    last_active: float = 0


@dataclass
class FairBandwidthLimiter:
    """Fair-share bandwidth limiter with dynamic per-thread allocation.

    Total bandwidth is divided equally among active threads.
    Threads register/unregister as they start/finish downloads.
    """

    total_bytes_per_second: int
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _active_threads: dict[int, ThreadState] = field(default_factory=dict)
    _window_started: float = field(default_factory=time.monotonic)
    _total_bytes_in_window: int = 0

    def __post_init__(self) -> None:
        self._window_started = self.now()
        self._recalculate_fair_share()

    def register_thread(self, thread_id: int) -> None:
        """Register a new active download thread."""
        with self._lock:
            if thread_id not in self._active_threads:
                self._active_threads[thread_id] = ThreadState(
                    thread_id=thread_id,
                    fair_share_bps=self._fair_share_bps,
                    last_active=self.now(),
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
            elapsed = current_time - self._window_started

            # Reset window if 1 second has passed
            if elapsed >= 1:
                self._window_started = current_time
                self._total_bytes_in_window = 0
                for state in self._active_threads.values():
                    state.bytes_in_window = 0
                elapsed = 0

            # Use provided thread_id or generate one
            if thread_id is None:
                thread_id = threading.get_ident()

            # Get or create thread state
            state = self._active_threads.get(thread_id)
            if state is None:
                # Thread not registered, use full bandwidth (backward compat)
                state = ThreadState(
                    thread_id=thread_id,
                    fair_share_bps=self.total_bytes_per_second,
                    last_active=current_time,
                )
                self._active_threads[thread_id] = state
                self._recalculate_fair_share()

            # Update thread's byte count
            state.bytes_in_window += byte_count
            self._total_bytes_in_window += byte_count
            state.last_active = current_time

            # Check if this thread exceeded its fair share
            fair_share = state.fair_share_bps
            if state.bytes_in_window > fair_share:
                overflow = state.bytes_in_window - fair_share
                delay = overflow / fair_share if fair_share > 0 else 0
        if delay > 0:
            self.sleep(delay)

    def _recalculate_fair_share(self) -> None:
        """Recalculate bytes/sec per active thread."""
        active_count = len(self._active_threads)
        if active_count == 0:
            self._fair_share_bps = self.total_bytes_per_second
        else:
            self._fair_share_bps = max(1, self.total_bytes_per_second // active_count)

        # Update all active threads
        for state in self._active_threads.values():
            state.fair_share_bps = self._fair_share_bps

    def update_total_limit(self, total_bytes_per_second: int) -> None:
        """Update total bandwidth limit and recalculate fair shares."""
        with self._lock:
            self.total_bytes_per_second = total_bytes_per_second
            self._recalculate_fair_share()
            # Reset window to apply immediately
            self._window_started = self.now()
            self._total_bytes_in_window = 0
            for state in self._active_threads.values():
                state.bytes_in_window = 0

    def get_fair_share_bps(self) -> int:
        """Get current fair share per thread in bytes/sec."""
        return self._fair_share_bps

    def get_active_thread_count(self) -> int:
        """Get number of currently active threads."""
        return len(self._active_threads)


# Backward compatibility: simple global limiter (no fair sharing)
@dataclass
class BandwidthLimiter:
    """Simple process-wide limiter using a one-second accounting window."""

    bytes_per_second: int
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _window_started: float = field(default_factory=time.monotonic)
    _bytes_in_window: int = 0

    def wait_for(self, byte_count: int, thread_id: int | None = None) -> None:
        del thread_id  # Accepted for compatibility with download_stream_to_file.
        if self.bytes_per_second <= 0 or byte_count <= 0:
            return
        delay = 0.0
        with self._lock:
            current_time = self.now()
            elapsed = current_time - self._window_started
            if elapsed >= 1:
                self._window_started = current_time
                self._bytes_in_window = 0
                elapsed = 0

            self._bytes_in_window += byte_count
            if self._bytes_in_window <= self.bytes_per_second:
                return

            overflow = self._bytes_in_window - self.bytes_per_second
            delay = overflow / self.bytes_per_second
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
    clamped_percent = max(0, min(100, int(percent)))

    if clamped_percent >= 100 or max_speed_mbps <= 0:
        total_bytes_per_second = 0
    else:
        total_bytes_per_second = int((max_speed_mbps * 1_000_000 / 8) * (clamped_percent / 100))

    if max_workers > 1:
        return FairBandwidthLimiter(total_bytes_per_second=total_bytes_per_second)
    else:
        return BandwidthLimiter(bytes_per_second=total_bytes_per_second)