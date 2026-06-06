"""Torrin – open-source debrid-aware streaming addon."""

from ...base import HttpAddon


class TorrinAddon(HttpAddon):
    """Torrin – open-source debrid-aware streaming addon."""

    name = "Torrin"
    base_url = "https://torrin.app"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url