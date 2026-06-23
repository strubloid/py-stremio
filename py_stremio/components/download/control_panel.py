"""Single-line bottom status bar with interactive download controls.

The bar lives on the terminal's LAST line, protected by a scroll region so
content scrolls above it.  Keyboard controls work without any toggle::

    ═══ Speed: 100% · 300 Mbps  T:4  [+/-]spd [s]pre [w/W]thr [t]pre [q]quit  ═══  ∷  2 active · 7.7 KB/s ═══
"""
from __future__ import annotations

import re
import shutil
import sys
import threading
import time
from typing import Any, Generator


ACCENT = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def _display_len(text: str) -> int:
    return len(re.sub(r"\033\[[0-9;]*m", "", text))


def _truncate_to_width(text: str, width: int) -> str:
    if _display_len(text) <= width:
        return text
    plain = re.sub(r"\033\[[0-9;]*m", "", text)
    if len(plain) <= width:
        return text
    return plain[:width]


def _format_bytes(byte_count: int | float) -> str:
    if byte_count < 1024:
        return f"{int(byte_count)} B"
    if byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f} KB"
    mb = byte_count / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"


# ── Scroll region helpers ────────────────────────────────────────────


def _setup_scroll_region(height: int) -> None:
    """Reserve the bottom line for a status bar via scroll region.

    After this, printable content only scrolls within lines 1 .. height-1.
    Line *height* is never touched by newline scrolling.
    """
    if height > 1:
        sys.stdout.write(f"\033[1;{height - 1}r")
        sys.stdout.flush()


def _reset_scroll_region() -> None:
    """Restore the default scroll region (full terminal)."""
    sys.stdout.write("\033[r")
    sys.stdout.flush()


def scroll_region_active(height: int) -> Generator:
    """Context manager: activate scroll region for the duration."""
    term_height = shutil.get_terminal_size(fallback=(100, 24)).lines if height is None else height
    _setup_scroll_region(term_height)
    try:
        yield
    finally:
        _reset_scroll_region()


# ── StatusBar ────────────────────────────────────────────────────────


