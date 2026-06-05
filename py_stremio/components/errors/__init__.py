"""Error reporting and deduplication system.

Usage:
    from py_stremio.components.errors import ErrorReporter, report_error

    # Report an error (replaces old log_error calls)
    report_error(context="try_addon(torrentio)", exception=exc, url=addon_url)

    # At the end of the run, print the grouped summary
    from py_stremio.components.errors import print_error_summary
    print_error_summary()

This module replaces the old error_logger.py with a deduplicating system
that groups repeated errors by category and tracks affected addons.
"""

from .error_category import ErrorCategory, normalize_error
from .error_entry import ErrorEntry
from .error_summary import ErrorSummary
from .error_reporter import ErrorReporter, report_error, print_error_summary, redact_url, error_count, reset_error_reporter

__all__ = [
    "ErrorCategory",
    "ErrorEntry",
    "ErrorSummary",
    "ErrorReporter",
    "report_error",
    "print_error_summary",
    "redact_url",
    "normalize_error",
    "error_count",
    "reset_error_reporter",
]
