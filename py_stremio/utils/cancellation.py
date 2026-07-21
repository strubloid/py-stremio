"""Cooperative shutdown helpers for Ctrl+C handling."""
from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Iterable, Protocol


class _ExecutorLike(Protocol):
    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None: ...


_shutdown_requested = threading.Event()


class DownloadCancelled(KeyboardInterrupt):
    """Raised by cooperative checks while preserving resumable partial files."""


def raise_if_shutdown_requested() -> None:
    """Abort the current operation when cooperative shutdown was requested."""
    if _shutdown_requested.is_set():
        raise DownloadCancelled()


def request_shutdown() -> None:
    """Mark that the app is shutting down because the user interrupted it."""
    _shutdown_requested.set()


def clear_shutdown() -> None:
    """Reset shutdown state at the start of a new app run/test."""
    _shutdown_requested.clear()


def shutdown_requested() -> bool:
    """Return True after Ctrl+C has requested cooperative shutdown."""
    return _shutdown_requested.is_set()


def cancel_futures(futures: Iterable[Future]) -> None:
    """Cancel all pending futures, ignoring futures that are already running/done."""
    for future in futures:
        try:
            future.cancel()
        except Exception:
            pass


def shutdown_executor_now(executor: _ExecutorLike, futures: Iterable[Future]) -> None:
    """Cancel pending work and stop accepting new work without waiting for threads.

    Python cannot forcibly kill a thread that is currently inside a blocking HTTP or
    disk call, but this prevents queued work from starting and lets the main app
    return immediately. Running workers will finish/timeout in the background.
    """
    cancel_futures(futures)
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        # Python < 3.9 compatibility: cancel_futures was added in 3.9.
        executor.shutdown(wait=False)
