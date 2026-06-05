"""Tests for the error deduplication and reporting system.

These tests verify that the ErrorReporter correctly:
- Groups duplicate errors by category
- Separates different error categories
- Tracks affected addon names
- Redacts sensitive URLs
- Prints grouped summaries
- Handles debug mode with full tracebacks
"""

import json
import re
import traceback
from unittest.mock import patch

import httpx
import pytest

from py_stremio.components.errors import (
    ErrorCategory,
    ErrorEntry,
    ErrorReporter,
    ErrorSummary,
    normalize_error,
    print_error_summary,
    redact_url,
    report_error,
    reset_error_reporter,
)
from py_stremio.components.error_logger import log_error
from py_stremio.components.stream_downloads import InvalidVideoDownloadError


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_reporter():
    """Reset the ErrorReporter singleton before each test."""
    reset_error_reporter()
    yield
    reset_error_reporter()


def make_httpx_error(status_code: int, url: str = "https://torrentio.strem.fun/stream/series/tt1234567:1:1.json") -> httpx.HTTPStatusError:
    """Create a mock httpx HTTPStatusError with the given status code."""
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(
        f"Client error '{status_code}' for url",
        request=request,
        response=response,
    )


def make_dns_error(host: str = "example.com") -> httpx.ConnectError:
    """Create a mock DNS resolution error."""
    request = httpx.Request("GET", f"https://{host}/")
    return httpx.ConnectError(
        f"Connection error: [Errno -2] Name or service not known for {host}",
        request=request,
    )


def make_timeout_error(url: str = "https://torrentio.strem.fun/") -> httpx.TimeoutException:
    """Create a mock timeout error."""
    request = httpx.Request("GET", url)
    return httpx.TimeoutException(
        "Read timed out. (read timeout=10)",
        request=request,
    )


def make_json_decode_error(url: str = "https://example.com/stream.json", body: str = "not json") -> Exception:
    """Create a mock JSON decode error wrapper."""
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        return exc


def make_invalid_video_error(size: int = 419051, min_size: int = 104857600) -> InvalidVideoDownloadError:
    """Create a mock invalid video size error."""
    return InvalidVideoDownloadError(
        f"Resolved stream is only {size} bytes "
        f"(min {min_size} bytes for a complete video)"
    )


# ── Test: normalize_error ───────────────────────────────────────────────────


class TestNormalizeError:
    """Verify that normalize_error correctly classifies exceptions."""

    def test_http_404(self):
        exc = make_httpx_error(404)
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.HTTP_404_NOT_FOUND
        assert metadata["status_code"] == 404

    def test_http_400(self):
        exc = make_httpx_error(400)
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.HTTP_400_BAD_REQUEST
        assert metadata["status_code"] == 400

    def test_http_403(self):
        exc = make_httpx_error(403)
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.HTTP_403_FORBIDDEN
        assert metadata["status_code"] == 403

    def test_http_429(self):
        exc = make_httpx_error(429)
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.HTTP_429_TOO_MANY_REQUESTS
        assert metadata["status_code"] == 429

    def test_http_500(self):
        exc = make_httpx_error(500)
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.HTTP_500_INTERNAL_SERVER_ERROR
        assert metadata["status_code"] == 500

    def test_http_302(self):
        exc = make_httpx_error(302)
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.HTTP_302_REDIRECT
        assert metadata["status_code"] == 302

    def test_dns_error(self):
        exc = make_dns_error()
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.CONNECTION_DNS_ERROR

    def test_timeout_error(self):
        exc = make_timeout_error()
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.READ_TIMEOUT

    def test_json_decode_error(self):
        exc = make_json_decode_error()
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.JSON_DECODE_ERROR

    def test_invalid_video_error(self):
        exc = make_invalid_video_error(size=419051, min_size=104857600)
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.INVALID_VIDEO_TOO_SMALL
        assert metadata["size_bytes"] == 419051
        assert metadata["min_bytes"] == 104857600

    def test_unknown_error(self):
        exc = RuntimeError("something completely unexpected")
        category, metadata = normalize_error(exc)
        assert category == ErrorCategory.UNKNOWN_ERROR


# ── Test: ErrorReporter ─────────────────────────────────────────────────────


