"""Animeo – anime stream aggregator."""

from ...base import HttpAddon


class AnimeoAddon(HttpAddon):
    """Animeo – anime stream aggregator."""

    name = "Animeo"
    base_url = "https://7a625ac658ec-animeo.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url