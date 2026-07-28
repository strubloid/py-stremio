"""
Addon health checker — runs every active URL from
  - addons/addons.txt
  - addons/stremio.txt
  - addons/experimental.txt
and reports which ones are alive, dead, or advisory-only.

Output: debug/13_addon_health_report.json + a short stdout summary.

Usage:  python debug/13_addon_health_check.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = ROOT / "debug" / "13_addon_health_report.json"
TIMEOUT = 10.0
MAX_WORKERS = 20


URL_RE = re.compile(r"^https?://[^\s#]+$")


def extract_active_urls(path: Path) -> list[str]:
    """Return URLs whose line starts with http(s):// and is not commented out."""
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        if URL_RE.match(s):
            out.append(s)
    return out


def _normalize_for_request(url: str) -> str:
    """If a URL is a base (no /manifest.json), probe /manifest.json."""
    if url.endswith("/manifest.json"):
        return url
    return url.rstrip("/") + "/manifest.json"


def probe(url: str, client: httpx.Client) -> dict:
    """Probe one manifest URL."""
    target = _normalize_for_request(url)
    start = time.time()
    out: dict = {
        "url": url,
        "probed": target,
        "ok": False,
        "status": None,
        "error": None,
        "is_addon": False,
        "has_stream_resource": False,
        "has_catalog_resource": False,
        "elapsed": 0.0,
    }
    try:
        resp = client.get(target, timeout=TIMEOUT, follow_redirects=True)
        elapsed = time.time() - start
        out["elapsed"] = round(elapsed, 2)
        out["status"] = resp.status_code
        if resp.status_code != 200:
            out["error"] = f"HTTP {resp.status_code}"
            return out
        data = resp.json()
    except Exception as exc:
        out["elapsed"] = round(time.time() - start, 2)
        out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return out

    # Heuristics: a Stremio addon manifest has id, version, resources/types fields
    if isinstance(data, dict) and "id" in data and ("resources" in data or "types" in data):
        out["ok"] = True
        out["is_addon"] = True
        resources = data.get("resources") or []
        if isinstance(resources, list):
            if any(r == "stream" or (isinstance(r, dict) and r.get("name") == "stream") for r in resources):
                out["has_stream_resource"] = True
            if any(r == "catalog" or (isinstance(r, dict) and r.get("name") == "catalog") for r in resources):
                out["has_catalog_resource"] = True
        out["name"] = data.get("name") or data.get("id")
        out["version"] = data.get("version")
    else:
        out["error"] = "manifest_shape_invalid"
    return out


def main() -> int:
    sources = {
        "addons.txt": ROOT / "addons" / "addons.txt",
        "stremio.txt": ROOT / "addons" / "stremio.txt",
        "experimental.txt": ROOT / "addons" / "experimental.txt",
    }

    by_source: dict[str, list[str]] = {}
    for label, path in sources.items():
        if path.exists():
            by_source[label] = extract_active_urls(path)
        else:
            by_source[label] = []

    all_urls: list[tuple[str, str]] = []
    for label, urls in by_source.items():
        for u in urls:
            all_urls.append((label, u))

    # De-duplicate but keep first source label
    seen: dict[str, str] = {}
    for label, u in all_urls:
        if u not in seen:
            seen[u] = label
    unique_urls = list(seen.keys())

    print(f"Total active URLs (raw): {len(all_urls)}")
    print(f"Unique URLs to probe:   {len(unique_urls)}")
    print(f"Concurrency:            {MAX_WORKERS} workers, {TIMEOUT}s timeout each")
    print()

    results: dict[str, dict] = {}
    headers = {"User-Agent": "py-stremio/1.0 addon-health-check"}

    with httpx.Client(headers=headers) as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {executor.submit(probe, u, client): u for u in unique_urls}
            done = 0
            for future in as_completed(future_map):
                u = future_map[future]
                try:
                    r = future.result()
                except Exception as exc:
                    r = {"url": u, "ok": False, "error": f"probe_failed: {exc}"}
                results[u] = r
                done += 1
                if done % 10 == 0 or done == len(unique_urls):
                    print(f"  Probed {done}/{len(unique_urls)}", flush=True)

    # Cross-reference: which source each URL came from
    by_source_final: dict[str, list[str]] = {k: [] for k in sources}
    for label, u in all_urls:
        by_source_final[label].append(u)

    # Classification
    summary = {
        "ok": [],
        "stream_capable": [],
        "catalog_only": [],
        "dead": [],
        "advisory": [],  # reachable but no stream resource
    }
    for u, r in results.items():
        if r.get("ok") and r.get("has_stream_resource"):
            summary["stream_capable"].append(u)
            summary["ok"].append(u)
        elif r.get("ok"):
            summary["catalog_only"].append(u)
            summary["ok"].append(u)
        else:
            summary["dead"].append(u)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_probed": len(unique_urls),
        "by_source_counts": {k: len(v) for k, v in by_source_final.items()},
        "summary": {
            "stream_capable": len(summary["stream_capable"]),
            "catalog_only": len(summary["catalog_only"]),
            "dead": len(summary["dead"]),
        },
        "stream_capable": sorted(summary["stream_capable"]),
        "catalog_only": sorted(summary["catalog_only"]),
        "dead": sorted(summary["dead"]),
        "per_url": {u: r for u, r in results.items()},
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print(f"Stream-capable addons:  {len(summary['stream_capable'])}")
    print(f"Catalog-only addons:    {len(summary['catalog_only'])}")
    print(f"Dead addons:            {len(summary['dead'])}")
    print()
    print(f"Full report written to: {OUT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
