"""Latin Movies – Spanish/Latino movie streams."""

from ...base import HttpAddon


class LatinMoviesAddon(HttpAddon):
    """Latin Movies – Spanish/Latino movie streams."""

    name = "LatinMovies"
    base_url = "https://latinmovies.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url