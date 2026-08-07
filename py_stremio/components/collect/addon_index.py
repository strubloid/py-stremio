"""Thread-safe persistent index of all known addon URLs.

Provides O(1) lookups by URL, hostname, or path pattern.
Survives across discovery runs and can be serialized to JSON.
"""

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Iterator
from urllib.parse import urlparse


@dataclass
class IndexedAddon:
    url: str
    hostname: str
    path_pattern: str
    first_seen: datetime
    last_checked: datetime
    is_working: bool | None = None
    consecutive_failures: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "hostname": self.hostname,
            "path_pattern": self.path_pattern,
            "first_seen": self.first_seen.isoformat(),
            "last_checked": self.last_checked.isoformat(),
            "is_working": self.is_working,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IndexedAddon":
        return cls(
            url=data["url"],
            hostname=data["hostname"],
            path_pattern=data["path_pattern"],
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_checked=datetime.fromisoformat(data["last_checked"]),
            is_working=data.get("is_working"),
            consecutive_failures=data.get("consecutive_failures", 0),
            last_error=data.get("last_error"),
        )


class AddonIndex:
    """Thread-safe persistent index of all known addon URLs.

    Provides O(1) lookups by URL, hostname, or pattern.
    Use load_from_file() or load_from_json() to populate.
    Use save_to_json() to persist changes.
    """

    def __init__(self):
        self._by_url: dict[str, IndexedAddon] = {}
        self._by_hostname: dict[str, set[str]] = {}
        self._by_pattern: dict[str, set[str]] = {}
        self._lock = RLock()
        self._modified = False

    def _normalize(self, url: str) -> str:
        """Normalize URL for consistent indexing."""
        return url.strip().rstrip("/").removesuffix("/manifest.json")

    def _strip_variable_parts(self, path: str) -> str:
        """Strip variable parts like RD keys for pattern comparison."""
        cleaned = re.sub(r"/realdebrid=[^/]+", "/realdebrid=*", path)
        cleaned = re.sub(r"/rd=[^/]+", "/rd=*", cleaned)
        cleaned = re.sub(r"/api_key=[^/]+", "/api_key=*", cleaned)
        cleaned = re.sub(r"/[a-f0-9]{32,}", "/*KEY*/", cleaned)
        return cleaned

    def _extract_base_hostname(self, url: str) -> str:
        """Extract base hostname (ignore subdomains)."""
        parts = urlparse(url).netloc.split(".")
        if len(parts) >= 3:
            if parts[-2] in ("com", "io", "net", "org", "fun"):
                return ".".join(parts[-3:]) if len(parts) > 3 else ".".join(parts)
        return ".".join(parts[-2:])

    def _extract_path_pattern(self, url: str) -> str:
        """Extract path pattern without variable parts."""
        path = urlparse(url).path.rstrip("/")
        return self._strip_variable_parts(path)

    # ── O(1) membership tests ─────────────────────────────────────────────

    def has_url(self, url: str) -> bool:
        """Check if URL is already indexed (exact match). O(1)."""
        normalized = self._normalize(url)
        with self._lock:
            return normalized in self._by_url

    def has_hostname(self, hostname: str) -> bool:
        """Check if ANY addon from this hostname is already indexed. O(1)."""
        with self._lock:
            return hostname in self._by_hostname

    def has_pattern(self, path_pattern: str) -> bool:
        """Check if this path pattern already exists. O(1)."""
        with self._lock:
            return path_pattern in self._by_pattern

    def get_by_hostname(self, hostname: str) -> list[IndexedAddon]:
        """Get all addons from a specific hostname. O(k) where k = addons for host."""
        with self._lock:
            urls = self._by_hostname.get(hostname, set())
            return [self._by_url[u] for u in urls if u in self._by_url]

    def get_by_pattern(self, pattern: str) -> list[IndexedAddon]:
        """Get all addons with a specific path pattern. O(k)."""
        with self._lock:
            urls = self._by_pattern.get(pattern, set())
            return [self._by_url[u] for u in urls if u in self._by_url]

    # ── Smart deduplication ───────────────────────────────────────────────

    def is_duplicate(self, url: str) -> tuple[bool, str]:
        """Check if URL is a duplicate.

        Returns (is_duplicate, reason):
          - (True, "exact") — exact URL already exists
          - (True, "hostname+pattern") — same hostname + path pattern exists
          - (True, "pattern") — same path pattern (different hostname) exists
          - (False, "") — genuinely new addon
        """
        normalized = self._normalize(url)
        parsed = urlparse(normalized)
        hostname = parsed.netloc
        path = parsed.path.rstrip("/")
        pattern = self._strip_variable_parts(path)

        with self._lock:
            if normalized in self._by_url:
                return True, "exact"

            for existing_url in self._by_hostname.get(hostname, set()):
                existing_parsed = urlparse(existing_url)
                existing_pattern = self._strip_variable_parts(existing_parsed.path.rstrip("/"))
                if pattern == existing_pattern:
                    return True, "hostname+pattern"

            for existing_url in self._by_pattern.get(pattern, set()):
                if existing_url in self._by_url:
                    return True, "pattern"

            return False, ""

    # ── Mutations ─────────────────────────────────────────────────────────

    def add(self, url: str, is_working: bool | None = None) -> bool:
        """Add URL to index. Returns True if genuinely new, False if duplicate."""
        normalized = self._normalize(url)
        is_dup, _ = self.is_duplicate(normalized)
        if is_dup:
            return False

        parsed = urlparse(normalized)
        hostname = parsed.netloc
        path = parsed.path.rstrip("/")
        pattern = self._strip_variable_parts(path)

        addon = IndexedAddon(
            url=normalized,
            hostname=hostname,
            path_pattern=pattern,
            first_seen=datetime.now(),
            last_checked=datetime.now(),
            is_working=is_working,
        )

        with self._lock:
            self._by_url[normalized] = addon
            self._by_hostname.setdefault(hostname, set()).add(normalized)
            self._by_pattern.setdefault(pattern, set()).add(normalized)
            self._modified = True

        return True

    def add_batch(self, urls: list[str], is_working: bool | None = None) -> int:
        """Add multiple URLs. Returns count of genuinely new addons."""
        new_count = 0
        for url in urls:
            if self.add(url, is_working):
                new_count += 1
        return new_count

    def mark_checked(self, url: str, is_working: bool, error: str | None = None):
        """Update addon status after a check."""
        normalized = self._normalize(url)
        with self._lock:
            if normalized in self._by_url:
                addon = self._by_url[normalized]
                addon.last_checked = datetime.now()
                addon.is_working = is_working
                if not is_working:
                    addon.consecutive_failures += 1
                    addon.last_error = error
                else:
                    addon.consecutive_failures = 0
                    addon.last_error = None
                self._modified = True

    def mark_working(self, url: str):
        """Mark addon as working (success)."""
        self.mark_checked(url, True)

    def mark_failed(self, url: str, error: str | None = None):
        """Mark addon as failed."""
        self.mark_checked(url, False, error)

    def remove(self, url: str) -> bool:
        """Remove URL from index."""
        normalized = self._normalize(url)
        with self._lock:
            if normalized not in self._by_url:
                return False
            addon = self._by_url[normalized]
            self._by_hostname.get(addon.hostname, set()).discard(normalized)
            self._by_pattern.get(addon.path_pattern, set()).discard(normalized)
            del self._by_url[normalized]
            self._modified = True
            return True

    def clear_failures(self, url: str):
        """Clear failure count after a success."""
        normalized = self._normalize(url)
        with self._lock:
            if normalized in self._by_url:
                addon = self._by_url[normalized]
                addon.consecutive_failures = 0
                addon.last_error = None
                self._modified = True

    # ── Queries ────────────────────────────────────────────────────────────

    def get_all_urls(self) -> list[str]:
        """Get all indexed URLs as list."""
        with self._lock:
            return list(self._by_url.keys())

    def get_working_urls(self) -> list[str]:
        """Get only addons confirmed to work."""
        with self._lock:
            return [a.url for a in self._by_url.values() if a.is_working is True]

    def get_failed_urls(self) -> list[str]:
        """Get addons confirmed to be failing."""
        with self._lock:
            return [a.url for a in self._by_url.values() if a.is_working is False]

    def get_untested_urls(self) -> list[str]:
        """Get addons never tested (is_working is None)."""
        with self._lock:
            return [a.url for a in self._by_url.values() if a.is_working is None]

    def get_urls_by_hostname(self, hostname: str) -> list[str]:
        """Get all URLs for a hostname."""
        with self._lock:
            return list(self._by_hostname.get(hostname, set()))

    def get_all_hostnames(self) -> list[str]:
        """Get all unique hostnames in index."""
        with self._lock:
            return list(self._by_hostname.keys())

    def iter_addons(self) -> Iterator[IndexedAddon]:
        """Iterate over all indexed addons."""
        with self._lock:
            return iter(list(self._by_url.values()))

    # ── Persistence ───────────────────────────────────────────────────────

    def to_json(self) -> list[dict]:
        """Serialize index to JSON-compatible list."""
        with self._lock:
            return [a.to_dict() for a in self._by_url.values()]

    def to_json_str(self) -> str:
        """Serialize index to JSON string."""
        return json.dumps(self.to_json(), indent=2)

    @classmethod
    def from_json(cls, data: list[dict]) -> "AddonIndex":
        """Deserialize from JSON list."""
        index = cls()
        for item in data:
            addon = IndexedAddon.from_dict(item)
            index._by_url[addon.url] = addon
            index._by_hostname.setdefault(addon.hostname, set()).add(addon.url)
            index._by_pattern.setdefault(addon.path_pattern, set()).add(addon.url)
        return index

    @classmethod
    def from_json_str(cls, json_str: str) -> "AddonIndex":
        """Deserialize from JSON string."""
        return cls.from_json(json.loads(json_str))

    def save_to_json_file(self, filepath: str | Path) -> None:
        """Save index to JSON file atomically."""
        path = Path(filepath)
        tmp_path = path.with_suffix(".tmp")
        text = self.to_json_str()
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)

    @classmethod
    def load_from_json_file(cls, filepath: str | Path) -> "AddonIndex":
        """Load index from JSON file."""
        path = Path(filepath)
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_json(data)
        except (json.JSONDecodeError, KeyError):
            return cls()

    # ── File loading ─────────────────────────────────────────────────────

    def load_from_file(self, filepath: str | Path) -> int:
        """Load all URLs from file into index. Returns count of new URLs."""
        from urllib.parse import unquote
        new_count = 0
        path = Path(filepath)
        if not path.exists():
            return 0

        with path.open(encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and stripped.startswith("http"):
                    url = unquote(stripped)
                    if self.add(url):
                        new_count += 1
        return new_count

    def save_to_file(self, filepath: str | Path, working_only: bool = False) -> None:
        """Save index to file (urls only, no JSON)."""
        path = Path(filepath)
        lines = ["# Py-Stremio addon manifest URLs", f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "# Auto-generated by AddonIndex\n"]

        with self._lock:
            for addon in sorted(self._by_url.values(), key=lambda a: a.hostname):
                if working_only and addon.is_working is not True:
                    continue
                lines.append(addon.url)

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ── Statistics ────────────────────────────────────────────────────────

    def quick_status(self) -> dict:
        """Get count of addons in each state (instant, no I/O)."""
        with self._lock:
            total = len(self._by_url)
            working = sum(1 for a in self._by_url.values() if a.is_working is True)
            failed = sum(1 for a in self._by_url.values() if a.is_working is False)
            untested = sum(1 for a in self._by_url.values() if a.is_working is None)
            return {
                "total": total,
                "working": working,
                "failed": failed,
                "untested": untested,
            }

    @property
    def is_modified(self) -> bool:
        """Check if index has been modified since last save."""
        return self._modified

    def mark_saved(self):
        """Mark index as saved (clear modified flag)."""
        self._modified = False

    def __len__(self) -> int:
        """Return total count of indexed addons."""
        with self._lock:
            return len(self._by_url)

    def __contains__(self, url: str) -> bool:
        """Support 'url in index' syntax."""
        return self.has_url(url)


# ── Global singleton ──────────────────────────────────────────────────────────

_index: AddonIndex | None = None
_index_lock = RLock()


def get_addon_index() -> AddonIndex:
    """Get the global AddonIndex singleton."""
    global _index
    with _index_lock:
        if _index is None:
            _index = AddonIndex()
        return _index


def reset_addon_index() -> None:
    """Reset the global index (mainly for testing)."""
    global _index
    with _index_lock:
        _index = None


def set_addon_index(index: AddonIndex) -> None:
    """Set the global index singleton."""
    global _index
    with _index_lock:
        _index = index
