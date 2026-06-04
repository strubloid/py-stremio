"""Validate addon URLs from addons.txt by testing manifest + stream endpoints.

Usage:
    validate_and_update("addons.txt")   # Test all URLs, comment out failing ones
    validate_all_addons("addons.txt")   # Test all URLs, return (working, failed) lists
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote

import httpx

# ── Test target ──────────────────────────────────────────────────────────
# Game of Thrones S01E01 — almost universally available across addons
TEST_TYPE = "series"
TEST_ID = "tt0944947:1:1"

VALIDATION_TIMEOUT = 10          # seconds per addon
VALIDATION_CONCURRENCY = 10      # parallel checks


# ── Helpers ──────────────────────────────────────────────────────────────

def _addon_label(url: str, max_len: int = 55) -> str:
    """Short human-friendly label from a URL (domain + last path segment)."""
    base = url.rstrip("/").replace("/manifest.json", "")
    # Strip query params for display
    clean = base.split("?")[0]
    if len(clean) <= max_len:
        return clean
    # Show last N chars so the meaningful part isn't lost
    return f"…{clean[-max_len:]}"


def _extract_lines(filepath: str) -> tuple[list[str], list[tuple[str, int, str]]]:
    """Read file, return (all_lines, [(unquoted_url, lineno, original_line), ...]).

    Only non-comment lines starting with ``http`` are included.
    """
    with open(filepath, "r") as f:
        all_lines = f.readlines()
    candidates: list[tuple[str, int, str]] = []
    for i, line in enumerate(all_lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped.startswith("http"):
            candidates.append((unquote(stripped), i, stripped))
    return all_lines, candidates


# ── Single-addon test ────────────────────────────────────────────────────

def check_addon_url(url: str) -> dict:
    """Test a single addon URL.

    Checks:
      1. ``{base}/manifest.json`` returns 200 + parseable JSON
      2. ``{base}/stream/{type}/{id}.json`` returns parseable JSON with streams

    Returns dict with keys: *url*, *manifest_ok*, *streams_found*, *error*.
    """
    base = url.rstrip("/").replace("/manifest.json", "")
    result = {"url": url, "manifest_ok": False, "streams_found": 0, "error": None}

    headers = {
        "User-Agent": "Stremio/4.4.168",
        "Accept": "application/json",
    }

    # ── 1. Manifest check ────────────────────────────────────────────────
    try:
        resp = httpx.get(
            f"{base}/manifest.json",
            timeout=VALIDATION_TIMEOUT,
            headers=headers,
            follow_redirects=True,
        )
        if resp.is_success:
            data = resp.json()
            # Any manifest-shaped JSON qualifies: has at least one of
            # these standard keys OR it's a dict with content
            if isinstance(data, dict) and (
                "id" in data or "name" in data
                or "resources" in data or "types" in data
                or "streams" in data
            ):
                result["manifest_ok"] = True
    except Exception as exc:
        result["error"] = str(exc)[:100]

    # ── 2. Stream query ──────────────────────────────────────────────────
    try:
        resp = httpx.get(
            f"{base}/stream/{TEST_TYPE}/{TEST_ID}.json",
            timeout=VALIDATION_TIMEOUT,
            headers=headers,
            follow_redirects=True,
        )
        if resp.is_success:
            data = resp.json()
            streams = data.get("streams", [])
            if isinstance(streams, list):
                result["streams_found"] = len(streams)
    except Exception:
        pass

    return result


# ── Batch validation ─────────────────────────────────────────────────────

def validate_all_addons(
    filepath: str = "addons.txt",
    *,
    quiet: bool = False,
) -> tuple[list[str], list[str]]:
    """Test every uncommented URL in *filepath*.

    Returns ``(working_urls, failed_urls)``.
    """
    import sys
    import itertools

    lines, candidates = _extract_lines(filepath)

    if not candidates:
        print("  No addon URLs found to validate.")
        return [], []

    working: list[str] = []
    failed: list[str] = []
    total = len(candidates)
    spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    done_count = 0

    print(f"    Testing {total} addon URLs...", end="", flush=True)

    with ThreadPoolExecutor(max_workers=VALIDATION_CONCURRENCY) as executor:
        futures = {
            executor.submit(check_addon_url, url): (lineno, url, orig_line)
            for url, lineno, orig_line in candidates
        }
        for future in as_completed(futures):
            done_count += 1
            char = next(spinner)
            sys.stdout.write(f"\r    {char} Testing addons ({done_count}/{total})")
            sys.stdout.flush()

            lineno, url, orig_line = futures[future]
            try:
                result = future.result(timeout=VALIDATION_TIMEOUT + 5)
            except Exception as exc:
                result = {
                    "url": url,
                    "manifest_ok": False,
                    "streams_found": 0,
                    "error": f"future exception: {exc}",
                }

            ok = result["manifest_ok"] or result["streams_found"] > 0
            if ok:
                working.append(url)
            else:
                failed.append(url)

    # Clear the spinner line
    print()

    return working, failed


def update_addons_file(
    filepath: str = "addons.txt",
    *,
    working: list[str] | None = None,
    failed: list[str] | None = None,
) -> int:
    """Rewrite *filepath*, commenting out any URL in *failed*.

    Preserves all existing comments, section headers, and blank lines.
    URLs in *working* are left untouched.  Returns number of lines changed.
    """
    working_set = set(working or [])
    failed_set = set(failed or [])

    with open(filepath, "r") as f:
        original = f.read()

    new_lines: list[str] = []
    changes = 0

    for line in original.splitlines(keepends=True):
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and stripped.startswith("http")
        ):
            url = unquote(stripped)
            if url in failed_set and url not in working_set:
                new_lines.append(f"# {stripped}\n")
                changes += 1
                continue
            # Working URL — keep as-is
            new_lines.append(line)
        else:
            # Already a comment, blank, section header — keep untouched
            new_lines.append(line)

    if changes:
        with open(filepath, "w") as f:
            f.writelines(new_lines)

    return changes


def validate_and_update(
    filepath: str = "addons.txt",
    *,
    quiet: bool = False,
) -> tuple[int, int]:
    """Validate all addon URLs and auto-comment failing ones.

    Returns ``(working_count, failed_count)``.
    """
    print()
    print(f"\033[96m🛠  Validate addons\033[0m")
    if not quiet:
        print(f"  File: {filepath}")

    working, failed = validate_all_addons(filepath, quiet=quiet)
    changes = update_addons_file(filepath, working=working, failed=failed)

    if changes:
        print(f"  Commented out {changes} non-working URL(s) in {filepath}")

    if not failed:
        print(f"\n  \033[92m✓ All {len(working)} addon(s) working\033[0m")
    else:
        print(
            f"\n  \033[93m{len(working)} working, "
            f"{len(failed)} failed "
            f"({changes} commented out in {filepath})\033[0m"
        )

    return len(working), len(failed)
