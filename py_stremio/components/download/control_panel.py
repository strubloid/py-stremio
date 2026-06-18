"""Interactive download controls — floating menu for speed/thread adjustments during downloads."""
import sys
import threading
import time
from typing import Callable, Optional

from py_stremio.services.progress import ACCENT, GREEN, YELLOW, RED, DIM, RESET


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


class DownloadControlPanel:
    """Floating control panel for active downloads."""

    def __init__(
        self,
        bandwidth_limiter,
        max_workers_ref: list[int],
        speed_percent_ref: list[int],
        max_speed_mbps: float = 100.0,
    ):
        self.limiter = bandwidth_limiter
        self.max_workers_ref = max_workers_ref  # mutable ref [current_workers]
        self.speed_percent_ref = speed_percent_ref  # mutable ref [current_speed%]
        self.max_speed_mbps = max_speed_mbps
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._menu_visible = False
        self._lock = threading.Lock()

    def start(self):
        """Start the key listener thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the key listener thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _listen_loop(self):
        """Listen for key presses (non-blocking)."""
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while self._running:
                if sys.stdin in __import__('select').select([sys.stdin], [], [], 0.1)[0]:
                    ch = sys.stdin.read(1)
                    if ch:
                        self._handle_key(ch)
                time.sleep(0.05)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _handle_key(self, ch: str):
        """Handle key press."""
        if ch.lower() == 'm':
            self._toggle_menu()
        elif ch.lower() == 'q':
            # Signal shutdown
            from py_stremio.utils.cancellation import request_shutdown
            request_shutdown()
        elif self._menu_visible:
            self._handle_menu_key(ch)

    def _toggle_menu(self):
        with self._lock:
            self._menu_visible = not self._menu_visible
            if self._menu_visible:
                self._draw_menu()
            else:
                self._clear_menu()

    def _clear_menu(self):
        """Clear the menu overlay."""
        # Move up and clear lines
        lines = 8
        sys.stdout.write(f"\033[{lines}A")  # Move up
        for _ in range(lines):
            sys.stdout.write("\033[2K\r")  # Clear line
        sys.stdout.write(f"\033[{lines}A")  # Move up again
        sys.stdout.flush()

    def _draw_menu(self):
        """Draw the floating control menu."""
        speed = self.speed_percent_ref[0]
        workers = self.max_workers_ref[0]
        max_mbps = self.max_speed_mbps

        menu = f"""
{_c('╭─ Download Controls ──────────────────────────────╮', ACCENT)}
{_c('│', ACCENT)}  {_c('[+/-]', YELLOW)} Speed: {speed}% of {max_mbps} Mbps     {_c('[w/W]', YELLOW)} Threads: {workers}  {_c('│', ACCENT)}
{_c('│', ACCENT)}  {_c('[s/S]', YELLOW)} Speed: 25/50/75/100%  {_c('[t/T]', YELLOW)} Threads: 1/2/4/8    {_c('│', ACCENT)}
{_c('│', ACCENT)}  {_c('[m]', YELLOW)} Hide menu    {_c('[q]', RED)} Quit (graceful)              {_c('│', ACCENT)}
{_c('╰────────────────────────────────────────────────────╯', ACCENT)}
"""
        sys.stdout.write(menu)
        sys.stdout.flush()

    def _handle_menu_key(self, ch: str):
        changed = False
        if ch == '+':
            self.speed_percent_ref[0] = min(100, self.speed_percent_ref[0] + 5)
            changed = True
        elif ch == '-':
            self.speed_percent_ref[0] = max(0, self.speed_percent_ref[0] - 5)
            changed = True
        elif ch.lower() == 's':
            # Cycle through presets
            presets = [25, 50, 75, 100]
            current = self.speed_percent_ref[0]
            idx = presets.index(current) if current in presets else 0
            self.speed_percent_ref[0] = presets[(idx + 1) % len(presets)]
            changed = True
        elif ch.lower() == 't':
            # Cycle thread presets
            presets = [1, 2, 4, 8]
            current = self.max_workers_ref[0]
            idx = presets.index(current) if current in presets else 0
            self.max_workers_ref[0] = presets[(idx + 1) % len(presets)]
            changed = True
        elif ch == 'w':
            self.max_workers_ref[0] = min(16, self.max_workers_ref[0] + 1)
            changed = True
        elif ch == 'W':
            self.max_workers_ref[0] = max(1, self.max_workers_ref[0] - 1)
            changed = True

        if changed and self.limiter:
            self.limiter.update_speed(self.speed_percent_ref[0], self.max_speed_mbps)
            self._clear_menu()
            self._draw_menu()


def create_control_panel(bandwidth_limiter, max_workers: int, speed_percent: int, max_speed_mbps: float = 100.0):
    """Create and start the download control panel."""
    # Use mutable lists as references for thread-safe updates
    workers_ref = [max_workers]
    speed_ref = [speed_percent]
    panel = DownloadControlPanel(bandwidth_limiter, workers_ref, speed_ref, max_speed_mbps)
    panel.start()
    return panel, workers_ref, speed_ref