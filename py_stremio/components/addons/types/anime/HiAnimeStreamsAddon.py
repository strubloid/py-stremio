"""HiAnime Streams – anime subtitles streaming with hianime: id prefix."""

from ...base import HttpAddon


class HiAnimeStreamsAddon(HttpAddon):
    """HiAnime Streams – anime streaming addon with embedded subtitles."""

    name = "HiAnime Streams"
    base_url = "https://streamio-hianime.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
