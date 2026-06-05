"""Summary model for grouped error output."""

from __future__ import annotations

from dataclasses import dataclass, field

from .error_entry import ErrorEntry


@dataclass
class ErrorSummary:
    """Aggregated summary of all errors collected during a run."""

    entries: dict[str, ErrorEntry] = field(default_factory=dict)
    """Map of error category value → ErrorEntry."""

    total_count: int = 0
    """Total number of error occurrences across all categories."""

    def add_entry(self, entry: ErrorEntry) -> None:
        """Add or merge a new error entry.

        If an entry with the same category already exists, merge the new
        occurrence into it.
        """
        key = entry.category.value
        existing = self.entries.get(key)
        if existing:
            existing.count += entry.count
            existing.addons.update(entry.addons)
        else:
            self.entries[key] = entry
        self.total_count += entry.count

    @property
    def has_errors(self) -> bool:
        """Return True if any errors were collected."""
        return len(self.entries) > 0

    @property
    def sorted_entries(self) -> list[ErrorEntry]:
        """Return entries sorted by count descending."""
        return sorted(self.entries.values(), key=lambda e: (-e.count, e.category.value))

    def clear(self) -> None:
        """Reset the summary."""
        self.entries.clear()
        self.total_count = 0
