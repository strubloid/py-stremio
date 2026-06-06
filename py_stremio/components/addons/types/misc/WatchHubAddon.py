"""WatchHub – scrapes multiple free video hosters."""

from ...base import HttpAddon


class WatchHubAddon(HttpAddon):
    """WatchHub – scrapes multiple free video hosters."""

    name = "WatchHub"
    base_url = "https://watchhub.strem.fun"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url