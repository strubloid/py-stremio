"""Orchestrate a full addon discovery run: scrape → test → merge."""

import time
from pathlib import Path

from .sources import run_all_sources
from .tester import test_urls
from .merger import merge_new_addons


def _find_project_root() -> Path:
    """Walk up from cwd or the module's location to find pyproject.toml."""
    start = Path.cwd()
    for p in [start] + list(start.parents):
        if (p / "pyproject.toml").exists():
            return p
    # Fallback to cwd
    return start


def discover_new_addons(
    addon_txt_path: str | None = None,
    max_test_workers: int = 8,
    verbose: bool = True,
) -> dict[str, int | str]:
    """Run the full addon discovery pipeline.

    1. Scrape known sources for addon manifest URLs.
    2. Test each URL for reachability.
    3. Merge working URLs into addons.txt.

    Args:
        addon_txt_path: Path to addons.txt (default: project root).
        max_test_workers: Parallelism for the URL tester.
        verbose: Print progress.

    Returns:
        Dict with counts from the merge step.
    """
    project_root = Path(addon_txt_path).resolve().parent if addon_txt_path else _find_project_root()
    if addon_txt_path is None:
        addon_txt_path = str(project_root / "addons.txt")

    if verbose:
        print(f"  Addons file: {addon_txt_path}", flush=True)

    # ── Step 1: Collect ──
    if verbose:
        print("  📡 Collecting addon URLs from sources...", flush=True)

    collected = run_all_sources(verbose=verbose)

    if not collected.urls:
        if verbose:
            print("  ! No URLs collected from any source", flush=True)
        return {"error": "no_urls_collected"}

    if verbose:
        print(f"  Collected {len(collected.urls)} unique addon URLs", flush=True)
    if collected.errors:
        for err in collected.errors:
            if verbose:
                print(f"  ⚠ {err}", flush=True)

    # ── Step 2: Test ──
    if verbose:
        print(f"\n  🧪 Testing {len(collected.urls)} addon URLs (max {max_test_workers} workers)...", flush=True)

    test_start = time.monotonic()
    tested = test_urls(
        list(collected.urls),
        max_workers=max_test_workers,
        verbose=verbose,
    )

    if verbose:
        print(f"  ⏱  Testing took {tested.elapsed_seconds:.1f}s", flush=True)

    if not tested.working:
        if verbose:
            print("  ! No working addons found", flush=True)
        return {"error": "no_working_found"}

    # ── Step 3: Merge ──
    addon_path = Path(addon_txt_path)
    if verbose:
        print(f"\n  📝 Merging into {addon_path}...", flush=True)

    result = merge_new_addons(
        addon_txt_path=addon_txt_path,
        working_urls=tested.working,
        dead_urls=tested.dead,
        verbose=verbose,
    )

    return result
