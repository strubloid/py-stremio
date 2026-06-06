"""Easynews+ – streams from Easynews usenet, cached via ElfHosted."""

from ...base import HttpAddon


class EasyNewsPlusAddon(HttpAddon):
    """Easynews+ – streams from Easynews usenet, cached via ElfHosted."""

    name = "EasyNews+"
    base_url = "https://easynewsplus.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url