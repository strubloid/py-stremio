"""MediaFusion – scrapes public & semi-private trackers plus free hosters."""

from ...base import HttpAddon


class MediaFusionAddon(HttpAddon):
    """MediaFusion – scrapes public & semi-private trackers plus free hosters."""

    name = "MediaFusion"
    base_url = "https://mediafusion.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url