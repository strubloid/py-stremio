"""
Insert newly verified addons into addons/stremio.txt and addons/addons.txt.

Reads the verification report and appends the 24 confirmed-working addons
to the files, organized by region/category. Existing addons are not
touched.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "debug" / "15_verification_report.json"
STREMIO_FILE = ROOT / "addons" / "stremio.txt"
ADDONS_FILE = ROOT / "addons" / "addons.txt"


# Region labels with emoji/flag for readability
REGION_LABELS = {
    "worldwide": "🌍 WORLDWIDE",
    "argentina": "🇦🇷 ARGENTINA",
    "australia": "🇦🇺 AUSTRALIA",
    "brazil": "🇧🇷 BRAZIL",
    "india": "🇮🇳 INDIA",
    "japan": "🇯🇵 JAPAN",
    "italy": "🇮🇹 ITALY",
    "korea": "🇰🇷 KOREA",
    "latam": "🌎 LATAM",
    "poland": "🇵🇱 POLAND",
    "portugal": "🇵🇹 PORTUGAL",
    "romania": "🇷🇴 ROMANIA",
    "arabia": "🇸🇦 ARABIA",
    "spain": "🇪🇸 SPAIN",
    "france": "🇫🇷 FRANCE",
    "germany": "🇩🇪 GERMANY",
    "russia": "🇷🇺 RUSSIA",
    "vietnam": "🇻🇳 VIETNAM",
    "turkey": "🇹🇷 TURKEY",
    "usa": "🇺🇸 USA",
}


# Addons that are most useful for video downloads.
# We skip metadata/catalog-only addons (MyTrakt, Better Metadata) and
# NSFW ones. IPTV addons are included since the user wants worldwide.
def categorize(addon: dict) -> str:
    cat = (addon.get("category") or "").lower()
    name = addon.get("name", "")
    if "NSFW" in name or "Porn" in name or "18+" in name:
        return "nsfw_skip"
    if cat in ("torrent",):
        return "torrent"
    if cat in ("iptv",):
        return "iptv"
    if cat in ("specialized",):
        return "specialized"
    if cat in ("usenet",):
        return "usenet"
    return "other"


def build_section(verified: list[dict]) -> str:
    """Build the new addon block to append to stremio.txt."""
    # Group by region, then by category within region
    by_region: dict[str, dict[str, list[dict]]] = {}
    for a in verified:
        region = a.get("region", "worldwide") or "worldwide"
        bucket = categorize(a)
        if bucket == "nsfw_skip":
            continue
        by_region.setdefault(region, {}).setdefault(bucket, []).append(a)

    lines: list[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append("")
    lines.append(f"# ── WORLDWIDE ADDONS ADDED {ts} ─────────────────────────────────────────")
    lines.append(f"# {len(verified)} addons verified via debug/15_verify_candidates.py")
    lines.append(f"# Sources: stremio-addons.net, elfhosted, community catalogs")
    lines.append(f"# All return valid Stremio manifest with 'stream' resource")
    lines.append("")

    # Worldwide first, then by region alphabetically
    region_order = ["worldwide"] + sorted(r for r in by_region if r != "worldwide")
    cat_order = ["torrent", "iptv", "specialized", "usenet", "other"]

    for region in region_order:
        if region not in by_region:
            continue
        label = REGION_LABELS.get(region, region.upper())
        lines.append(f"# ── {label} ─────────────────────────────────────────────────")
        for cat in cat_order:
            if cat not in by_region[region]:
                continue
            cat_label = {"torrent": "Torrent / Debrid", "iptv": "IPTV / Live",
                         "specialized": "Specialized", "usenet": "Usenet",
                         "other": "Other"}[cat]
            lines.append(f"#   {cat_label}")
            for a in sorted(by_region[region][cat], key=lambda x: x["name"]):
                lines.append(f"https://{a['url'].split('://', 1)[1] if a['url'].startswith('http') else a['url']}")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not REPORT.exists():
        print(f"ERROR: missing {REPORT}")
        return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    verified = report.get("verified_addons", [])
    if not verified:
        print("No verified addons to insert.")
        return 0

    block = build_section(verified)

    # Append to stremio.txt
    if STREMIO_FILE.exists():
        existing = STREMIO_FILE.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            existing += "\n"
        STREMIO_FILE.write_text(existing + block + "\n", encoding="utf-8")
        print(f"Appended {block.count(chr(10))} lines to {STREMIO_FILE.relative_to(ROOT)}")

    # Also add a slim version to addons.txt (just the base URLs without /manifest.json,
    # matching the existing convention)
    if ADDONS_FILE.exists():
        # Only add torrent and iptv addons to addons.txt (the curated list)
        addons_block_lines: list[str] = []
        addons_block_lines.append("")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        addons_block_lines.append(f"# ── WORLDWIDE ADDONS ADDED {ts} ─────────────────────────────────────────")
        for a in sorted(verified, key=lambda x: (x.get("region", "z"), x["name"])):
            cat = categorize(a)
            if cat not in ("torrent", "iptv"):
                continue
            url = a["url"]
            # Strip /manifest.json to match the addons.txt convention
            base = url.replace("/manifest.json", "").rstrip("/")
            addons_block_lines.append(f"{base}  # {a['name']} [{a.get('region', 'worldwide')}]")
        addons_block_lines.append("")
        existing = ADDONS_FILE.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            existing += "\n"
        ADDONS_FILE.write_text(existing + "\n".join(addons_block_lines) + "\n", encoding="utf-8")
        print(f"Appended slim list to {ADDONS_FILE.relative_to(ROOT)}")

    print()
    print("Added addons:")
    for a in sorted(verified, key=lambda x: (x.get("region", "z"), x["name"])):
        print(f"  [{a.get('region', 'worldwide'):12s}] {a['name']:35s} {a['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
