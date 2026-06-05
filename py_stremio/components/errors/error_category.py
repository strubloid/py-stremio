"""Error categorization — converts raw exceptions into stable categories."""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any

import httpx

from py_stremio.components.download.stream_download import InvalidVideoDownloadError


class ErrorCategory(str, Enum):
    """Stable error categories for deduplication and reporting."""

    HTTP_404_NOT_FOUND = "404 Not Found"
    HTTP_400_BAD_REQUEST = "400 Bad Request"
    HTTP_403_FORBIDDEN = "403 Forbidden"
    HTTP_429_TOO_MANY_REQUESTS = "429 Too Many Requests"
    HTTP_500_INTERNAL_SERVER_ERROR = "500 Internal Server Error"
    HTTP_302_REDIRECT = "302 Redirect"
    CONNECTION_DNS_ERROR = "DNS / Connection Error"
    READ_TIMEOUT = "Read Timeout"
    JSON_DECODE_ERROR = "JSON Decode Error"
    INVALID_VIDEO_TOO_SMALL = "Invalid Video"
    UNKNOWN_ERROR = "Unknown Error"

    @property
    def summary_line(self) -> str:
        """Return a human-readable one-line description of this category."""
        return _SUMMARY_LINES.get(self, "An error occurred during addon or stream processing.")


_SUMMARY_LINES: dict[ErrorCategory, str] = {
    ErrorCategory.HTTP_404_NOT_FOUND: "Addon endpoint does not support this stream path or media type.",
    ErrorCategory.HTTP_400_BAD_REQUEST: "Addon rejected the request as malformed.",
    ErrorCategory.HTTP_403_FORBIDDEN: "Addon returned access denied.",
    ErrorCategory.HTTP_429_TOO_MANY_REQUESTS: "Addon rate-limited the request.",
    ErrorCategory.HTTP_500_INTERNAL_SERVER_ERROR: "Addon returned an internal server error.",
    ErrorCategory.HTTP_302_REDIRECT: "Addon returned unexpected redirect.",
    ErrorCategory.CONNECTION_DNS_ERROR: "Addon host could not be reached — name or service not known.",
    ErrorCategory.READ_TIMEOUT: "Addon did not respond before the timeout.",
    ErrorCategory.JSON_DECODE_ERROR: "Addon returned empty or non-JSON response.",
    ErrorCategory.INVALID_VIDEO_TOO_SMALL: "Resolved stream is too small to be a complete video.",
    ErrorCategory.UNKNOWN_ERROR: "An unexpected error occurred.",
}

# Patterns to detect specific error messages in exception strings
_DNS_ERROR_PATTERNS = [
    re.compile(r"Name or service not known", re.IGNORECASE),
    re.compile(r"Temporary failure in name resolution", re.IGNORECASE),
    re.compile(r"No address associated with hostname", re.IGNORECASE),
    re.compile(r"getaddrinfo failed", re.IGNORECASE),
    re.compile(r"nodename nor servname provided", re.IGNORECASE),
    re.compile(r"cannot resolve", re.IGNORECASE),
]

_TIMEOUT_PATTERNS = [
    re.compile(r"tim(?:e|ei)out", re.IGNORECASE),
    re.compile(r"Read timed out", re.IGNORECASE),
    re.compile(r"Connect timeout", re.IGNORECASE),
]

_JSON_DECODE_CLASSES = (
    json.JSONDecodeError,
    json.decoder.JSONDecodeError,
)

# Minimum size below which an invalid-video message is considered too-small
# (parsed from the error text)
_MIN_SIZE_PATTERN = re.compile(r"only (\d+) bytes")
_MIN_MIN_BYTES_PATTERN = re.compile(r"min (\d+) bytes")


def _extract_http_status(exc: BaseException) -> int | None:
    """Extract HTTP status code from an exception, if applicable."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    if isinstance(exc, httpx.HTTPError):
        # e.g. httpx.HTTPError without .response
        return None
    # Check for wrapped httpx errors in the cause chain
    cause = exc.__cause__
    if cause is not None:
        return _extract_http_status(cause)
    # Also check __context__
    ctx = exc.__context__
    if ctx is not None:
        return _extract_http_status(ctx)
    return None


def _extract_url(exc: BaseException) -> str | None:
    """Extract URL from an httpx exception if available."""
    if isinstance(exc, httpx.RequestError):
        return str(exc.request.url) if exc.request else None
    if isinstance(exc, httpx.HTTPStatusError):
        return str(exc.request.url) if exc.request else None
    return None


def _extract_http_reason(exc: BaseException) -> str | None:
    """Extract the HTTP reason phrase from an exception."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.reason_phrase
    return None


