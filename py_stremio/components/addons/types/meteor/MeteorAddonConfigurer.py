"""Meteor for the Weebs URL configuration."""

import base64
import json
from urllib.parse import urlparse

from ..addon_url_configurer import AddonUrlConfigurer


class MeteorAddonConfigurer(AddonUrlConfigurer):
    """Build Meteor base64 config URLs that return RealDebrid playback links."""

    host_match = "midnightignite.me"

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        return "midnightignite.me" in parsed.netloc

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/").removesuffix("/manifest.json"))
        return f"{parsed.scheme}://{parsed.netloc}"

    def configure(self, base_url: str, api_key: str) -> str:
        config = {
            "debridService": "realdebrid",
            "debridApiKey": api_key,
            "cachedOnly": False,
            "skipReleaseFilter": True,
            "removeTrash": False,
            "removeSamples": False,
            "removeAdult": False,
            "exclude3D": False,
            "enableSeaDex": False,
            "enableUsenet": False,
            "usenetCustomEngines": False,
            "enableYourMedia": False,
            "showYourMediaStreams": True,
            "yourMediaSources": [],
            "yourMediaLegacyMode": False,
            "minSeeders": 0,
            "maxResults": 0,
            "maxResultsPerRes": 0,
            "maxSize": 0,
            "resolutions": [],
            "languages": {
                "preferred": ["en", "multi"],
                "required": [],
                "exclude": [],
            },
            "resultFormat": ["title", "quality", "size", "audio"],
            "languageFormat": "flags",
            "sortOrder": [
                "cached", "yourmedia", "seadex", "resolution",
                "quality", "type", "language", "seeders", "size", "pack",
            ],
            "allowP2P": False,
            "excludedSources": [],
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(config, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        return f"{base_url.rstrip('/')}/{encoded}/manifest.json"
