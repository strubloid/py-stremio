"""FigaroCorso – Italian content addon."""

from ...base import HttpAddon


class FigaroCorsoAddon(HttpAddon):
    """FigaroCorso – Italian content addon."""

    name = "FigaroCorso"
    base_url = "https://www.figarocorso.info/stremio"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url