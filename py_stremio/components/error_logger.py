"""Persistent error logging — delegates to the deduplicating ErrorReporter.

This module maintains backward compatibility with the existing
``from ..error_logger import log_error`` imports used across the codebase.
All new code should import from ``py_stremio.components.errors`` instead::

    from py_stremio.components.errors import report_error, print_error_summary

    report_error(context="try_addon(torrentio)", exception=exc, url=addon_url)

The old ``log_error(context, exception, details)`` function is kept as an
alias that funnels through the same deduplication system.

To append to the persistent errors.md file (legacy behaviour), call
``log_error_to_file(context, exception, details)`` explicitly.
"""

from datetime import datetime
from pathlib import Path
import sys
import traceback

from .errors import report_error, print_error_summary

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ERROR_LOG = PROJECT_ROOT / "errors.md"

_LOCK_AVAILABLE = True
try:
    import threading

    _lock = threading.Lock()
except ImportError:
    _LOCK_AVAILABLE = False


def log_error(context: str, exception: BaseException | None = None, details: str = "") -> None:
    """Log an error through the deduplicating ErrorReporter.

    This is the backward-compatible alias for the old ``log_error()``.
    Instead of printing full tracebacks each time, it delegates to the
    ``ErrorReporter`` which groups duplicates and prints a summary at the
    end of the run.

    Args:
        context: Short description of where the error occurred (e.g. ``"try_addon(torrentio)"``).
        exception: The exception that was caught.
        details: Optional URL or detail string associated with the error.
    """
    if exception is not None:
        report_error(context=context, exception=exception, url=details)
    else:
        # If no exception passed but we're in an except block
        exc_info = sys.exc_info()
        if exc_info[1] is not None:
            report_error(context=context, exception=exc_info[1], url=details)


def log_error_to_file(context: str, exception: BaseException | None = None, details: str = "") -> None:
    """Append a structured error entry to errors.md (legacy file logging).

    This preserves the old behaviour of writing to errors.md for persistent
    debugging. Most callers should use ``log_error()`` instead, which
    funnels through the deduplicating system.

    Args:
        context: Short description of where the error occurred.
        exception: The exception that was caught (optional).
        details: Optional human-readable detail string.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exc_info = sys.exc_info()
    tb_text = ""
    if exception is not None:
        tb_text = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
    elif exc_info[0] is not None:
        tb_text = "".join(traceback.format_exception(*exc_info))

    entry_parts = [f"## {timestamp} — {context}", ""]
    if details:
        entry_parts.append(f"**Details:** {details}")
        entry_parts.append("")
    if tb_text:
        entry_parts.append("```")
        entry_parts.append(tb_text.rstrip("\n"))
        entry_parts.append("```")
        entry_parts.append("")

    entry = "\n".join(entry_parts)

    if _LOCK_AVAILABLE:
        with _lock:
            _append_entry(entry)
    else:
        _append_entry(entry)


def _append_entry(entry: str) -> None:
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        pass  # don't crash if we can't write the error log


__all__ = [
    "log_error",
    "log_error_to_file",
    "print_error_summary",
    "report_error",
]
