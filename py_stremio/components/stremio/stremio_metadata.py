"""Metadata lookup helpers for Stremio/Cinemeta."""
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import gzip
import io
import urllib.parse

import httpx


IMDB_TITLE_EPISODE_DATASET_URL = "https://datasets.imdbws.com/title.episode.tsv.gz"


def _search_series(title: str) -> list[dict]:
    query = urllib.parse.quote(title.lower())
    search_url = f"https://v3-cinemeta.strem.io/catalog/series/top/search={query}.json"
    response = httpx.get(search_url, timeout=15)
    if response.status_code != 200:
        return []
    return response.json().get("metas", [])


def _best_series_match(title: str) -> dict | None:
    metas = _search_series(title)
    for meta in metas:
        if meta.get("name", "").lower() == title.lower():
            return meta
    return metas[0] if metas else None


def _video_year(video: dict) -> int | None:
    date_text = video.get("released") or video.get("firstAired")
    if not date_text:
        return None
    try:
        return int(str(date_text)[:4])
    except ValueError:
        return None


def _current_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _video_release_datetime(video: dict) -> datetime | None:
    date_text = video.get("released") or video.get("firstAired")
    if not date_text:
        return None
    try:
        return datetime.fromisoformat(str(date_text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _episode_number(video: dict) -> int:
    return int(video.get("episode") or video.get("number") or 0)


def _is_placeholder_episode(video: dict) -> bool:
    """Return True for empty placeholder rows like 'Episode #4.1' or 'TBA'."""
    season = int(video.get("season") or 0)
    episode = _episode_number(video)
    name = str(video.get("name") or "").strip().casefold()
    placeholder_name = f"episode #{season}.{episode}".casefold()
    has_description = bool((video.get("overview") or video.get("description") or "").strip())
    rating = str(video.get("rating") or "").strip()
    has_external_episode_id = bool(video.get("tvdb_id"))
    placeholder_episode_name = name == placeholder_name and not has_external_episode_id
    tba_name = name in {"tba", "tbd"}
    return (placeholder_episode_name or tba_name) and not has_description and rating in ("", "0", "0.0")


def _is_available_episode(video: dict) -> bool:
    if _is_placeholder_episode(video):
        return False
    release_date = _video_release_datetime(video)
    return release_date is None or release_date <= _current_datetime()


@lru_cache(maxsize=1)
def _load_imdb_max_seasons() -> dict[str, int] | None:
    """Load IMDb parent-series max seasons once for this process."""
    try:
        response = httpx.get(IMDB_TITLE_EPISODE_DATASET_URL, timeout=60)
        if response.status_code != 200:
            return None
        max_seasons: dict[str, int] = {}
        with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as dataset:
            for raw_line in dataset:
                line = raw_line.decode("utf-8", errors="ignore").rstrip("\n")
                _, parent_tconst, season_number, _ = (line.split("\t") + ["", "", "", ""])[:4]
                if not parent_tconst.startswith("tt") or not season_number.isdigit():
                    continue
                max_seasons[parent_tconst] = max(max_seasons.get(parent_tconst, 0), int(season_number))
        return max_seasons
    except Exception as e:
        print(f"  IMDb season lookup error: {e}")
        return None


@lru_cache(maxsize=256)
def get_imdb_max_season(imdb_id: str) -> int | None:
    """Return the highest season listed by IMDb for a series, or None when unavailable.

    Cinemeta can occasionally expose provider/anime-cour season groupings before IMDb
    lists them as real seasons. The IMDb title.episode dataset is the authoritative
    guard used before creating automatic next-season folders.
    """
    max_seasons = _load_imdb_max_seasons()
    if max_seasons is None:
        return None
    return max_seasons.get(imdb_id)


def get_current_year_series_seasons(title: str, year: int) -> list[dict]:
    """Return seasons for a series that have episodes released in the requested year."""
    try:
        search_meta = _best_series_match(title)
        if not search_meta:
            return []
        imdb_id = search_meta.get("imdb_id") or search_meta.get("id")
        if not imdb_id:
            return []

        meta_url = f"https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json"
        response = httpx.get(meta_url, timeout=15)
        if response.status_code != 200:
            return []
        meta = response.json().get("meta", {})
        seasons: dict[int, set[int]] = defaultdict(set)
        for video in meta.get("videos", []):
            season = int(video.get("season") or 0)
            episode = _episode_number(video)
            if season <= 0 or episode <= 0 or _video_year(video) != year or not _is_available_episode(video):
                continue
            seasons[season].add(episode)
        imdb_max_season = get_imdb_max_season(imdb_id)
        if imdb_max_season is None:
            return []

        return [
            {
                "imdb_id": meta.get("imdb_id") or imdb_id,
                "title": meta.get("name") or search_meta.get("name") or title,
                "season": season,
                "episode_count": max(episodes),
                "available_episodes": sorted(episodes),
            }
            for season, episodes in sorted(seasons.items())
            if season <= imdb_max_season
        ]
    except Exception as e:
        print(f"  Current-year season lookup error: {e}")
        return []


def get_imdb_id(title: str) -> str | None:
    """Search for IMDB ID using Cinemeta."""
    search_url = f"https://cinemeta.strem.io/metadata/{urllib.parse.quote(title.lower().replace(' ', '-'))}"

    try:
        response = httpx.get(search_url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("imdb_id")
    except Exception as e:
        print(f"  IMDB lookup error: {e}")

    return None


def get_series_imdb_id(title: str, season: int) -> str | None:
    """Get IMDB ID for a series by searching Cinemeta catalog."""
    try:
        meta = _best_series_match(title)
        if meta:
            return meta.get("imdb_id") or meta.get("id")
    except Exception as e:
        print(f"  Series IMDB lookup error: {e}")

    return None


def get_series_metadata(title: str, season: int) -> dict | None:
    """Return IMDB ID, canonical title, and available episode count for a season."""
    try:
        search_meta = _best_series_match(title)
        if not search_meta:
            return None

        imdb_id = search_meta.get("imdb_id") or search_meta.get("id")
        if not imdb_id:
            return None

        meta_url = f"https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json"
        response = httpx.get(meta_url, timeout=15)
        if response.status_code != 200:
            return {
                "imdb_id": imdb_id,
                "title": search_meta.get("name") or title,
                "episode_count": None,
                "available_episodes": [],
                "season_exists": None,
            }

        meta = response.json().get("meta", {})
        videos = meta.get("videos", [])

        # IMDb title.episode dataset can lag for long-running anime (e.g. One Piece
        # only shows 1 season there). Don't short-circuit on it — let Cinemeta's
        # episode-level video data have the final say.
        season_episodes = sorted({
            _episode_number(video)
            for video in videos
            if video.get("season") == season and _episode_number(video) > 0 and _is_available_episode(video)
        })
        episode_count = max(season_episodes) if season_episodes else None
        return {
            "imdb_id": meta.get("imdb_id") or imdb_id,
            "title": meta.get("name") or search_meta.get("name") or title,
            "episode_count": episode_count,
            "available_episodes": season_episodes,
            "season_exists": bool(season_episodes),
        }
    except Exception as e:
        print(f"  Series metadata lookup error: {e}")
        return None
