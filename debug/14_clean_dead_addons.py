"""
Clean non-working addons from the three addon files.

Reads debug/13_addon_health_report.json, identifies dead URLs, and
comments them out (or removes them) in:
  - addons/addons.txt
  - addons/stremio.txt
  - addons/experimental.txt

Dead URLs already in comments are left alone. Dead URLs on active lines
are commented out and tagged with the failure reason for future reference.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "debug" / "13_addon_health_report.json"
FILES = [
    ROOT / "addons" / "addons.txt",
    ROOT / "addons" / "stremio.txt",
    ROOT / "addons" / "experimental.txt",
]


def clean_one(path: Path, dead_urls: set[str]) -> tuple[int, list[str]]:
    if not path.exists():
        return 0, []
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    changed = 0
    notes: list[str] = []
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            out.append(line)
            continue
        # Active URL line — check if it's a dead URL.
        # A dead URL may be the probed (with /manifest.json) or the original
        # (without it) — match by URL prefix or hostname.
        matched = None
        for dead in dead_urls:
            if dead in line:
                matched = dead
                break
            # If the line is the base URL (no /manifest.json) but the dead
            # record was probed with /manifest.json, still match.
            if line.rstrip("/") + "/manifest.json" == dead:
                matched = dead
                break
            # If the line is the base URL and the dead record is the same
            # base URL, match.
            if line.rstrip("/") == dead.rstrip("/"):
                matched = dead
                break
        if matched:
            rel = path.relative_to(ROOT)
            note = f"  commented {rel}: {matched[:80]}"
            notes.append(note)
            out.append(f"# DEAD-2026-07-22 {line}")
            changed += 1
        else:
            out.append(line)

    if changed:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        header = f"\n# ── Cleaned {ts}: {changed} dead URL(s) commented out (see debug/13_addon_health_report.json) ──"
        # Insert header near top, after the file's leading comment block
        insert_at = 0
        for i, ln in enumerate(out[:30]):
            if ln.strip().startswith("#") or not ln.strip():
                insert_at = i + 1
            else:
                break
        out.insert(insert_at, header)
        new_text = "\n".join(out) + "\n"
        path.write_text(new_text, encoding="utf-8")
    return changed, notes


def main() -> int:
    if not REPORT.exists():
        print(f"ERROR: missing {REPORT} — run 13_addon_health_check.py first")
        return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    dead_urls = set(report.get("dead", []))
    if not dead_urls:
        print("No dead addons to clean.")
        return 0

    print(f"Dead addons to comment out: {len(dead_urls)}")
    for u in sorted(dead_urls):
        print(f"  - {u[:90]}")
    print()

    total = 0
    all_notes: list[str] = []
    for path in FILES:
        if not path.exists():
            print(f"  SKIP (missing): {path.relative_to(ROOT)}")
            continue
        changed, notes = clean_one(path, dead_urls)
        total += changed
        all_notes.extend(notes)
        rel = str(path.relative_to(ROOT))
        print(f"  {rel:30s}  {changed} line(s) commented")

    print()
    print(f"Total: {total} dead URL(s) commented out across {len(FILES)} file(s)")
    print()
    for note in all_notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