class TestErrorReporter:
    """Verify the ErrorReporter singleton deduplicates correctly."""

    def test_single_error(self):
        reporter = ErrorReporter()
        exc = make_httpx_error(404)
        reporter.report(exception=exc, context="try_addon(torrentio)")
        assert reporter.summary().total_count == 1
        assert len(reporter.summary().entries) == 1

    def test_duplicate_404_errors_are_grouped(self):
        reporter = ErrorReporter()
        exc = make_httpx_error(404)

        # Report the same error type 3 times with different addon names
        reporter.report(exception=exc, context="try_addon(torrentio)")
        reporter.report(exception=exc, context="try_addon(podnapisi)")
        reporter.report(exception=exc, context="try_addon(trakt)")

        summary = reporter.summary()
        assert summary.total_count == 3
        assert len(summary.entries) == 1  # only one category

        entry = summary.entries[ErrorCategory.HTTP_404_NOT_FOUND.value]
        assert entry.count == 3
        assert "torrentio" in entry.addons
        assert "podnapisi" in entry.addons
        assert "trakt" in entry.addons

    def test_different_status_codes_are_separate_groups(self):
        reporter = ErrorReporter()
        reporter.report(exception=make_httpx_error(404), context="try_addon(torrentio)")
        reporter.report(exception=make_httpx_error(500), context="try_addon(comet)")
        reporter.report(exception=make_httpx_error(403), context="try_addon(hdhub)")

        summary = reporter.summary()
        assert summary.total_count == 3
        assert len(summary.entries) == 3
        assert ErrorCategory.HTTP_404_NOT_FOUND.value in summary.entries
        assert ErrorCategory.HTTP_500_INTERNAL_SERVER_ERROR.value in summary.entries
        assert ErrorCategory.HTTP_403_FORBIDDEN.value in summary.entries

    def test_invalid_video_errors_are_grouped(self):
        reporter = ErrorReporter()
        exc1 = make_invalid_video_error(size=419051)
        exc2 = make_invalid_video_error(size=512000)
        exc3 = make_invalid_video_error(size=8192)

        reporter.report(exception=exc1, context="invalid_video", url="https://example.com/stream1")
        reporter.report(exception=exc2, context="invalid_video", url="https://example.com/stream2")
        reporter.report(exception=exc3, context="invalid_video", url="https://example.com/stream3")

        summary = reporter.summary()
        assert summary.total_count == 3
        assert len(summary.entries) == 1
        entry = summary.entries[ErrorCategory.INVALID_VIDEO_TOO_SMALL.value]
        assert entry.count == 3

    def test_json_decode_errors_are_grouped(self):
        reporter = ErrorReporter()
        exc = make_json_decode_error()

        reporter.report(exception=exc, context="try_addon(torrentio)")
        reporter.report(exception=exc, context="try_addon(mediafusion)")
        reporter.report(exception=exc, context="try_addon(comet)")

        summary = reporter.summary()
        assert summary.total_count == 3
        assert len(summary.entries) == 1
        assert ErrorCategory.JSON_DECODE_ERROR.value in summary.entries

    def test_timeout_errors_are_grouped(self):
        reporter = ErrorReporter()
        exc = make_timeout_error()

        reporter.report(exception=exc, context="try_addon(knightcrawler)")
        reporter.report(exception=exc, context="try_addon(peerflix)")
        reporter.report(exception=exc, context="try_addon(nucleus)")

        summary = reporter.summary()
        assert summary.total_count == 3
        assert len(summary.entries) == 1
        assert ErrorCategory.READ_TIMEOUT.value in summary.entries

    def test_mixed_errors_are_separate(self):
        reporter = ErrorReporter()

        reporter.report(exception=make_httpx_error(404), context="try_addon(torrentio)")
        reporter.report(exception=make_timeout_error(), context="try_addon(comet)")
        reporter.report(exception=make_invalid_video_error(), context="invalid_video")
        reporter.report(exception=make_httpx_error(404), context="try_addon(podnapisi)")

        summary = reporter.summary()
        assert summary.total_count == 4
        assert len(summary.entries) == 3  # 404 x2, timeout x1, invalid video x1


# ── Test: report_error module-level helper ───────────────────────────────────


class TestReportErrorModule:
    """Verify the module-level report_error helper works like the class method."""

    def test_report_error_module_level(self):
        report_error(context="try_addon(torrentio)", exception=make_httpx_error(404))
        report_error(context="try_addon(podnapisi)", exception=make_httpx_error(404))

        from py_stremio.components.errors.error_reporter import _get_reporter
        reporter = _get_reporter()
        assert reporter.summary().total_count == 2

    def test_log_error_backward_compat(self):
        """The old log_error() should still work and funnel through ErrorReporter."""
        log_error("try_addon(torrentio)", make_httpx_error(404))
        log_error("try_addon(podnapisi)", make_httpx_error(404))

        from py_stremio.components.errors.error_reporter import _get_reporter
        reporter = _get_reporter()
        assert reporter.summary().total_count == 2


