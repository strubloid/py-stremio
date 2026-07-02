"""HTTP client for addon queries with Cloudflare bypass support.

Uses ``httpx`` as the primary transport because its per-call timeouts are
reliable for Stremio addon endpoints. Falls back to ``tls_client`` and then
``cloudscraper`` when ``httpx`` is not installed.

The client session is created once and reused across all queries to
maintain session cookies and browser fingerprint.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── Transport selection ────────────────────────────────────────────────────

def _create_session():
    """Create the most capable HTTP session available.

    Priority order:
    1. ``httpx.Client`` — reliable per-request timeouts for addon endpoints.
    2. ``tls_client`` — real TLS fingerprint mimicking Chrome 120, but some
       versions can hang indefinitely despite a timeout kwarg.
    3. ``cloudscraper`` — browser emulation with JS challenge solving.
    4. Plain ``requests.Session`` (fallback).
    """
    try:
        import httpx

        session = httpx.Client(
            follow_redirects=True,
            headers={
                # NOTE: Stremio/4.4.168 UA is blocked by Cloudflare on many IPs.
                # Using a Chrome UA as a workaround until we implement proper
                # Cloudflare bypass (tls_client / cloudscraper) for httpx.
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        logger.debug("Using httpx session for addon queries")
        return session, "httpx"
    except ImportError:
        logger.debug("httpx not available, falling back to tls_client")

    try:
        import tls_client

        session = tls_client.Session(client_identifier="chrome_120")
        session.timeout_seconds = 15
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        logger.debug("Using tls_client session (Chrome 120 fingerprint)")
        return session, "tls_client"
    except ImportError:
        logger.debug("tls_client not available, falling back to cloudscraper")

    try:
        import cloudscraper

        session = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "desktop": True,
                "mobile": False,
            },
            interpreter="nodejs",
        )
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        logger.debug("Using cloudscraper session")
        return session, "cloudscraper"
    except ImportError:
        import requests

        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        logger.debug("Using plain requests.Session (no Cloudflare bypass)")
        return session, "requests"


_session, _backend = _create_session()

# tls_client and cloudscraper both support timeout_seconds as a session-level
# property.  Wrap their ``get()`` so we can pass timeout per-call too.
_ORIGINAL_GET = _session.get


def _patched_get(url, **kwargs):
    """Patched ``.get()`` that normalises timeout/redirect kwargs.

    httpx and requests/cloudscraper accept per-call timeouts. tls_client only
    supports a session-level ``timeout_seconds`` property, so keep it as the
    fallback-only special case.
    """
    timeout = kwargs.pop("timeout", None)
    if _backend == "httpx":
        allow_redirects = kwargs.pop("allow_redirects", None)
        if allow_redirects is not None:
            kwargs["follow_redirects"] = allow_redirects
        if timeout is not None:
            kwargs["timeout"] = timeout
    elif timeout is not None:
        try:
            _session.timeout_seconds = timeout
        except AttributeError:
            # requests/cloudscraper — pass to the underlying request
            kwargs["timeout"] = timeout
    return _ORIGINAL_GET(url, **kwargs)


_session.get = _patched_get  # type: ignore[method-assign]


# ── Public API ─────────────────────────────────────────────────────────────


class CloudscraperError(Exception):
    """Wrapper for transport errors that preserves the original exception."""


def addon_get(url: str, timeout: float = 10) -> dict:
    """Fetch an addon stream endpoint and return parsed JSON.

    Uses ``tls_client`` or ``cloudscraper`` to bypass Cloudflare challenges.
    Applies per-host rate limiting to prevent 429 Too Many Requests.
    The per-host lock is held for the entire HTTP request duration.

    Returns:
        Parsed JSON dict from the addon response.

    Raises:
        CloudscraperError: On any transport, status, or parse error.
            The original exception is accessible via ``__cause__``.
    """
    from requests.exceptions import RequestException, HTTPError

    from .rate_limiter import get_rate_limiter

    limiter = get_rate_limiter()

    with limiter.request(url):
        try:
            resp = _session.get(url, timeout=timeout, allow_redirects=True)

            # Update rate-limiter state based on response
            if resp.status_code == 429:
                limiter.report_429(url)
            elif resp.status_code is not None and resp.status_code < 400:
                limiter.report_success(url)

            _raise_for_status(resp)
            return resp.json()
        except RuntimeError as exc:
            # Per-host request cap reached
            raise CloudscraperError(str(exc)) from exc
        except RequestException as exc:
            raise CloudscraperError(str(exc)) from exc
        except ValueError as exc:
            raise CloudscraperError(f"Invalid JSON from {_short_url(url)}") from exc
        except Exception as exc:
            # tls_client raises TLSClientExeption for DNS/connection errors
            # (Go-style errors not subclassed from RequestException)
            raise CloudscraperError(str(exc)) from exc


def _raise_for_status(resp) -> None:
    """Raise :class:`requests.exceptions.HTTPError` if the response has an
    error status code.

    Works with ``requests.Response``, ``tls_client.Response``, and
    ``cloudscraper.Response`` (the latter two are transparent wrappers).
    """
    status = resp.status_code
    if 400 <= status < 600:
        from requests.exceptions import HTTPError

        # Coerce the URL to a plain string for the error message — httpx
        # responses expose ``httpx.URL`` which is not str-cooperative.
        url_str = str(resp.url) if resp.url else ""
        raise HTTPError(
            f"{status} Client/Server Error for url: {_short_url(url_str)}",
            response=resp,
        )


def addon_get_streams(
    url: str,
    timeout: float = 10,
    addon_name: str = "addon_client",
) -> list[dict]:
    """Fetch an addon stream endpoint and return the ``streams`` list.

    Thin wrapper around :func:`addon_get` that extracts the stream array.
    Returns an empty list on any error, logging the failure through the
    standard error reporter.

    Args:
        url: Full addon stream query URL.
        timeout: Request timeout in seconds.
        addon_name: Addon name for error context.

    Returns:
        List of raw stream dicts (may be empty).
    """
    try:
        data = addon_get(url, timeout=timeout)
        return data.get("streams", [])
    except CloudscraperError as exc:
        from py_stremio.components.errors.error_logger import log_error

        log_error(f"fetch_streams({addon_name})", exception=exc, details=url)
        return []


def _short_url(url: str) -> str:
    """Return a short human-readable URL fragment for error messages."""
    # httpx.Response.url is an httpx.URL object which lacks ``.decode()``
    # required by ``urllib.parse.urlparse``'s coercion logic.  Coerce
    # to a plain string up front so error messages never crash on URL
    # type differences between backends.
    url_str = str(url) if url else ""
    parsed = urlparse(url_str)
    path = parsed.path.rstrip("/")
    # Show first 60 chars of path starting from meaningful segment
    segments = [s for s in path.split("/") if s and not s.startswith("realdebrid") and not s.startswith("eyJ")]
    if segments:
        key = segments[-1] if len(segments) <= 3 else "/".join(segments[-3:])
        if len(key) > 50:
            key = key[:20] + "..." + key[-10:]
        return f"{parsed.netloc}/.../{key}"
    return parsed.netloc
