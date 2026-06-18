"""Shared bandwidth limiting helpers for downloads."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class BandwidthLimiter:
    """Simple process-wide limiter using a one-second accounting window."""

    bytes_per_second: int
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _window_started: float = field(default_factory=time.monotonic)
    _bytes_in_window: int = 0

    def wait_for(self, byte_count: int) -> None:
        if self.bytes_per_second <= 0 or byte_count <= 0:
            return
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
            # Reset window to apply immediately
            self._window_started = self.now()
            self._bytes_in_window = 0


def build_limiter(percent: int, max_speed_mbps: float) -> BandwidthLimiter | None:
    """Build a limiter from percentage of configured max Mbps.

    percent=100 means no limiting. max_speed_mbps is megabits/sec.
    """
    clamped_percent = max(0, min(100, int(percent)))
    if clamped_percent >= 100 or max_speed_mbps <= 0:
        return None
    bytes_per_second = int((max_speed_mbps * 1_000_000 / 8) * (clamped_percent / 100))
    return BandwidthLimiter(bytes_per_second=max(1, bytes_per_second))
