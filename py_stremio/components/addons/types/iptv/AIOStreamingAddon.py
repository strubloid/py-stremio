"""AIO Streaming – all-in-one IPTV and VOD aggregator."""

from ...base import HttpAddon


class AIOStreamingAddon(HttpAddon):
    """AIO Streaming – all-in-one IPTV and VOD aggregator."""

    name = "AIOStreaming"
    base_url = "https://3b4bbf5252c4-aio-streaming.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url