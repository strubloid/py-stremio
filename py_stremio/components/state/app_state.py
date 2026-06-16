"""Download state management."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
import json
from typing import Any

from py_stremio.utils.atomic_write import atomic_write_json


@dataclass
class DownloadRecord:
    filename: str
    quality: str
    provider: str
    addon_url: str = ""
    server: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    attempts: int = 1


@dataclass
class DownloadState:
    folder_path: Path
    items: dict[str, DownloadRecord] = field(default_factory=dict)
    last_scan: str = field(default_factory=lambda: datetime.now().isoformat())
    total_downloaded: int = 0
    failed_items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_download(self, filename: str, quality: str, provider: str,
                     addon_url: str = "", server: str = "") -> None:
        """Record a successful download.

        `server` is the addon URL that actually served the stream (the same
        data that used to live in `addon_url`).  Both fields are kept for
        backward compatibility so old state files continue to work.
        """
        if server and not addon_url:
            addon_url = server
        elif addon_url and not server:
            server = addon_url
        self.items[filename] = DownloadRecord(
            filename=filename,
            quality=quality,
            provider=provider,
            addon_url=addon_url,
            server=server,
            timestamp=datetime.now().isoformat(),
        )
        self.total_downloaded += 1

    def get_addon_url(self, filename: str) -> str:
        if filename in self.items:
            return self.items[filename].addon_url
        return ""

    def get_server(self, filename: str) -> str:
        """Return the addon URL that served this file, or fallback to addon_url."""
        if filename not in self.items:
            return ""
        record = self.items[filename]
        return record.server or record.addon_url

    def mark_failed(self, item_key: str, error: str, attempt: int):
        self.failed_items[item_key] = {
            "error": error,
            "attempt": attempt,
            "timestamp": datetime.now().isoformat(),
        }

    def is_downloaded(self, filename: str) -> bool:
        return filename in self.items

    def was_attempted(self, item_key: str) -> int:
        if item_key in self.failed_items:
            return self.failed_items[item_key]["attempt"]
        return 0


def load_state(folder_path: Path) -> DownloadState:
    """Load state from folder, creating default if missing."""
    state_path = folder_path / ".download-state.json"
    if not state_path.exists():
        return DownloadState(folder_path=folder_path)
    try:
        with open(state_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        from py_stremio.components.errors import report_error

        report_error(
            context=f"load_state({folder_path.name})",
            exception=exc,
            url=str(state_path),
        )
        # Backup and return fresh state — don't let a corrupted file
        # block the entire pipeline
        backup = state_path.with_suffix(".download-state.json.corrupt")
        try:
            import shutil
            shutil.copy2(state_path, backup)
        except OSError:
            pass
        return DownloadState(folder_path=folder_path)
    items = {}
    for filename, record_data in data.get("items", {}).items():
        # Backward compatibility: old states only have addon_url.
        # Populate server from addon_url if server is missing.
        if "server" not in record_data and record_data.get("addon_url"):
            record_data["server"] = record_data["addon_url"]
        items[filename] = DownloadRecord(**record_data)
    return DownloadState(
        folder_path=folder_path,
        items=items,
        last_scan=data.get("last_scan", ""),
        total_downloaded=data.get("total_downloaded", 0),
        failed_items=data.get("failed_items", {}),
    )


def save_state(folder_path: Path, state: DownloadState) -> None:
    """Save state to file."""
    state_path = folder_path / ".download-state.json"
    data = {
        "items": {k: asdict(v) for k, v in state.items.items()},
        "last_scan": state.last_scan,
        "total_downloaded": state.total_downloaded,
        "failed_items": state.failed_items,
    }
    atomic_write_json(state_path, data, indent=2)
