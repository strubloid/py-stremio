"""FrostStream – Brazilian stream aggregator (movies + series)."""

from ...base import HttpAddon


class FrostStreamAddon(HttpAddon):
    """FrostStream – Brazilian stream aggregator with direct MP4/MKV URLs.

    Multi-provider aggregator that resolves movie and series episodes
    to direct video files (MP4 / MKV) hosted on CDNs like
    ``s3.us-east-1.wasabisys.com`` and several regional mirrors.
    Streams are tagged ``behaviorHints.notWebReady=true`` because each
    provider may require custom ``Referer`` / ``Origin`` headers that
    py-stremio does not currently forward — downloads will work for
    providers whose CDN accepts a plain GET, fail for the others.
    """

    name = "FrostStream"
    base_url = "https://froststream.cloutteam.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