# ── Test: print_summary ─────────────────────────────────────────────────────


class TestPrintSummary:
    """Verify the printed summary output format."""

    def test_summary_format_no_errors(self, capsys):
        """With no errors, nothing is printed."""
        print_error_summary()
        captured = capsys.readouterr()
        assert captured.err == ""  # nothing on stderr

    def test_summary_format_with_errors(self, capsys):
        reporter = ErrorReporter()
        reporter.report(exception=make_httpx_error(404), context="try_addon(torrentio)")
        reporter.report(exception=make_httpx_error(404), context="try_addon(podnapisi)")
        reporter.report(exception=make_invalid_video_error(), context="invalid_video")

        print_error_summary()
        captured = capsys.readouterr()

        # Should contain the header
        assert "ERROR SUMMARY" in captured.err
        assert "3 total" in captured.err

        # Should contain the 404 category
        assert "404 Not Found" in captured.err
        assert "x2" in captured.err

        # Should contain the invalid video category
        assert "Invalid Video" in captured.err
        assert "x1" in captured.err

        # Should list affected addons
        assert "torrentio" in captured.err
        assert "podnapisi" in captured.err

    def test_debug_mode_shows_traceback(self, capsys):
        """In debug mode, full tracebacks should be printed."""
        reporter = ErrorReporter()
        reporter.report(exception=make_httpx_error(404), context="try_addon(torrentio)")

        print_error_summary(debug=True)
        captured = capsys.readouterr()

        # Should contain traceback text (file paths, exception type)
        assert "Traceback" in captured.err or "httpx.HTTPStatusError" in captured.err

    def test_normal_mode_hides_traceback(self, capsys):
        """In normal mode, tracebacks should NOT be printed."""
        reporter = ErrorReporter()
        reporter.report(exception=make_httpx_error(404), context="try_addon(torrentio)")

        print_error_summary(debug=False)
        captured = capsys.readouterr()

        # Should NOT contain traceback text
        assert "Traceback" not in captured.err


# ── Test: URL redaction ─────────────────────────────────────────────────────


class TestRedactUrl:
    """Verify sensitive URL parts are redacted before logging."""

    def test_redact_realdebrid_query_param(self):
        url = "https://torrentio.strem.fun/realdebrid=abc123def456"
        redacted = redact_url(url)
        assert "abc123def456" not in redacted
        assert "***REDACTED***" in redacted

    def test_redact_apikey_param(self):
        url = "https://example.com/stream?apikey=secret123&other=value"
        redacted = redact_url(url)
        assert "secret123" not in redacted
        assert "***REDACTED***" in redacted
        assert "other=value" in redacted

    def test_redact_token_param(self):
        url = "https://example.com/stream?token=mysecrettoken"
        redacted = redact_url(url)
        assert "mysecrettoken" not in redacted
        assert "***REDACTED***" in redacted

    def test_redact_path_realdebrid(self):
        url = "https://torrentio.strem.fun/resolve/realdebrid/abc123def/stream.mkv"
        redacted = redact_url(url)
        assert "abc123def" not in redacted
        assert "***REDACTED***" in redacted

    def test_redact_path_apikey(self):
        url = "https://example.com/api/apikey/secretvalue/data"
        redacted = redact_url(url)
        assert "secretvalue" not in redacted

    def test_none_url(self):
        assert redact_url(None) == ""

    def test_clean_url_unchanged(self):
        url = "https://torrentio.strem.fun/stream/series/tt0944947:1:1.json"
        redacted = redact_url(url)
        assert redacted == url

    def test_long_url_truncated(self):
        long_url = "https://example.com/" + "a" * 200 + "?key=value"
        redacted = redact_url(long_url, max_length=60)
        assert len(redacted) <= 63  # 60 + "..."

    def test_redact_password_param(self):
        url = "https://example.com/stream?password=supersecret&tracking=true"
        redacted = redact_url(url)
        assert "supersecret" not in redacted
        assert "***REDACTED***" in redacted
        assert "tracking=true" in redacted
    
    def test_redact_rd_param(self):
        url = "https://example.com/stream?rd=abc123&foo=bar"
        redacted = redact_url(url)
        assert "abc123" not in redacted
        assert "***REDACTED***" in redacted


