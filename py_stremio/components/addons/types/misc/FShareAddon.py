"""FShare – Vietnamese file-sharing hoster streams."""

from ...base import HttpAddon


class FShareAddon(HttpAddon):
    """FShare – Vietnamese file-sharing hoster streams."""

    name = "FShare"
    base_url = "https://fshare.gaixixon.workers.dev"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url