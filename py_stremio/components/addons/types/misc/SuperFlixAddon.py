"""SuperFlix – free movie and series streaming."""
from ...base import HttpAddon


class SuperFlixAddon(HttpAddon):
    """SuperFlix – free HTTPS movie and series streaming addon."""

    name = "SuperFlix"
    base_url = "https://23dfbfad8cb2-stremio-addon-superflix.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
