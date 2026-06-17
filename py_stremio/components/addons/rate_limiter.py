"""Per-host rate limiter to prevent 429 Too Many Requests.

Guarantees only ONE request at a time to any given host by holding a
per-host **threading lock** for the **entire** HTTP request duration.
A minimum gap (``MIN_GAP`` seconds) is enforced between consecutive
requests to the same host.

Unlike a naive ``wait_if_needed()`` that releases the lock before the
actual HTTP call, this design keeps the lock acquired across the full
request — so two threads can *never* fire overlapping requests to the
same host.

Requests to *different hosts* run in parallel (no shared bottleneck),
which is safe since different services have independent rate limits.

Usage::

    with limiter.request("https://torrentio.strem.fun/..."):
        resp = session.get(url, ...)
    # Optional: limiter.report_429(url) / report_success(url)
    # inside the ``with`` block (lock already held).
"""

from contextlib import contextmanager
import os
import threading
import time
from typing import Generator
from urllib.parse import urlparse

# ── Tunables ──────────────────────────────────────────────────────────────────

MIN_GAP = 2.0           # minimum seconds between requests to the same host
COOLDOWN_BASE = 60      # seconds to ban a host after a 429
_MAX_COOLDOWN = 3600    # 1 hour cap
_MAX_REQUESTS_PER_HOST = 50  # max requests per host per RateLimiter lifetime

# Disable delays when running under pytest (set PY_STREMIO_RATE_LIMIT=0)
_DISABLE_DELAYS = os.environ.get("PY_STREMIO_RATE_LIMIT") == "0"


# ── Inner state ───────────────────────────────────────────────────────────────

class _HostState:
    """Mutable state for one host.  Guarded by ``lock``."""

    __slots__ = (
        "lock", "last_request", "cooldown_until",
        "consecutive_429s", "request_count",
    )

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.last_request: float = 0.0
        self.cooldown_until: float = 0.0
        self.consecutive_429s: int = 0
        self.request_count: int = 0


# ── Singleton ─────────────────────────────────────────────────────────────────

class RateLimiter:
    """Per-host rate limiter + global concurrency throttle.

    Thread-safe singleton.  Use ``get_instance()`` or the module-level
    ``get_rate_limiter()`` to access.
    """

    _instance: "RateLimiter | None" = None
    _registry_lock: threading.Lock
    _hosts: dict[str, _HostState]

    def __new__(cls) -> "RateLimiter":
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._registry_lock = threading.Lock()
            obj._hosts = {}
            cls._instance = obj
        return cls._instance

    @classmethod
    def get_instance(cls) -> "RateLimiter":
        return cls()

    # ── Public API ────────────────────────────────────────────────────────────

    @contextmanager
    def request(self, url: str) -> Generator[str, None, None]:
        """Block until safe to make a request to *url*, then yield with the
        per-host lock held.

        The per-host lock is held for the **entire** duration of the
        ``with`` block — guaranteeing no other thread can make a
        concurrent request to the same host.
        """
        host = _extract_host(url)
        if not host:
            yield url
            return

        state = self._get_state(host)

        # Per-host lock — serialises requests to this host.
        # Held for the ENTIRE HTTP request so no overlapping requests
        # to the same host are possible.
        with state.lock:
            # Per-session request cap — prevent runaway queries to one host
            if _MAX_REQUESTS_PER_HOST > 0 and state.request_count >= _MAX_REQUESTS_PER_HOST:
                raise RuntimeError(
                    f"Rate limit cap reached: {host} — "
                    f"{state.request_count} requests (max {_MAX_REQUESTS_PER_HOST})"
                )
            state.request_count += 1

            if not _DISABLE_DELAYS:
                now = time.monotonic()

                # a) 429 cooldown — exponential back-off
                if state.cooldown_until > now:
                    wait = state.cooldown_until - now
                    time.sleep(wait)
                    now = time.monotonic()

                # b) Minimum gap since last request to this host
                if state.last_request > 0:
                    gap = MIN_GAP - (now - state.last_request)
                    if gap > 0:
                        time.sleep(gap)

            state.last_request = time.monotonic()

            # Yield — caller makes the HTTP request with the lock held
            yield url

    def report_429(self, url: str) -> None:
        """Register that *url*'s host returned HTTP 429.

        Extends the cooldown period exponentially on consecutive 429s.
        Safe to call from inside or outside a ``with limiter.request():``
        block.
        """
        host = _extract_host(url)
        if not host:
            return
        state = self._get_state(host)
        now = time.monotonic()
        with state.lock:
            state.consecutive_429s += 1
            exponent = state.consecutive_429s - 1
            cooldown = min(COOLDOWN_BASE * (2 ** exponent), _MAX_COOLDOWN)
            state.cooldown_until = now + cooldown
            state.last_request = now

    def report_success(self, url: str) -> None:
        """Reset the consecutive-429 counter for *url*'s host."""
        host = _extract_host(url)
        if not host:
            return
        state = self._hosts.get(host)
        if state is None:
            return
        with state.lock:
            state.consecutive_429s = 0

    def get_cooldown_seconds(self, url: str) -> float:
        """Seconds remaining before *url*'s host can be queried (0 = ready)."""
        host = _extract_host(url)
        if not host:
            return 0.0
        state = self._hosts.get(host)
        if state is None:
            return 0.0
        remaining = state.cooldown_until - time.monotonic()
        return max(0.0, remaining)

    def is_banned(self, url: str) -> bool:
        return self.get_cooldown_seconds(url) > 0

    def reset_host(self, url: str) -> None:
        """Remove all state for *url*'s host."""
        host = _extract_host(url)
        if host and host in self._hosts:
            with self._registry_lock:
                if host in self._hosts:
                    del self._hosts[host]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_state(self, host: str) -> _HostState:
        with self._registry_lock:
            if host not in self._hosts:
                self._hosts[host] = _HostState()
            return self._hosts[host]


def _extract_host(url: str) -> str:
    """Extract lowercased hostname from a URL."""
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or parsed.hostname or "").lower()
        if ":" in host:
            host = host.split(":")[0]
        return host
    except Exception:
        return ""


# ── Module-level convenience accessor ─────────────────────────────────────────

_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter.get_instance()
    return _rate_limiter
