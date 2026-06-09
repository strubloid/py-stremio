"""Premiumize Library – stream from your Premiumize cloud."""
from ...base import HttpAddon


class PremiumizeAddon(HttpAddon):
    """Premiumize Library – access your Premiumize cloud storage."""

    name = "Premiumize"
    base_url = "https://premiumize.almosteffective.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
