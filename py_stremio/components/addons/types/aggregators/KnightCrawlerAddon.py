"""KnightCrawler – [DEPRECATED] Use MediaFusion, Comet, or CometNet instead."""

from ...base import HttpAddon


class KnightCrawlerAddon(HttpAddon):
    """KnightCrawler – [DEPRECATED] Use MediaFusion, Comet, or CometNet instead."""

    name = "KnightCrawler"
    base_url = "https://knightcrawler.elfhosted.com"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url