"""XtreamPro – IPTV stream aggregator."""

from ...base import HttpAddon


class XtreamProAddon(HttpAddon):
    """XtreamPro – IPTV stream aggregator."""

    name = "XtreamPro"
    base_url = "https://xtreampro.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url