# ── Test: ErrorEntry ────────────────────────────────────────────────────────


class TestErrorEntry:
    """Verify ErrorEntry merge and display properties."""

    def test_merge_increases_count(self):
        entry = ErrorEntry(category=ErrorCategory.HTTP_404_NOT_FOUND)
        assert entry.count == 1
        entry.merge("torrentio")
        assert entry.count == 2
        assert "torrentio" in entry.addons

    def test_merge_deduplicates_addons(self):
        entry = ErrorEntry(category=ErrorCategory.HTTP_404_NOT_FOUND)
        entry.merge("torrentio")
        entry.merge("torrentio")
        assert entry.count == 3
        assert len(entry.addons) == 1

    def test_sorted_addons(self):
        entry = ErrorEntry(category=ErrorCategory.HTTP_404_NOT_FOUND)
        entry.merge("zebra")
        entry.merge("alpha")
        entry.merge("Beta")
        assert entry.sorted_addons == ["alpha", "Beta", "zebra"]

    def test_size_info(self):
        entry = ErrorEntry(
            category=ErrorCategory.INVALID_VIDEO_TOO_SMALL,
            metadata={"size_bytes": 419051, "min_bytes": 104857600},
        )
        assert "419051" in entry.size_info
        assert "104857600" in entry.size_info
        assert "only" in entry.size_info
        assert "minimum" in entry.size_info


# ── Test: ErrorSummary ────────────────────────────────────────────────────


class TestErrorSummary:
    """Verify ErrorSummary aggregation."""

    def test_add_entry(self):
        summary = ErrorSummary()
        entry = ErrorEntry(category=ErrorCategory.HTTP_404_NOT_FOUND, count=3)
        summary.add_entry(entry)
        assert summary.total_count == 3
        assert len(summary.entries) == 1

    def test_merge_duplicate_category(self):
        summary = ErrorSummary()
        e1 = ErrorEntry(
            category=ErrorCategory.HTTP_404_NOT_FOUND,
            count=2,
            addons={"torrentio", "podnapisi"},
        )
        e2 = ErrorEntry(
            category=ErrorCategory.HTTP_404_NOT_FOUND,
            count=1,
            addons={"trakt"},
        )
        summary.add_entry(e1)
        summary.add_entry(e2)
        assert summary.total_count == 3
        entry = summary.entries[ErrorCategory.HTTP_404_NOT_FOUND.value]
        assert entry.count == 3
        assert "trakt" in entry.addons

    def test_clear(self):
        summary = ErrorSummary()
        summary.add_entry(ErrorEntry(category=ErrorCategory.HTTP_404_NOT_FOUND))
        summary.clear()
        assert summary.total_count == 0
        assert len(summary.entries) == 0

    def test_sorted_entries_by_count(self):
        summary = ErrorSummary()
        summary.add_entry(ErrorEntry(category=ErrorCategory.HTTP_404_NOT_FOUND, count=5))
        summary.add_entry(ErrorEntry(category=ErrorCategory.READ_TIMEOUT, count=10))
        summary.add_entry(ErrorEntry(category=ErrorCategory.JSON_DECODE_ERROR, count=2))
        sorted_ = summary.sorted_entries
        assert sorted_[0].count == 10  # highest first
        assert sorted_[1].count == 5
        assert sorted_[2].count == 2

    def test_has_errors(self):
        summary = ErrorSummary()
        assert not summary.has_errors
        summary.add_entry(ErrorEntry(category=ErrorCategory.HTTP_404_NOT_FOUND))
        assert summary.has_errors


# ── Test: redact_url in ErrorReporter.report ────────────────────────────────


class TestUrlRedactionInErrorReporter:
    """Verify that URLs are redacted when stored in the ErrorReporter."""

    def test_sensitive_url_is_redacted_in_reporter(self):
        reporter = ErrorReporter()
        sensitive_url = "https://torrentio.strem.fun/realdebrid=abc123def"
        reporter.report(
            exception=make_httpx_error(404, url=sensitive_url),
            context="try_addon(torrentio)",
            url=sensitive_url,
        )
        entry = reporter.summary().entries[ErrorCategory.HTTP_404_NOT_FOUND.value]
        # The stored URL should be redacted
        assert "abc123def" not in entry.metadata.get("url", "")
        assert "***REDACTED***" in entry.metadata.get("url", "")
