"""Comet running on ElfHosted infrastructure."""

from ...base import HttpAddon
from ._comet_build import build_comet_url


class CometElfHostedAddon(HttpAddon):
    """Comet running on ElfHosted infrastructure."""

    name = "Comet-ElfHosted"
    base_url = "https://comet.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return build_comet_url(self.base_url, api_key)