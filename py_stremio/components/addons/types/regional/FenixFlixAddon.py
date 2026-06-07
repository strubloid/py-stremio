"""FenixFlix – Portuguese-language movies and series."""

from ...base import HttpAddon


class FenixFlixAddon(HttpAddon):
    """FENIXFLIX – Portuguese-language addon for movies and series."""

    name = "FENIXFLIX"
    base_url = "https://fenixflix-ur9u.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
