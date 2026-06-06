"""Dubbindo – dubbed content in multiple languages."""

from ...base import HttpAddon


class DubbindoAddon(HttpAddon):
    """Dubbindo – dubbed content in multiple languages."""

    name = "Dubbindo"
    base_url = "https://f7094476a780-dubbindo.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url