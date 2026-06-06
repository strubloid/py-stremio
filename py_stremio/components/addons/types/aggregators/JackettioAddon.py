"""Jackettio – connects to a Jackett instance for tracker access."""

from ...base import HttpAddon


class JackettioAddon(HttpAddon):
    """Jackettio – connects to a Jackett instance for tracker access."""

    name = "Jackettio"
    base_url = "https://jackettio.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url