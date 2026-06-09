"""TILL – Jackett/Prowlarr/Zilean aggregator with all debrid."""
from ...base import HttpAddon


class TillAddon(HttpAddon):
    """TILL – Jackett, Prowlarr and Zilean sources with support for Real-Debrid, AllDebrid and Premiumize."""

    name = "TILL"
    base_url = "https://till-8b4w.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
