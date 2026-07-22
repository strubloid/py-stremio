"""Cross-platform single-keypress capture for interactive download controls.

When the download UI is running interactively, the user can press single
keys to adjust live settings (4K filter, worker count, speed limit). This
module hides the platform-specific raw-mode / non-blocking read logic
behind a small ``KeyboardControls`` facade.

Usage::

    controls = KeyboardControls()
    controls.on("b", lambda: toggle_4k())
    controls.on("+", lambda: bump_workers(+1))
    controls.start()
    try:
        ...  # long-running work
    finally:
        controls.stop()

The terminal is put into raw mode (Unix) or the console is set to no-echo
(Windows) for the lifetime of the controls so single keystrokes can be
read without waiting for Enter. ``Ctrl+C`` is left to the existing
``utils.cancellation`` cooperative shutdown so behaviour stays identical
to non-interactive runs.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Callable


def _is_windows() -> bool:
    return os.name == "nt"


class KeyboardControls:
    """Background reader that dispatches single keystrokes to handlers.

    The reader thread blocks on a single-byte read, so it must run in a
    dedicated thread — never call :meth:`read_key` from the main thread.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[], None]]] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._raw_active = False
        self._raw_state: tuple | None = None  # (termios_attrs) for restore
        self._supports_raw = self._detect_raw_support()

    @staticmethod
    def _detect_raw_support() -> bool:
        """Return True when the current stdin/stdout can be put in raw mode.

        Pipped stdin/stdout and CI environments that lack a controlling
        tty must NOT be put into raw mode — there is no terminal to talk
        to. The caller can still register handlers and call them via
        :meth:`dispatch` for tests.
        """
        try:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                return False
        except (ValueError, OSError):
            return False
        return True

    def on(self, key: str, handler: Callable[[], None]) -> None:
        """Register *handler* to be called when *key* is pressed.

        ``key`` is matched case-insensitively against the decoded
        single-character keystroke. ``Ctrl+C`` is reserved for the
        existing cooperative shutdown and is not honoured here.
        """
        if not key:
            return
        normalized = key.lower()
        with self._lock:
            self._handlers.setdefault(normalized, []).append(handler)

    def handlers_for(self, key: str) -> list[Callable[[], None]]:
        """Return the list of registered handlers for *key* (testing)."""
        with self._lock:
            return list(self._handlers.get(key.lower(), []))

    def dispatch(self, key: str) -> None:
        """Call all handlers registered for *key* (testing helper)."""
        normalized = key.lower()
        with self._lock:
            handlers = list(self._handlers.get(normalized, ()))
        for handler in handlers:
            try:
                handler()
            except Exception:
                # A buggy handler must not kill the reader thread; the
                # real interactive loop would silently ignore it too.
                continue

    def start(self) -> None:
        """Begin reading keystrokes in a background thread.

        No-op (and no thread spawned) when raw-mode is not supported,
        so the controls degrade gracefully on pipes and CI logs.
        """
        if self._thread is not None:
            return
        if not self._supports_raw:
            return
        self._enter_raw_mode()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._reader_loop, name="py-stremio-controls", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the reader thread and restore the terminal.

        Safe to call multiple times and from the same thread that
        called :meth:`start`.
        """
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join(timeout=1.0)
            self._thread = None
        self._exit_raw_mode()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internals ──────────────────────────────────────────────────────

    def _enter_raw_mode(self) -> None:
        if self._raw_active:
            return
        if _is_windows():
            try:
                import msvcrt  # type: ignore[import-not-found]
            except ImportError:
                return
            # msvcrt reads from the console directly; no mode flip needed
            # for individual key reads. Mark raw-active so stop() can
            # symmetrically tear down (currently a no-op on Windows).
            self._raw_active = True
            return
        try:
            import termios
            import tty
        except ImportError:
            return
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError):
            return
        try:
            attrs = termios.tcgetattr(fd)
        except termios.error:
            return
        self._raw_state = (termios, tty, attrs)
        try:
            tty.setcbreak(fd)
        except termios.error:
            self._raw_state = None
            return
        self._raw_active = True

    def _exit_raw_mode(self) -> None:
        if not self._raw_active:
            return
        if _is_windows():
            self._raw_active = False
            return
        if self._raw_state is None:
            self._raw_active = False
            return
        termios, _tty, attrs = self._raw_state
        self._raw_state = None
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, attrs)
        except (termios.error, OSError):
            pass
        self._raw_active = False

    def _reader_loop(self) -> None:
        if _is_windows():
            self._reader_loop_windows()
        else:
            self._reader_loop_unix()

    def _reader_loop_unix(self) -> None:
        try:
            import select
        except ImportError:
            return
        while not self._stop_event.is_set():
            try:
                rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            except (OSError, ValueError):
                return
            if not rlist:
                continue
            try:
                ch = os.read(sys.stdin.fileno(), 1)
            except OSError:
                return
            if not ch:
                continue
            decoded = ch.decode("utf-8", errors="ignore")
            if not decoded:
                continue
            if decoded == "\x03":
                # Ctrl+C — let the existing cooperative shutdown
                # handle it; don't dispatch it as a regular key.
                continue
            self.dispatch(decoded)

    def _reader_loop_windows(self) -> None:
        try:
            import msvcrt  # type: ignore[import-not-found]
        except ImportError:
            return
        while not self._stop_event.is_set():
            if not msvcrt.kbhit():
                # Cooperative sleep so the thread can react to stop_event
                # even when no key is pressed.
                self._stop_event.wait(timeout=0.1)
                continue
            try:
                ch = msvcrt.getwch()
            except OSError:
                return
            if not ch:
                continue
            if ch == "\x03":
                continue
            self.dispatch(ch)
