"""Parallel URL reachability testing for Stremio addon manifests."""

import json
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urlparse

_HDR = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


@dataclass
class TestResult:
    """Test results for a batch of addon URLs."""
    working: list[tuple[str, str | None]] = field(default_factory=list)
    dead: list[str] = field(default_factory=list)
    total_tested: int = 0
    elapsed_seconds: float = 0.0


def _test_single_url(url: str, timeout: int = 8) -> tuple[bool, str | None]:
    """Test if a single URL is a valid Stremio addon manifest endpoint.

    Fetches <url>/manifest.json and checks for 'id' or 'name' in the
    JSON response.  Returns (True, name_or_id) on success or
    (False, None) on failure.
    """
    base = url.rstrip("/")
    manifest_url = f"{base}/manifest.json"
    try:
        req = urllib.request.Request(manifest_url, headers=_HDR)
        r = urllib.request.urlopen(req, timeout=timeout, context=_CTX)
        if r.status == 200:
            data = r.read()
            try:
                j = json.loads(data)
                if "id" in j or "name" in j:
                    name = j.get("name") or j.get("id") or "unknown"
                    return True, str(name)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            # Some addons return content that is not valid JSON but the
            # endpoint works (e.g. StremThru).  Accept 200 with >=50 bytes.
            if len(data) >= 50:
                return True, "http_200"
    except Exception:
        pass
    return False, None


def test_urls(
    urls: list[str],
    max_workers: int = 8,
    verbose: bool = True,
) -> TestResult:
    """Test multiple addon URLs in parallel.

    Args:
        urls: List of addon manifest URLs to test.
        max_workers: Parallelism level (default 8).
        verbose: Print progress every 15 URLs.

    Returns:
        TestResult with working and dead lists.
    """
    result = TestResult(total_tested=len(urls))
    start = time.monotonic()
    working: list[tuple[str, str | None]] = []
    dead: list[str] = []

    for i in range(0, len(urls), 20):
        chunk = urls[i : i + 20]
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_map = {ex.submit(_test_single_url, u): u for u in chunk}
            for f in as_completed(fut_map):
                url = fut_map[f]
                try:
                    ok, name = f.result(timeout=10)
                    if ok:
                        working.append((url, name))
                    else:
                        dead.append(url)
                except Exception:
                    dead.append(url)

        if verbose and len(urls) >= 15:
            pct = min(100, (i + 20) * 100 // len(urls))
            print(
                f"  Tested {pct}% "
                f"({len(working)} working, {len(dead)} dead)",
                flush=True,
            )

    # Deduplicate by domain + path (take the first working variant)
    seen_domains: set[str] = set()
    deduped_working: list[tuple[str, str | None]] = []
    for url, name in working:
        parsed = urlparse(url)
        key = f"{parsed.netloc}{parsed.path.rstrip('/')}"
        if key not in seen_domains:
            seen_domains.add(key)
            deduped_working.append((url, name))

    result.working = deduped_working
    result.dead = dead
    result.elapsed_seconds = time.monotonic() - start

    if verbose:
        print(
            f"  Done: {len(deduped_working)} working, "
            f"{len(dead)} dead in {result.elapsed_seconds:.1f}s",
            flush=True,
        )

    return result