class StatusBar:
    """Single-line interactive status bar at the terminal bottom.

    Sets up a terminal scroll region on start() that reserves the bottom
    line for the bar, then resets it on stop().  All printable content
    (print(), progress printer, etc.) scrolls normally in the area above.

    Usage::

        bar = StatusBar(limiter, workers_ref, speed_ref, max_mbps)
        bar.start()
        ...
        bar.update_stats(active=2, remaining=12, rate_bps=7_700_000)
        ...
        bar.stop()
    """

    def __init__(
        self,
        bandwidth_limiter: Any,
        max_workers_ref: list[int],
        speed_percent_ref: list[int],
        max_speed_mbps: float = 100.0,
    ):
        self.limiter = bandwidth_limiter
        self.max_workers_ref = max_workers_ref
        self.speed_percent_ref = speed_percent_ref
        self.max_speed_mbps = max_speed_mbps
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Download stats (updated externally via update_stats)
        self.active_count = 0
        self.total_remaining = 0
        self.overall_rate_bps: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Set up scroll region, draw bar, start key listener."""
        if self._running:
            return
        self._running = True
        self._setup_scroll()
        self._draw(force_setup=False)
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Clear bar, reset scroll region, stop key listener."""
        self._running = False
        self._clear()
        _reset_scroll_region()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def update_stats(
        self,
        active: int = 0,
        remaining: int = 0,
        rate_bps: float = 0.0,
    ) -> None:
        """Update download statistics and redraw the bar."""
        with self._lock:
            self.active_count = active
            self.total_remaining = remaining
            self.overall_rate_bps = rate_bps
        self._draw()

    # ── Scroll region ─────────────────────────────────────────────────────

    def _setup_scroll(self) -> None:
        """Set scroll region excluding the bottom line.  Handles resize."""
        _, height = self._term_size()
        _setup_scroll_region(height)

    # ── Rendering ─────────────────────────────────────────────────────────

    def _term_size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size(fallback=(100, 24))
        return size.columns, size.lines

    def _draw(self, force_setup: bool = True) -> None:
        """Draw the bar on the terminal's last line."""
        term_width, term_height = self._term_size()
        speed = self.speed_percent_ref[0]
        workers = self.max_workers_ref[0]

        if force_setup:
            # Re-apply scroll region on every draw so terminal resize is handled
            self._setup_scroll()

        # Colour-coded speed
        if speed == 0:
            speed_color = RED
        elif speed <= 25:
            speed_color = YELLOW
        elif speed <= 75:
            speed_color = ACCENT
        else:
            speed_color = GREEN

        # ── Left segment — controls ───────────────────────────────────────
        left = (
            f" \u2550\u2550\u2550 "
            f"Speed: {_c(f'{speed}%', speed_color)} of {_c(f'{self.max_speed_mbps:.0f} Mbps', ACCENT)}"
            f" {_c('[+/-]', YELLOW)}step {_c('[s]', YELLOW)}preset"
            f"  \u00b7  "
            f"Threads: {_c(str(workers), ACCENT)}"
            f" {_c('[w/W]', YELLOW)}step {_c('[t]', YELLOW)}preset"
            f"  \u00b7  {_c('[q]', RED)}quit"
        )

        # ── Right segment — download stats ────────────────────────────────
        stats_parts: list[str] = []
        if self.active_count > 0:
            stats_parts.append(f"{self.active_count} active")
        if self.total_remaining > 0:
            stats_parts.append(f"{self.total_remaining} left")
        if self.overall_rate_bps > 0:
            stats_parts.append(_format_bytes(int(self.overall_rate_bps)) + "/s")
        right = ""
        if stats_parts:
            sep = " \u2237  "
            right = f" {_c(sep + sep.join(stats_parts), DIM)}"

        # ── Fill middle so the bar spans the full width ───────────────────
        bare_len = _display_len(left) + _display_len(right)
        middle = " " * max(1, term_width - bare_len)
        line = f"{left}{middle}{right}"

        if _display_len(line) > term_width:
            line = _truncate_to_width(line, term_width)

        # ── Output — absolute position on the last line (no save/restore
        #    needed — the scroll region protects this line from scrolling) ──
        with self._lock:
            sys.stdout.write(f"\033[{term_height};1H")
            sys.stdout.write(f"\033[K{line}")
            # Reposition cursor to bottom of scroll region so the
            # progress printer's inline ANSI updates (cursor-up)
            # work correctly starting from just above the bar.
            sys.stdout.write(f"\033[{term_height - 1};1H")
            sys.stdout.flush()

    def _clear(self) -> None:
        """Erase the status bar line and move cursor to top."""
        _, term_height = self._term_size()
        sys.stdout.write(f"\033[{term_height};1H")
        sys.stdout.write("\033[K")
        sys.stdout.write(f"\033[{term_height - 1};1H")
        sys.stdout.flush()

    # ── Key handling ──────────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        """Daemon thread: listen for keyboard input."""
        import select
        import termios
        import tty

        fd = None
        old_settings = None
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            while self._running:
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    ch = sys.stdin.read(1)
                    if ch:
                        self._handle_key(ch)
                time.sleep(0.05)
        except (OSError, IOError):
            pass  # stdin not a TTY (e.g. tests)
        finally:
            if fd is not None and old_settings is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except (OSError, IOError):
                    pass

    def _handle_key(self, ch: str) -> None:
        if ch.lower() == "q":
            from py_stremio.utils.cancellation import request_shutdown

            request_shutdown()
        else:
            self._handle_menu_key(ch)

    def _handle_menu_key(self, ch: str) -> None:
        changed = False
        if ch == "+":
            self.speed_percent_ref[0] = min(100, self.speed_percent_ref[0] + 5)
            changed = True
        elif ch == "-":
            self.speed_percent_ref[0] = max(0, self.speed_percent_ref[0] - 5)
            changed = True
        elif ch.lower() == "s":
            presets = [25, 50, 75, 100]
            current = self.speed_percent_ref[0]
            idx = presets.index(current) if current in presets else 0
            self.speed_percent_ref[0] = presets[(idx + 1) % len(presets)]
            changed = True
        elif ch.lower() == "t":
            presets = [1, 2, 4, 8]
            current = self.max_workers_ref[0]
            idx = presets.index(current) if current in presets else 0
            self.max_workers_ref[0] = presets[(idx + 1) % len(presets)]
            changed = True
        elif ch == "w":
            self.max_workers_ref[0] = min(16, self.max_workers_ref[0] + 1)
            changed = True
        elif ch == "W":
            self.max_workers_ref[0] = max(1, self.max_workers_ref[0] - 1)
            changed = True

        if not changed:
            return

        # Update limiter if it exists (None at 100% speed)
        if self.limiter:
            clamped = max(0, min(100, self.speed_percent_ref[0]))
            if clamped >= 100 or self.max_speed_mbps <= 0:
                total_bps = 0
            else:
                total_bps = max(1, int((self.max_speed_mbps * 1_000_000 / 8) * (clamped / 100)))

            if hasattr(self.limiter, "update_total_limit"):
                self.limiter.update_total_limit(total_bps)
            elif hasattr(self.limiter, "update_speed"):
                self.limiter.update_speed(self.speed_percent_ref[0], self.max_speed_mbps)

        # Always redraw when speed/workers change, even without a limiter
        self._draw()


# ── Factory (backward-compatible signature) ────────────────────────────


def create_control_panel(
    bandwidth_limiter,
    max_workers: int,
    speed_percent: int,
    max_speed_mbps: float = 100.0,
    progress_line_count: int = 0,  # no longer used — kept for signature compat
) -> tuple[StatusBar, list[int], list[int]]:
    """Create and start the bottom status bar (was DownloadControlPanel).

    Returns (status_bar, workers_ref, speed_ref) — the last two are mutable
    lists that the caller can read for current values.
    """
    workers_ref = [max_workers]
    speed_ref = [speed_percent]
    bar = StatusBar(bandwidth_limiter, workers_ref, speed_ref, max_speed_mbps)
    bar.start()
    return bar, workers_ref, speed_ref
