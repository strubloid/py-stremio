"""HDHub – Brazilian addon with free hosters and torrent support."""

from ....configs.app_settings import settings
from ...base import HttpAddon
from .HDHubAddonConfigurer import HDHubAddonConfigurer


class HDHubAddon(HttpAddon):
    """HDHub – Brazilian addon with free hosters and torrent support."""

    name = "HDHub"
    base_url = "https://hdhub.thevolecitor.qzz.io"

    def get_url(self, api_key: str | None = None) -> str:
        # HDHub accepts a TorBox API key (UUID-shaped) under its ``torbox``
        # config field. ``HDHUB_DEBRID_KEY`` is the dedicated env var; the
        # runtime ``api_key`` parameter is the auto-injected RealDebrid key,
        # which HDHub does not accept, so we deliberately ignore it.
        torbox_key = (
            getattr(settings, "HDHUB_DEBRID_KEY", None)
            or (api_key or "")
        )
        return HDHubAddonConfigurer().configure(self.base_url, torbox_key)