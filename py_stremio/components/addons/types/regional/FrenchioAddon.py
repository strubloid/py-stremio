"""Frenchio – French-language content aggregator."""
from ...base import HttpAddon


class FrenchioAddon(HttpAddon):
    """Frenchio | ElfHosted – French-language movie and series streams."""

    name = "Frenchio"
    base_url = "https://frenchio.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
