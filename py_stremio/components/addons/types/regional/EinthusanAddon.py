"""Einthusan – South Asian movies & shows (Hindi, Tamil, Telugu, etc.)."""

from ...base import HttpAddon


class EinthusanAddon(HttpAddon):
    """Einthusan – South Asian movies & shows (Hindi, Tamil, Telugu, etc.)."""

    name = "Einthusan"
    base_url = "https://einthusan.asaddon.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url