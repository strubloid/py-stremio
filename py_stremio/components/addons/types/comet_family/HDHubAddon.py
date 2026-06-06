"""HDHub – Brazilian addon with free hosters and torrent support."""

from ...base import HttpAddon
from .HDHubAddonConfigurer import HDHubAddonConfigurer


class HDHubAddon(HttpAddon):
    """HDHub – Brazilian addon with free hosters and torrent support."""

    name = "HDHub"
    base_url = "https://hdhub.thevolecitor.qzz.io"

    def get_url(self, api_key: str | None = None) -> str:
        return HDHubAddonConfigurer().configure(self.base_url, "")