"""FreeMium TV – Spanish/Latin American TV streaming."""
from ...base import HttpAddon


class FreeMiumTVAddon(HttpAddon):
    """FreeMium TV – Spanish/Latin and World TV streaming service."""

    name = "FreeMium TV"
    base_url = "https://hfreemiumy.surge.sh"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
