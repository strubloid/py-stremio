"""Built-in Stremio addon definitions."""
from .base import HttpAddon


COMET_CONFIG = "eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOlt7InNlcnZpY2UiOiJyZWFsZGVicmlkIiwiYXBpS2V5IjoiUlVNMktTVVhZWjRSUjVYWTM0UzNIS0pDNEwzT0g2TzI2VE1DRk82SUlIQlNGWlZLVDdBQSJ9XSwiZW5hYmxlVG9ycmVudCI6ZmFsc2UsImRlZHVwbGljYXRlU3RyZWFtcyI6ZmFsc2UsInNjcmFwZURlYnJpZEFjY291bnRUb3JyZW50cyI6ZmFsc2UsImRlYnJpZFN0cmVhbVByb3h5UGFzc3dvcmQiOiIiLCJsYW5ndWFnZXMiOnsicmVxdWlyZWQiOltdLCJhbGxvd2VkIjpbXSwiZXhjbHVkZSI6W10sInByZWZlcnJlZCI6W119LCJyZXNvbHV0aW9ucyI6e30sIm9wdGlvbnMiOnsicmVtb3ZlX3JhbmtzX3VuZGVyIjotMTAwMDAwMDAwMDAsImFsbG93X2VuZ2xpc2hfaW5fbGFuZ3VhZ2VzIjpmYWxzZSwicmVtb3ZlX3Vua25vd25fbGFuZ3VhZ2VzIjpmYWxzZX19"
HDHUB_CONFIG = "eyJ0b3Jib3giOiJ1bnNldCIsInF1YWxpdGllcyI6IjIxNjBwLDEwODBwLDcyMHAiLCJzb3J0IjoiZGVzYyJ9"


class TorrentioAddon(HttpAddon):
    """Torrentio addon with RealDebrid support."""

    name = "Torrentio"
    base_url = "https://torrentio.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/realdebrid={api_key}/"
        return self.base_url


class TorrentioSortSeedersAddon(TorrentioAddon):
    """Torrentio sorted by seeders."""

    name = "Torrentio-SortSeeders"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=seeders|realdebrid={api_key}/"
        return self.base_url


class TorrentioPortugueseAddon(TorrentioAddon):
    """Torrentio with Portuguese language filter."""

    name = "Torrentio-PT"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=portuguese|realdebrid={api_key}/"
        return self.base_url


class MediaFusionAddon(HttpAddon):
    """MediaFusion ElfHosted addon."""

    name = "MediaFusion"
    base_url = "https://mediafusion.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class AnimeKitsuAddon(HttpAddon):
    """Anime Kitsu metadata addon."""

    name = "Anime-Kitsu"
    base_url = "https://anime-kitsu.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class BrazucaTorrentsAddon(HttpAddon):
    """Brazuca Torrents - Brazilian content."""

    name = "Brazuca-Torrents"
    base_url = "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=size|realdebrid={api_key}/"
        return self.base_url


class ThePirateBayPlusAddon(HttpAddon):
    """ThePirateBay+ addon."""

    name = "ThePirateBay+"
    base_url = "https://thepiratebay-plus.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class CustomCometAddon(HttpAddon):
    """Comet addon with debrid support."""

    name = "Comet"
    base_url = "https://comet.feels.legal"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/{COMET_CONFIG}/manifest.json"
        return self.base_url


class HDHubAddon(HttpAddon):
    """HDHub addon."""

    name = "HDHub"
    base_url = "https://hdhub.thevolecitor.qzz.io"

    def get_url(self, api_key: str | None = None) -> str:
        return f"{self.base_url}/{HDHUB_CONFIG}/manifest.json"
