"""Sootio URL configuration."""

from urllib.parse import quote, urlparse

from ..addon_url_configurer import AddonUrlConfigurer


class SootioAddonConfigurer(AddonUrlConfigurer):
    """Build Sootio URL-encoded config URLs that return RealDebrid playback links."""

    host_match = "sooti.info"

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        return "sooti.info" in parsed.netloc

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/").removesuffix("/manifest.json"))
        return f"{parsed.scheme}://{parsed.netloc}"

    def configure(self, base_url: str, api_key: str) -> str:
        config = {
            "DebridServices": [
                {
                    "provider": "RealDebrid",
                    "apiKey": api_key,
                    "enablePersonalCloud": True,
                    "enableProxy": False,
                    "proxyUrl": "",
                    "proxyPassword": "",
                }
            ],
            "Languages": [],
            "Resolutions": [],
            "Scrapers": [
                "1337x",
                "knaben",
                "torrents-csv",
                "rarbg",
                "limetorrents",
            ],
            "IndexerScrapers": ["stremthru"],
            "ScrapersConfigured": True,
            "minSize": 0,
            "maxSize": 200,
            "ShowCatalog": True,
            "ProxyApplyAll": False,
            "DebridProvider": "RealDebrid",
            "DebridApiKey": api_key,
        }
        encoded = quote(
            __import__("json").dumps(config, separators=(",", ":")),
            safe="",
        )
        return f"{base_url.rstrip('/')}/{encoded}/manifest.json"
