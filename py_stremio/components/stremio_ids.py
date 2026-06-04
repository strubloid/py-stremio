"""Stremio identifier construction."""


def build_stremio_id(
    imdb_id: str | None,
    title: str,
    season: int | None = None,
    episode: int | None = None,
) -> str:
    """Build Stremio ID from IMDB ID or title."""
    if imdb_id:
        if season and episode:
            return f"{imdb_id}:{season}:{episode}"
        if season:
            return f"{imdb_id}:{season}"
        return imdb_id

    base_id = title.lower().replace(" ", ".").replace("-", ".")
    if season and episode:
        return f"{base_id}:s{season:02d}e{episode:02d}"
    if season:
        return f"{base_id}:season-{season}"
    return base_id
