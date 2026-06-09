"""DMM Cast – Stream your RealDebrid cloud library in Stremio."""
from ...base import HttpAddon


class DMMAddon(HttpAddon):
    """DMM Cast for Real-Debrid – stream from your RD cloud."""

    name = "DMM Cast"
    base_url = "https://debridmediamanager.com/api/stremio/default"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
