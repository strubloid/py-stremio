"""ThePirateBay+ – dedicated TPB scraper."""

from ...base import HttpAddon


class ThePirateBayPlusAddon(HttpAddon):
    """ThePirateBay+ – dedicated TPB scraper."""

    name = "ThePirateBay+"
    base_url = "https://thepiratebay-plus.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url