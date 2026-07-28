"""
Verify candidate addons from research against their manifest endpoints.

Reads candidate addons from debug/15_candidate_addons.json, probes each
manifest, and writes a verification report.

Usage:  python debug/15_verify_candidates.py
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "debug" / "15_candidate_addons.json"
REPORT = ROOT / "debug" / "15_verification_report.json"
TIMEOUT = 12.0
MAX_WORKERS = 20


def probe(url: str, client: httpx.Client) -> dict:
    target = url if url.endswith("/manifest.json") else url.rstrip("/") + "/manifest.json"
    start = time.time()
    out = {"url": url, "probed": target, "ok": False, "status": None, "is_addon": False,
           "has_stream_resource": False, "name": None, "elapsed": 0.0, "error": None}
    try:
        resp = client.get(target, timeout=TIMEOUT, follow_redirects=True)
        out["elapsed"] = round(time.time() - start, 2)
        out["status"] = resp.status_code
        if resp.status_code != 200:
            out["error"] = f"HTTP {resp.status_code}"
            return out
        data = resp.json()
    except Exception as exc:
        out["elapsed"] = round(time.time() - start, 2)
        out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return out

    if isinstance(data, dict) and "id" in data and ("resources" in data or "types" in data):
        out["ok"] = True
        out["is_addon"] = True
        out["name"] = data.get("name") or data.get("id")
        resources = data.get("resources") or []
        if any(r == "stream" or (isinstance(r, dict) and r.get("name") == "stream") for r in resources):
            out["has_stream_resource"] = True
    else:
        out["error"] = "manifest_shape_invalid"
    return out


def main() -> int:
    if not CANDIDATES.exists():
        print(f"ERROR: missing {CANDIDATES}")
        return 1
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))

    print(f"Candidates to verify: {len(candidates)}")
    print(f"Concurrency: {MAX_WORKERS} workers, {TIMEOUT}s timeout")
    print()

    headers = {"User-Agent": "py-stremio/1.0 addon-verify"}
    verified: list[dict] = []
    failed: list[dict] = []

    with httpx.Client(headers=headers) as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {executor.submit(probe, c["url"], client): c for c in candidates}
            done = 0
            for future in as_completed(future_map):
                c = future_map[future]
                try:
                    r = future.result()
                except Exception as exc:
                    r = {"ok": False, "error": f"probe_failed: {exc}"}
                if r.get("ok") and r.get("has_stream_resource"):
                    verified.append({**c, **r})
                else:
                    failed.append({**c, **r})
                done += 1
                if done % 10 == 0 or done == len(candidates):
                    print(f"  Probed {done}/{len(candidates)}", flush=True)

    print()
    print(f"Verified working (stream resource): {len(verified)}")
    print(f"Failed:                              {len(failed)}")
    print()

    print("─" * 70)
    print("VERIFIED:")
    for v in sorted(verified, key=lambda x: (x.get("region", "z"), x["name"])):
        print(f"  ✓ [{v.get('region', 'worldwide'):12s}] {v['name']:30s} {v.get('elapsed', 0):5.2f}s  {v['url'][:80]}")

    if failed:
        print()
        print("FAILED:")
        for f in failed:
            err = (f.get("error") or "?")[:40]
            region = (f.get("region") or "worldwide")[:12]
            name = (f.get("name") or "?")[:30]
            url = (f.get("url") or "?")[:60]
            print(f"  ✗ [{region:12s}] {name:30s} {err:40s}  {url}")

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_candidates": len(candidates),
        "verified": len(verified),
        "failed": len(failed),
        "verified_addons": verified,
        "failed_addons": failed,
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"Full report: {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