def _extract_response_text(exc: BaseException) -> str | None:
    """Extract a short response text snippet from an HTTP error."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            text = exc.response.text[:200]
            return text
        except Exception:
            return None
    return None


def _is_dns_error(exc: BaseException) -> bool:
    """Check if an exception is a DNS / connection resolution error."""
    exc_str = str(exc)
    if isinstance(exc, httpx.ConnectError):
        for pattern in _DNS_ERROR_PATTERNS:
            if pattern.search(exc_str):
                return True
    return False


def _is_timeout_error(exc: BaseException) -> bool:
    """Check if an exception is a read/connect timeout."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    exc_str = str(exc)
    for pattern in _TIMEOUT_PATTERNS:
        if pattern.search(exc_str):
            return True
    return False


def _is_json_decode_error(exc: BaseException) -> bool:
    """Check if an exception is a JSON decode error."""
    if isinstance(exc, _JSON_DECODE_CLASSES):
        return True
    if isinstance(exc.__cause__, _JSON_DECODE_CLASSES):
        return True
    exc_str = str(exc)
    if "JSON" in exc_str and ("decode" in exc_str.lower() or "parse" in exc_str.lower()):
        return True
    return False


def _extract_invalid_video_details(exc: BaseException) -> dict[str, Any]:
    """Extract size details from an InvalidVideoDownloadError message."""
    details: dict[str, Any] = {}
    exc_str = str(exc)
    m = _MIN_SIZE_PATTERN.search(exc_str)
    if m:
        details["size_bytes"] = int(m.group(1))
    m = _MIN_MIN_BYTES_PATTERN.search(exc_str)
    if m:
        details["min_bytes"] = int(m.group(1))
    return details


def normalize_error(
    exception: BaseException,
    context: str = "",
    url: str | None = None,
) -> tuple[ErrorCategory, dict[str, Any]]:
    """Convert an exception into a stable (ErrorCategory, metadata) pair.

    Args:
        exception: The exception that was caught.
        context: Short description of where the error occurred
                 (e.g. ``"try_addon(podnapisi)"``).
        url: The URL or other identifying string associated with the error.

    Returns:
        A tuple of ``(ErrorCategory, metadata_dict)`` where metadata includes
        relevant extracted info like status code, size, etc.
    """
    metadata: dict[str, Any] = {}
    metadata["context"] = context
    metadata["url"] = url or ""

    # Check for HTTP status errors first (httpx raises these)
    status_code = _extract_http_status(exception)
    if status_code:
        metadata["status_code"] = status_code
        reason = _extract_http_reason(exception)
        if reason:
            metadata["reason"] = reason
        if status_code == 404:
            return ErrorCategory.HTTP_404_NOT_FOUND, metadata
        if status_code == 400:
            return ErrorCategory.HTTP_400_BAD_REQUEST, metadata
        if status_code == 403:
            return ErrorCategory.HTTP_403_FORBIDDEN, metadata
        if status_code == 429:
            return ErrorCategory.HTTP_429_TOO_MANY_REQUESTS, metadata
        if status_code == 500:
            return ErrorCategory.HTTP_500_INTERNAL_SERVER_ERROR, metadata
        if status_code == 302:
            return ErrorCategory.HTTP_302_REDIRECT, metadata

    # Check for InvalidVideoDownloadError (imported from stream_downloads)
    if isinstance(exception, InvalidVideoDownloadError):
        details = _extract_invalid_video_details(exception)
        metadata.update(details)
        return ErrorCategory.INVALID_VIDEO_TOO_SMALL, metadata

    # DNS errors
    if _is_dns_error(exception):
        return ErrorCategory.CONNECTION_DNS_ERROR, metadata

    # Timeout errors
    if _is_timeout_error(exception):
        return ErrorCategory.READ_TIMEOUT, metadata

    # JSON decode errors
    if _is_json_decode_error(exception):
        response_text = _extract_response_text(exception)
        if response_text:
            metadata["response_preview"] = response_text[:100]
        return ErrorCategory.JSON_DECODE_ERROR, metadata

    # Check if the exception string mentions HTTP status codes
    exc_str = str(exception)
    if isinstance(exception, httpx.HTTPError):
        status_code = _extract_http_status(exception)
        if status_code:
            metadata["status_code"] = status_code
            if status_code == 404:
                return ErrorCategory.HTTP_404_NOT_FOUND, metadata
            if status_code == 400:
                return ErrorCategory.HTTP_400_BAD_REQUEST, metadata
            if status_code == 403:
                return ErrorCategory.HTTP_403_FORBIDDEN, metadata
            if status_code == 429:
                return ErrorCategory.HTTP_429_TOO_MANY_REQUESTS, metadata
            if status_code == 500:
                return ErrorCategory.HTTP_500_INTERNAL_SERVER_ERROR, metadata

    return ErrorCategory.UNKNOWN_ERROR, metadata
