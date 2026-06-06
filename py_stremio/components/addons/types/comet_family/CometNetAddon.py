"""CometNet – Comet's next-gen, actively maintained."""

from ...base import HttpAddon


class CometNetAddon(HttpAddon):
    """CometNet – Comet's next-gen, actively maintained."""

    name = "CometNet"
    base_url = "https://cometnet.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url