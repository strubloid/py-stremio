"""Thread-aware terminal output helpers."""
import contextlib
import sys
import threading
from typing import Iterator, TextIO


_quiet_thread_ids: set[int] = set()
_quiet_lock = threading.Lock()
_proxy_lock = threading.Lock()


class ThreadFilteringStdout:
    """Forward stdout except for threads explicitly marked as quiet."""

    def __init__(self, target: TextIO):
        self.target = target

    def write(self, text: str) -> int:
        with _quiet_lock:
            quiet = threading.get_ident() in _quiet_thread_ids
        if quiet:
            return len(text)
        return self.target.write(text)

    def flush(self) -> None:
        return self.target.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.target, "isatty", lambda: False)())

    def __getattr__(self, name: str):
        return getattr(self.target, name)


@contextlib.contextmanager
def suppress_current_thread_output():
    """Suppress ordinary print() output from the current thread only."""
    thread_id = threading.get_ident()
    with _quiet_lock:
        _quiet_thread_ids.add(thread_id)
    try:
        yield
    finally:
        with _quiet_lock:
            _quiet_thread_ids.discard(thread_id)


def install_thread_stdout_filter() -> tuple[TextIO, TextIO | None]:
    """Install the stdout proxy and return (real_stream, original_to_restore)."""
    with _proxy_lock:
        current = sys.stdout
        if isinstance(current, ThreadFilteringStdout):
            return current.target, None
        sys.stdout = ThreadFilteringStdout(current)  # type: ignore[assignment]
        return current, current


def restore_thread_stdout_filter(original: TextIO | None) -> None:
    """Restore stdout if install_thread_stdout_filter installed it here."""
    if original is None:
        return
    with _proxy_lock:
        if isinstance(sys.stdout, ThreadFilteringStdout) and sys.stdout.target is original:
            sys.stdout = original


@contextlib.contextmanager
def thread_stdout_filter() -> Iterator[TextIO]:
    """Temporarily install a thread-aware stdout proxy.

    Yields the real terminal stream. Progress UI should write to that real stream
    so it stays visible even when downloader worker threads are marked quiet.
    """
    installed_here = False
    original = sys.stdout
    with _proxy_lock:
        current = sys.stdout
        if isinstance(current, ThreadFilteringStdout):
            real_stream = current.target
        else:
            real_stream = current
            sys.stdout = ThreadFilteringStdout(current)  # type: ignore[assignment]
            installed_here = True
    try:
        yield real_stream
    finally:
        if installed_here:
            with _proxy_lock:
                if isinstance(sys.stdout, ThreadFilteringStdout) and sys.stdout.target is original:
                    sys.stdout = original
