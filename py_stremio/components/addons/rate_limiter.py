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

The hard cap is **windowed** rather than lifetime: ``_MAX_REQUESTS_PER_HOST``
is the maximum number of requests in any rolling ``_WINDOW_SECONDS`` window.
Old timestamps are trimmed on every check, so the budget continuously
refills as the window slides forward. When the budget is exhausted the
caller sleeps until the oldest entry leaves the window — preferable to
failing the entire download. The cap can be disabled with
``PY_STREMIO_RATE_LIMIT_CAP=0`` for debugging.

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
from collections import deque
from typing import Generator
from urllib.parse import urlparse

# ── Tunables ──────────────────────────────────────────────────────────────────

MIN_GAP = 2.0           # minimum seconds between requests to the same host
COOLDOWN_BASE = 60      # seconds to ban a host after a 429
_MAX_COOLDOWN = 3600    # 1 hour cap

# Windowed per-host cap. The budget is a sliding count of requests in
# the last ``_WINDOW_SECONDS`` seconds — replaces the previous lifetime
# counter that would lock popular hosts out for the rest of the process.
_DEFAULT_MAX_REQUESTS_PER_HOST = 50
_DEFAULT_WINDOW_SECONDS = 300.0  # 5 minutes
_MAX_SLEEP_ON_CAP = 30.0  # never wait more than this when the cap blocks us


def _env_flag(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_MAX_REQUESTS_PER_HOST = _env_flag("PY_STREMIO_RATE_LIMIT_CAP", _DEFAULT_MAX_REQUESTS_PER_HOST)
_WINDOW_SECONDS = float(_env_flag("PY_STREMIO_RATE_LIMIT_WINDOW", int(_DEFAULT_WINDOW_SECONDS)))

# Disable delays when running under pytest (set PY_STREMIO_RATE_LIMIT=0)
_DISABLE_DELAYS = os.environ.get("PY_STREMIO_RATE_LIMIT") == "0"


# ── Inner state ───────────────────────────────────────────────────────────────

class _HostState:
    """Mutable state for one host.  Guarded by ``lock``."""

    __slots__ = (
        "lock", "last_request", "cooldown_until",
        "consecutive_429s", "request_count", "request_timestamps",
    )

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.last_request: float = 0.0
        self.cooldown_until: float = 0.0
        self.consecutive_429s: int = 0
        # Lifetime counter kept for diagnostics (visible in state dumps).
        self.request_count: int = 0
        # Sliding window of recent request timestamps (monotonic seconds).
        self.request_timestamps: "deque[float]" = deque()


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
            now = time.monotonic()

            # 429 cooldown — skip a banned host for this query instead of
            # parking a download worker. A concurrent episode search can
            # otherwise queue behind this lock for minutes (or an hour),
            # making the whole download UI appear stuck. This remains active
            # under pytest's gap-delay override because it is a correctness
            # guard, not pacing.
            if state.cooldown_until > now:
                wait = state.cooldown_until - now
                raise RuntimeError(
                    f"Rate limited: {host} cooling down for {wait:.0f}s"
                )

            # Windowed cap — keep the host's recent request count below
            # ``_MAX_REQUESTS_PER_HOST`` over the last ``_WINDOW_SECONDS``.
            # When the cap is hit, sleep until the oldest entry leaves the
            # window (capped at ``_MAX_SLEEP_ON_CAP``) instead of raising —
            # a transient wait is far better than failing the whole season.
            if _MAX_REQUESTS_PER_HOST > 0:
                self._trim_window(state, now)
                while len(state.request_timestamps) >= _MAX_REQUESTS_PER_HOST:
                    oldest = state.request_timestamps[0]
                    wait = (oldest + _WINDOW_SECONDS) - now
                    if wait <= 0:
                        # Should not normally happen — trim and re-check.
                        self._trim_window(state, now)
                        continue
                    if wait > _MAX_SLEEP_ON_CAP:
                        # Cap is saturated for too long — signal it so the
                        # preflight can mark this addon "indeterminate"
                        # instead of "dead". Do NOT raise here; the caller
                        # is already inside a download context.
                        raise RuntimeError(
                            f"Rate limit cap saturated: {host} — "
                            f"{len(state.request_timestamps)} requests in last "
                            f"{_WINDOW_SECONDS:.0f}s, would need to wait {wait:.0f}s"
                        )
                    time.sleep(min(wait, _MAX_SLEEP_ON_CAP))
                    now = time.monotonic()
                    self._trim_window(state, now)

            state.request_count += 1
            state.request_timestamps.append(now)

            if not _DISABLE_DELAYS:

                # b) Minimum gap since last request to this host
                if state.last_request > 0:
                    gap = MIN_GAP - (now - state.last_request)
                    if gap > 0:
                        time.sleep(gap)

            state.last_request = time.monotonic()

            # Yield — caller makes the HTTP request with the lock held
            yield url

    @staticmethod
    def _trim_window(state: "_HostState", now: float) -> None:
        """Drop timestamps older than the window from the head of the deque.

        A timestamp is "in the window" while its age is strictly less than
        ``_WINDOW_SECONDS``. A request made at exactly ``now - window`` has
        already left the window and must be dropped.
        """
        window_start = now - _WINDOW_SECONDS
        timestamps = state.request_timestamps
        while timestamps and timestamps[0] <= window_start:
            timestamps.popleft()

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

    def is_saturated(self, url: str) -> bool:
        """Return True when *url*'s host is currently at or above the per-host cap.

        Used by the preflight search to distinguish a "dead" addon (no streams
        returned because the host is genuinely down or empty) from an
        "indeterminate" addon (no streams returned because the local
        rate-limit budget is exhausted and a wait would be needed).
        """
        if _MAX_REQUESTS_PER_HOST <= 0:
            return False
        host = _extract_host(url)
        if not host:
            return False
        state = self._hosts.get(host)
        if state is None:
            return False
        with state.lock:
            now = time.monotonic()
            self._trim_window(state, now)
            return len(state.request_timestamps) >= _MAX_REQUESTS_PER_HOST

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
