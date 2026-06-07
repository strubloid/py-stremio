"""Mico-Leão Dublado – Brazilian Portuguese torrent streaming addon."""

from ...base import HttpAddon


class MicoLeaoDubladoAddon(HttpAddon):
    """Mico-Leão Dublado 🇧🇷 – Brazilian Portuguese torrent-based addon for movies."""

    name = "Mico-Leão Dublado 🇧🇷"
    base_url = "https://27a5b2bfe3c0-stremio-brazilian-addon.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
