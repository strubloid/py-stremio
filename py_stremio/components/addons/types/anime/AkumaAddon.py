"""Akuma – free anime streams from Gogoanime, Zoro, AnimePahe."""

from ...base import HttpAddon


class AkumaAddon(HttpAddon):
    """Akuma – free anime streams from Gogoanime, Zoro, AnimePahe."""

    name = "Akuma"
    base_url = "https://akuma-delta.vercel.app"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url