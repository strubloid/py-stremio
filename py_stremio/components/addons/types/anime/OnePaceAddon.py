"""One Pace – fan-edit of One Piece that follows the manga pacing."""

from ...base import HttpAddon


class OnePaceAddon(HttpAddon):
    """One Pace – fan-edit of One Piece that follows the manga pacing."""

    name = "OnePace"
    base_url = "https://onepaceaddon-zoropogger.koyeb.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url