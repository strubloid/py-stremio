"""Meteor for the Weebs – Comet-family debrid addon with custom config."""

from ...base import HttpAddon
from ._meteor_build import build_meteor_url


class MeteorAddon(HttpAddon):
    """Meteor for the Weebs – Comet-family debrid addon."""

    name = "MeteorForTheWeebs"
    base_url = "https://meteorfortheweebs.midnightignite.me"

    def get_url(self, api_key: str | None = None) -> str:
        return build_meteor_url(self.base_url, api_key)
