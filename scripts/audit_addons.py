"""Audit all built-in Stremio addons.

For each addon class registered in py_stremio.components.addons.types we:
  1. Verify the class can be instantiated.
  2. Call get_url(api_key=None) and confirm the URL is well-formed.
  3. GET the /manifest.json to confirm the addon is reachable.
  4. If reachable, send a real /stream/series/ request for One Piece S23E3
     (IMDB tt0388629) and inspect the response shape to see if it has the
     expected fields the filter needs (infoHash/fileIdx or url).
  5. Mark the addon with PASS / WARN / FAIL based on the result.

Notes:
  - We attempt manifest.json first because it is the smallest possible
    probe — a working manifest usually means the addon service is
    reachable, and only when it succeeds do we burn the heavier
    stream-request round trip.
  - The audit is honest about what it can and cannot verify:
    * 4xx/5xx responses are reported with their actual status code.
    * Network errors (Cloudflare 403, DNS failure, timeout) are
      reported as "network unreachable" and not as addon bugs.
  - Run with: python scripts/audit_addons.py
  - The script can be re-run as addons are migrated.  Output is a
    markdown report listing every addon with its health state and the
    reason for any warning/failure.

Issues uncovered by this audit are recorded in addons-check.md.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from py_stremio.components.download import stream_download
from py_stremio.components.addons.models import StreamInfo

# Standard test query: One Piece S23E3 (IMDB tt0388629)
TEST_SERIES_ID = "tt0388629:23:3"
TEST_TITLE = "One Piece"
TEST_SEASON = 23
TEST_EPISODE = 3
TEST_IMDB = "tt0388629"
TIMEOUT = 8

# Audit a few representative queries: the user-reported case + a movie.
AUDIT_QUERIES: list[tuple[str, str, int | None, int | None, str]] = [
    # (description, stremio_id, season, episode, imdb)
    ("One Piece S23E3 (user case)", "tt0388629:23:3", 23, 3, "tt0388629"),
]


@dataclass
class AddonAudit:
    name: str
    base_url: str
    class_path: str
    health: str = "UNKNOWN"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    manifest_status: int | None = None
    stream_count: int = 0
    sample_name: str = ""
    sample_title: str = ""
    sample_has_infohash: bool = False
    sample_has_url: bool = False
    sample_passed_filter: bool = False
    response_time_ms: int = 0


def _class_path(cls: type) -> str:
    return f"{cls.__module__}.{cls.__name__}"


def _discover_addon_classes() -> list[tuple[str, type]]:
    """Walk py_stremio.components.addons.types and collect every HttpAddon subclass."""
    from py_stremio.components.addons.base import HttpAddon

    seen: dict[str, type] = {}
    import py_stremio.components.addons.types as types_pkg

    def _walk(module: Any) -> None:
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name, None)
            if (
                isinstance(attr, type)
                and issubclass(attr, HttpAddon)
                and attr is not HttpAddon
                and getattr(attr, "name", None)
            ):
                if attr.name not in seen:
                    seen[attr.name] = attr
        if hasattr(module, "__path__"):
            from pkgutil import iter_modules

            for _finder, sub_name, _is_pkg in iter_modules(module.__path__):
                if sub_name.startswith("_"):
                    continue
                full_name = f"{module.__name__}.{sub_name}"
                try:
                    sub_mod = __import__(full_name, fromlist=["*"])
                    _walk(sub_mod)
                except Exception:
                    pass

    _walk(types_pkg)
    return [(name, cls) for name, cls in sorted(seen.items())]


def _audit_one(name: str, cls: type) -> AddonAudit:
    audit = AddonAudit(
        name=name,
        base_url=getattr(cls, "base_url", ""),
        class_path=_class_path(cls),
    )

    # 1) Class sanity
    if not audit.base_url:
        audit.errors.append("base_url is empty")
        audit.health = "FAIL"
        return audit

    parsed = urlparse(audit.base_url)
    if parsed.scheme not in {"http", "https"}:
        audit.errors.append(f"base_url scheme is {parsed.scheme!r}, expected http(s)")
        audit.health = "FAIL"
        return audit
    if not parsed.netloc:
        audit.errors.append("base_url has no host")
        audit.health = "FAIL"
        return audit

    # 2) Instantiate and call get_url
    try:
        instance = cls()
    except Exception as exc:
        audit.errors.append(f"instantiate failed: {exc}")
        audit.health = "FAIL"
        return audit

    try:
        url = instance.get_url(api_key=None)
    except Exception as exc:
        audit.errors.append(f"get_url() raised: {exc}")
        audit.health = "FAIL"
        return audit

    if not url.startswith(("http://", "https://")):
        audit.errors.append(f"get_url() returned non-http URL: {url!r}")
        audit.health = "FAIL"
        return audit

    # 3) GET /manifest.json as a cheap reachability probe
    manifest_url = instance.query_stream_url("series", TEST_SERIES_ID).rsplit("/stream/", 1)[0] + "/manifest.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=TIMEOUT) as client:
            t0 = time.time()
            resp = client.get(manifest_url)
            audit.response_time_ms = int((time.time() - t0) * 1000)
            audit.manifest_status = resp.status_code
            if resp.status_code != 200:
                audit.warnings.append(
                    f"manifest.json returned {resp.status_code} (addon may be offline or Cloudflare-blocked)"
                )
                audit.health = "WARN"
                return audit
            try:
                manifest = resp.json()
                catalog_ids = [c.get("id") for c in (manifest.get("catalogs") or [])]
                audit.info.append(f"manifest OK; catalogs: {catalog_ids}")
            except Exception as exc:
                audit.warnings.append(f"manifest.json not parseable as JSON: {exc}")
                audit.health = "WARN"
                return audit
    except Exception as exc:
        audit.warnings.append(f"manifest.json request failed: {type(exc).__name__}: {str(exc)[:120]}")
        audit.health = "WARN"
        return audit

    # 4) Live /stream/ request
    stream_url = instance.query_stream_url("series", TEST_SERIES_ID)
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=TIMEOUT) as client:
            t0 = time.time()
            resp = client.get(stream_url)
            audit.response_time_ms = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                audit.warnings.append(f"stream endpoint returned {resp.status_code}")
                audit.health = "WARN"
                return audit
            try:
                data = resp.json()
            except Exception as exc:
                audit.warnings.append(f"stream response is not valid JSON: {exc}")
                audit.health = "WARN"
                return audit
    except Exception as exc:
        audit.warnings.append(f"stream request failed: {type(exc).__name__}: {str(exc)[:120]}")
        audit.health = "WARN"
        return audit

    if not isinstance(data, dict) or "streams" not in data:
        audit.warnings.append("response missing 'streams' key")
        audit.health = "WARN"
        return audit

    streams_raw = data["streams"]
    if not isinstance(streams_raw, list):
        audit.warnings.append(f"'streams' is {type(streams_raw).__name__}, expected list")
        audit.health = "WARN"
        return audit

    audit.stream_count = len(streams_raw)
    if audit.stream_count == 0:
        audit.warnings.append("returned 0 streams for the test query")
        audit.health = "WARN"
        return audit

    # 5) Inspect first stream shape
    first = streams_raw[0]
    audit.sample_name = str(first.get("name", ""))[:60]
    audit.sample_title = str(first.get("title", ""))[:60]
    audit.sample_has_infohash = bool(first.get("infoHash"))
    audit.sample_has_url = bool(first.get("url"))

    if not audit.sample_has_infohash and not audit.sample_has_url:
        audit.warnings.append("first stream has neither infoHash nor url — cannot be downloaded")
        audit.health = "WARN"
        return audit

    # 6) Run the stream through the real filter
    stream = StreamInfo(
        name=first.get("name"),
        title=first.get("title"),
        url=first.get("url"),
        info_hash=first.get("infoHash"),
        file_idx=first.get("fileIdx"),
        sources=first.get("sources"),
        addon_name=name,
        addon_url=instance.get_url(api_key=None),
        filename=(first.get("behaviorHints") or {}).get("filename"),
    )
    result = stream_download.select_quality_streams(
        [stream],
        "1080p",
        target_season=TEST_SEASON,
        target_episode=TEST_EPISODE,
        title=TEST_TITLE,
        target_imdb_id=TEST_IMDB,
    )
    audit.sample_passed_filter = bool(result)
    if not audit.sample_passed_filter:
        # Distinguish "correctly rejected" (wrong show / wrong episode)
        # from "wrongly rejected" (looks like valid shape but filter
        # refused it).  Wrong-show/wrong-episode rejection is the
        # filter working as designed; the addon returned bad data.
        combined = (audit.sample_name + " " + (audit.sample_title or "")).lower()
        target_title = "One Piece"
        wrong_show = target_title.lower() not in combined and any(
            s in combined for s in ("south park", "random", "bobs", "castle", "cops", "naruto")
        )
        advisory = any(
            marker in combined
            for marker in (
                "configure this addon", "kindly configure",
                "elfhosted addons disabled", "⛔", "ℹ",
            )
        )
        no_metadata = (
            not audit.sample_has_infohash
            and not audit.sample_has_url
        )
        if wrong_show:
            audit.warnings.append(
                f"first stream is wrong show (sample: {audit.sample_name!r}) — filter correctly rejected"
            )
        elif advisory:
            audit.warnings.append(
                f"first stream is advisory/config message — filter correctly rejected"
            )
        elif no_metadata:
            audit.warnings.append(
                "first stream has neither infoHash nor url — non-downloadable (filter correctly rejected)"
            )
        else:
            audit.warnings.append(
                "first stream REJECTED by filter — addon text shape may be incompatible"
            )
        audit.health = "WARN"
        return audit

    audit.health = "PASS"
    return audit


def _print_report(audits: list[AddonAudit]) -> None:
    by_health: dict[str, list[AddonAudit]] = {k: [] for k in ("PASS", "WARN", "FAIL", "UNKNOWN")}
    for a in audits:
        by_health.setdefault(a.health, []).append(a)

    print("\n# Addon Audit Report")
    print(f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Test query: {TEST_TITLE} S{TEST_SEASON:02d}E{TEST_EPISODE:02d}  (IMDB {TEST_IMDB})")
    print(f"Timeout per addon: {TIMEOUT}s\n")
    print(f"Total addons audited: {len(audits)}")
    for k in ("PASS", "WARN", "FAIL"):
        print(f"  {k}: {len(by_health.get(k, []))}")

    print("\n## PASS\n")
    for a in sorted(by_health["PASS"], key=lambda x: x.name.lower()):
        print(f"- **{a.name}**  —  {a.stream_count} streams, {a.response_time_ms}ms  "
              f"[{a.base_url}]")

    print("\n## WARN\n")
    for a in sorted(by_health["WARN"], key=lambda x: x.name.lower()):
        print(f"\n### {a.name}")
        print(f"- URL: `{a.base_url}`")
        print(f"- class: `{a.class_path}`")
        if a.manifest_status is not None:
            print(f"- manifest.json: {a.manifest_status}, latency: {a.response_time_ms}ms")
        for w in a.warnings:
            print(f"  - WARN: {w}")
        for i in a.info:
            print(f"  - INFO: {i}")
        if a.stream_count:
            print(f"- sample: name={a.sample_name!r}, title={a.sample_title!r}, "
                  f"infoHash={a.sample_has_infohash}, url={a.sample_has_url}, "
                  f"passed_filter={a.sample_passed_filter}")

    print("\n## FAIL\n")
    for a in sorted(by_health["FAIL"], key=lambda x: x.name.lower()):
        print(f"\n### {a.name}")
        print(f"- URL: `{a.base_url}`")
        print(f"- class: `{a.class_path}`")
        for e in a.errors:
            print(f"  - ERROR: {e}")


if __name__ == "__main__":
    classes = _discover_addon_classes()
    print(f"Discovered {len(classes)} addon classes. Auditing...\n")
    audits: list[AddonAudit] = []
    for i, (name, cls) in enumerate(classes, 1):
        print(f"[{i:>3}/{len(classes)}] {name:<30} ", end="", flush=True)
        a = _audit_one(name, cls)
        audits.append(a)
        flag = {"PASS": "✓", "WARN": "!", "FAIL": "✗", "UNKNOWN": "?"}[a.health]
        print(f"{flag} {a.health:<5} streams={a.stream_count:>3}  {a.base_url}")

    _print_report(audits)
