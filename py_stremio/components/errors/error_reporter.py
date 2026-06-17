"""ErrorReporter — singleton for deduplicated error tracking and reporting.

Usage::

    from py_stremio.components.errors import report_error, print_error_summary

    # Log errors as they happen (replaces old log_error())
    report_error(context="try_addon(torrentio)", exception=exc, url=addon_url)
    report_error(context="invalid_video", exception=exc, url=stream_url)

    # At the end of the run, print the grouped summary
    print_error_summary()
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from typing import Any

from .error_category import ErrorCategory, normalize_error
from .error_entry import ErrorEntry
from .error_summary import ErrorSummary

# ── URL redaction ──────────────────────────────────────────────────────────

# Query parameter keys to redact (case-insensitive)
_REDACT_PARAMS = {"apikey", "api_key", "apikey", "token", "realdebrid", "rd", "key", "password"}

# Path segments to redact — replace the whole match
_REDACT_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # (pattern, replacement) — uses plain string replacement, not group lookup
]

_PATH_REDACTIONS = [
    (re.compile(r"/realdebrid/[^/]+", re.IGNORECASE), "***REDACTED***"),
    (re.compile(r"/apikey/[^/]+", re.IGNORECASE), "***REDACTED***"),
    (re.compile(r"/token/[^/]+", re.IGNORECASE), "***REDACTED***"),
    (re.compile(r"/api_key/[^/]+", re.IGNORECASE), "***REDACTED***"),
    (re.compile(r"/password/[^/]+", re.IGNORECASE), "***REDACTED***"),
    # key=value in path segments (e.g. Torrentio path config)
    (re.compile(r"(realdebrid|rd|apikey|api_key|token|key|password)=[^/&]+", re.IGNORECASE), r"\1=***REDACTED***"),
]


def redact_url(url: str | None, max_length: int = 120) -> str:
    """Redact sensitive tokens and API keys from a URL.

    Masks query parameters and path segments that look like API keys
    (realdebrid, apikey, token, password, etc.).

    Args:
        url: The URL to redact.
        max_length: Maximum length before truncating (default: 120).

    Returns:
        The redacted (and optionally truncated) URL string.
    """
    if not url:
        return ""

    redacted = url

    # Redact query parameters
    if "?" in redacted:
        base, query_string = redacted.split("?", 1)
        params = query_string.split("&")
        redacted_params: list[str] = []
        for param in params:
            if "=" in param:
                key, value = param.split("=", 1)
                if key.lower() in _REDACT_PARAMS:
                    redacted_params.append(f"{key}=***REDACTED***")
                else:
                    redacted_params.append(param)
            else:
                redacted_params.append(param)
        redacted = f"{base}?{'&'.join(redacted_params)}"

    # Redact known path patterns (whole path segments)
    for pattern, replacement in _PATH_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)

    # Truncate long URLs
    if len(redacted) > max_length:
        redacted = redacted[:max_length] + "..."

    return redacted


def _parse_addon_name(context: str) -> str:
    """Extract the addon name from a context string like ``try_addon(podnapisi)``.

    Falls back to the first segment of the context if no parenthesised name
    is found.
    """
    m = re.search(r"\(([^)]+)\)", context)
    if m:
        return m.group(1).strip()
    parts = context.split("(", 1)
    return parts[0].strip()[:30]


# ── ErrorReporter ──────────────────────────────────────────────────────────


class ErrorReporter:
    """Singleton for deduplicated error tracking and reporting.

    Collects errors as they happen, groups them by category, and
    produces a clean summary at the end of a run.
    """

    _instance: ErrorReporter | None = None
    _debug: bool = False
    _summary: ErrorSummary
    _seen_tracebacks: set[str]

    def __new__(cls) -> ErrorReporter:
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._summary = ErrorSummary()
            obj._seen_tracebacks = set()
            cls._instance = obj
        return cls._instance

    @classmethod
    def get_instance(cls) -> ErrorReporter:
        """Get or create the singleton instance."""
        return cls()

    @classmethod
    def set_debug(cls, enabled: bool = True) -> None:
        """Enable debug mode, which prints full tracebacks for each error.

        In debug mode, every error is printed immediately with its full
        traceback instead of being deferred to the summary.
        """
        cls._debug = enabled

    @classmethod
    def is_debug(cls) -> bool:
        """Check if debug mode is enabled."""
        return cls._debug or bool(os.environ.get("PY_STREMIO_DEBUG", ""))

    def report(
        self,
        exception: BaseException,
        context: str = "",
        url: str | None = None,
    ) -> ErrorCategory:
        """Report an error for deduplication.

        Args:
            exception: The exception that was caught.
            context: Short description of where the error occurred
                     (e.g. ``"try_addon(podnapisi)"``).
            url: The URL or other identifier associated with the error
                 (will be redacted before storage).

        Returns:
            The ErrorCategory that was assigned.
        """
        category, metadata = normalize_error(exception, context=context, url=url)
        self._add_error(category, metadata, exception, context, url)
        return category

    def _add_error(
        self,
        category: ErrorCategory,
        metadata: dict[str, Any],
        exception: BaseException,
        context: str,
        url: str | None,
    ) -> None:
        """Add an error to the internal summary."""
        addon_name = _parse_addon_name(context)
        key = category.value

        if key not in self._summary.entries:
            # Capture the full traceback
            tb_text = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            )
            # Redact the URL in metadata
            redacted_url = redact_url(url)
            safe_metadata = dict(metadata)
            safe_metadata["url"] = redacted_url
            safe_metadata["context"] = context

            entry = ErrorEntry(
                category=category,
                metadata=safe_metadata,
                count=1,
                addons={addon_name} if addon_name else set(),
                traceback=tb_text,
            )
            self._summary.entries[key] = entry
            self._summary.total_count += 1
        else:
            self._summary.entries[key].merge(addon_name=addon_name)
            self._summary.total_count += 1  # <-- FIX: was missing
            if url:
                self._summary.entries[key].metadata["url"] = redact_url(url)

    def summary(self) -> ErrorSummary:
        """Return the current aggregated error summary."""
        return self._summary

    def print_summary(self, debug: bool | None = None) -> None:
        """Print the grouped error summary to stderr.

        Args:
            debug: If True, print full tracebacks for each error.
                   If False, print compact grouped output.
                   If None, use the instance's debug setting.
        """
        if not self._summary.has_errors:
            return

        show_debug = self.is_debug() if debug is None else debug

        entries = self._summary.sorted_entries
        total = self._summary.total_count

        # Print header
        print(file=sys.stderr)
        print("═" * 60, file=sys.stderr)
        print(f"  ERROR SUMMARY  ({total} total)", file=sys.stderr)
        print("═" * 60, file=sys.stderr)

        for entry in entries[:10]:  # max 10 categories shown
            # Single line: [category] xN — Reason  |  pods: a, b, c (+N)
            label = entry.short_label
            reason = entry.category.summary_line
            addon_info = ""
            addons_count = len(entry.sorted_addons)
            if addons_count > 0:
                names = ", ".join(sorted(entry.sorted_addons)[:6])
                if addons_count > 6:
                    names += f" (+{addons_count - 6})"
                addon_info = f"  |  pods: {names}"
            print(f"  {label} — {reason}{addon_info}", file=sys.stderr)
            # In debug mode, print the full traceback once per category
            if show_debug and entry.traceback:
                for line in entry.traceback.rstrip("\n").split("\n"):
                    print(f"    {line}", file=sys.stderr)

        hidden = len(entries) - 10
        if hidden > 0:
            print(f"  … and {hidden} more error categories ({total} shown)", file=sys.stderr)

        print(file=sys.stderr)
        print("═" * 60, file=sys.stderr)
        print(file=sys.stderr)

    def clear(self) -> None:
        """Reset all collected errors."""
        self._summary.clear()
        self._seen_tracebacks.clear()


# ── Module-level helpers (drop-in replacement for old log_error) ────────────

_reporter: ErrorReporter | None = None


def _get_reporter() -> ErrorReporter:
    global _reporter
    if _reporter is None:
        _reporter = ErrorReporter.get_instance()
    return _reporter


def report_error(
    context: str,
    exception: BaseException | None = None,
    url: str | None = None,
) -> None:
    """Report an error through the deduplicating system.

    This is the drop-in replacement for the old ``error_logger.log_error()``.

    Args:
        context: Short description of where the error occurred
                 (e.g. ``"try_addon(podnapisi)"``, ``"fetch_streams(Torrentio)"``).
        exception: The exception that was caught.
        url: The URL or other string associated with the error.
    """
    if exception is None:
        exc_info = sys.exc_info()
        if exc_info[1] is not None:
            exception = exc_info[1]
        else:
            return

    _get_reporter().report(exception=exception, context=context, url=url)


def print_error_summary(debug: bool | None = None) -> None:
    """Print the grouped error summary to stderr.

    Call this at the end of a run to show all deduplicated errors.

    Args:
        debug: If True, include full tracebacks. If None, use env/debug setting.
    """
    _get_reporter().print_summary(debug=debug)


def error_count() -> int:
    """Return the total number of error occurrences collected so far."""
    return _get_reporter().summary().total_count


def reset_error_reporter() -> None:
    """Reset the error reporter (useful in tests)."""
    global _reporter
    _reporter = None
    ErrorReporter._instance = None
