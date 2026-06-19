"""Interactive download controls — fixed-position bottom overlay for speed/thread adjustments."""
import sys
import threading
import time
import shutil
from typing import Optional

from py_stremio.services.progress import ACCENT, GREEN, YELLOW, RED, DIM, RESET


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


class DownloadControlPanel:
    """Fixed-position control panel at bottom of terminal."""

    def __init__(
        self,
        bandwidth_limiter,
        max_workers_ref: list[int],
        speed_percent_ref: list[int],
        max_speed_mbps: float = 100.0,
        progress_line_count: int = 0,
    ):
        self.limiter = bandwidth_limiter
        self.max_workers_ref = max_workers_ref
        self.speed_percent_ref = speed_percent_ref
        self.max_speed_mbps = max_speed_mbps
        self.progress_line_count = progress_line_count
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._visible = False
        self._lock = threading.Lock()
        self._panel_height = 5  # Height of panel in lines

    def update_progress_lines(self, count: int):
        """Update the number of progress lines above the panel."""
        self.progress_line_count = count

    def start(self):
        """Start the key listener thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the key listener thread and clear panel."""
        self._running = False
        if self._visible:
            self._hide()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _listen_loop(self):
        """Listen for key presses (non-blocking)."""
        import termios
        import tty

        fd = None
        old_settings = None
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            while self._running:
                if sys.stdin in __import__('select').select([sys.stdin], [], [], 0.1)[0]:
                    ch = sys.stdin.read(1)
                    if ch:
                        self._handle_key(ch)
                time.sleep(0.05)
        except (OSError, IOError):
            # stdin not a TTY (e.g., tests) - run without key listener
            pass
        finally:
            if fd is not None and old_settings is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except (OSError, IOError):
                    pass

    def _handle_key(self, ch: str):
        """Handle key press."""
        if ch.lower() == 'm':
            self._toggle()
        elif ch.lower() == 'q':
            from py_stremio.utils.cancellation import request_shutdown
            request_shutdown()
        elif self._visible:
            self._handle_menu_key(ch)

    def _toggle(self):
        with self._lock:
            if self._visible:
                self._hide()
            else:
                self._show()

    def _get_panel_position(self) -> int:
        """Calculate the row where panel should start (1-indexed)."""
        term_height = shutil.get_terminal_size(fallback=(100, 24)).lines
        return max(1, term_height - self._panel_height - self.progress_line_count)

    def _show(self):
        """Draw panel at fixed bottom position."""
        if self._visible:
            return
        self._visible = True
        self._draw()

    def _hide(self):
        """Clear panel area."""
        if not self._visible:
            return
        row = self._get_panel_position()
        # Move to panel start and clear lines
        sys.stdout.write(f"\033[{row};1H")  # Move to panel row
        for _ in range(self._panel_height):
            sys.stdout.write("\033[2K")  # Clear line
            sys.stdout.write("\033[1B")  # Move down
        sys.stdout.write(f"\033[{row};1H")  # Move back to panel row
        sys.stdout.flush()
        self._visible = False

    def _draw(self):
        """Draw the panel at bottom of terminal."""
        if not self._visible:
            return

        row = self._get_panel_position()
        speed = self.speed_percent_ref[0]
        workers = self.max_workers_ref[0]
        max_mbps = self.max_speed_mbps

        # Color for speed indicator
        if speed == 0:
            speed_color = RED
        elif speed <= 25:
            speed_color = YELLOW
        elif speed <= 75:
            speed_color = ACCENT
        else:
            speed_color = GREEN

        panel = f"""{_c('╭─ Download Controls ──────────────────────────────╮', ACCENT)}
{_c('│', ACCENT)}  {_c('[+/-]', YELLOW)} Speed: {_c(f'{speed}%', speed_color)} of {_c(f'{max_mbps:.0f} Mbps', ACCENT)}     {_c('[w/W]', YELLOW)} Threads: {_c(str(workers), ACCENT)}  {_c('│', ACCENT)}
{_c('│', ACCENT)}  {_c('[s/S]', YELLOW)} Speed: 25/50/75/100%  {_c('[t/T]', YELLOW)} Threads: 1/2/4/8    {_c('│', ACCENT)}
{_c('│', ACCENT)}  {_c('[m]', YELLOW)} Hide  {_c('[q]', RED)} Quit gracefully  {_c('│', ACCENT)}
{_c('╰────────────────────────────────────────────────────╯', ACCENT)}"""

        # Save cursor, move to panel position, draw, restore cursor
        sys.stdout.write("\033[s")  # Save cursor position
        sys.stdout.write(f"\033[{row};1H")  # Move to panel row
        sys.stdout.write(panel)
        sys.stdout.write("\033[u")  # Restore cursor position
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
            presets = [25, 50, 75, 100]
            current = self.speed_percent_ref[0]
            idx = presets.index(current) if current in presets else 0
            self.speed_percent_ref[0] = presets[(idx + 1) % len(presets)]
            changed = True
        elif ch.lower() == 't':
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
            # Calculate total bytes per second from percentage
            clamped = max(0, min(100, self.speed_percent_ref[0]))
            if clamped >= 100 or self.max_speed_mbps <= 0:
                total_bps = 0
            else:
                total_bps = max(1, int((self.max_speed_mbps * 1_000_000 / 8) * (clamped / 100)))
            
            # Use new FairBandwidthLimiter method if available, else fallback
            if hasattr(self.limiter, 'update_total_limit'):
                self.limiter.update_total_limit(total_bps)
            elif hasattr(self.limiter, 'update_speed'):
                self.limiter.update_speed(self.speed_percent_ref[0], self.max_speed_mbps)
            
            self._draw()  # Redraw with new values

    def refresh(self):
        """Refresh panel display (call when terminal resizes or progress lines change)."""
        if self._visible:
            self._draw()


def create_control_panel(bandwidth_limiter, max_workers: int, speed_percent: int, max_speed_mbps: float = 100.0, progress_line_count: int = 0):
    """Create and start the download control panel."""
    workers_ref = [max_workers]
    speed_ref = [speed_percent]
    panel = DownloadControlPanel(bandwidth_limiter, workers_ref, speed_ref, max_speed_mbps, progress_line_count)
    panel.start()
    return panel, workers_ref, speed_ref