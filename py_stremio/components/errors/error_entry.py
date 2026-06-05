"""Error entry model — a single deduplicated error record."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .error_category import ErrorCategory


@dataclass
class ErrorEntry:
    """A deduplicated error record with aggregated metadata.

    Each ErrorEntry represents one unique error category and contains
    the aggregated count, affected addons, and the first traceback.
    """

    category: ErrorCategory
    """The stable error category."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Extracted metadata from the first occurrence (status code, size, etc.)."""

    count: int = 1
    """How many times this error category has been reported."""

    addons: set[str] = field(default_factory=set)
    """Set of affected addon names or identifiers."""

    traceback: str = ""
    """The full traceback string from the first occurrence."""

    def merge(self, addon_name: str | None = None) -> None:
        """Merge another occurrence of the same error into this entry.

        Args:
            addon_name: If provided, the addon/context name to add to affected list.
        """
        self.count += 1
        if addon_name:
            self.addons.add(addon_name)

    @property
    def sorted_addons(self) -> list[str]:
        """Return affected addon names sorted alphabetically."""
        return sorted(self.addons, key=str.casefold)

    @property
    def size_info(self) -> str:
        """Return a human-readable size info string if available."""
        size = self.metadata.get("size_bytes")
        min_bytes = self.metadata.get("min_bytes")
        parts = []
        if size is not None:
            parts.append(f"only {size} bytes")
        if min_bytes is not None:
            parts.append(f"minimum is {min_bytes} bytes")
        return ", ".join(parts) if parts else ""

    @property
    def example_text(self) -> str:
        """Return a one-line example of the error for display."""
        if self.category == ErrorCategory.INVALID_VIDEO_TOO_SMALL and self.size_info:
            return f"Resolved stream is {self.size_info}."
        if self.metadata.get("reason"):
            return f"HTTP {self.metadata.get('status_code', '?')} {self.metadata.get('reason', '')}"
        if self.metadata.get("response_preview"):
            preview = self.metadata.get("response_preview", "")
            return f"Response content: {preview[:80]}"
        return self.category.summary_line

    @property
    def short_label(self) -> str:
        """Return a short label for terminal output."""
        sc = self.metadata.get("status_code")
        if sc:
            return f"[{self.category.value}] x{self.count}"
        return f"[{self.category.value}] x{self.count}"
