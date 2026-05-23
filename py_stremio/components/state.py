"""Download state management."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
import json
from typing import Any


@dataclass
class DownloadRecord:
    filename: str
    quality: str
    provider: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    attempts: int = 1


@dataclass
class DownloadState:
    folder_path: Path
    items: dict[str, DownloadRecord] = field(default_factory=dict)
    last_scan: str = field(default_factory=lambda: datetime.now().isoformat())
    total_downloaded: int = 0
    failed_items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_download(self, filename: str, quality: str, provider: str):
        self.items[filename] = DownloadRecord(
            filename=filename,
            quality=quality,
            provider=provider,
        )
        self.total_downloaded += 1

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
    with open(state_path) as f:
        data = json.load(f)
    items = {}
    for filename, record_data in data.get("items", {}).items():
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
    with open(state_path, "w") as f:
        json.dump(data, f, indent=2)