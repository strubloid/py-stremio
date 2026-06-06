"""Argentina TV – free Argentine IPTV channels."""

from ...base import HttpAddon


class ArgentinaTVAddon(HttpAddon):
    """Argentina TV – free Argentine IPTV channels."""

    name = "ArgentinaTV"
    base_url = "https://848b3516657c-argentinatv.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url