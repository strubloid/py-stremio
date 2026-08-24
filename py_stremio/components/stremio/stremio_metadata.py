"""Metadata lookup helpers for Stremio/Cinemeta."""
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import gzip
import io
import json
import re
import time
import urllib.parse

import httpx


IMDB_TITLE_EPISODE_DATASET_URL = "https://datasets.imdbws.com/title.episode.tsv.gz"

# Per-request timeout for Cinemeta/IMDb metadata calls. The previous 15s budget
# was too tight for slow paths (e.g. v3-cinemeta.strem.io CDN edges) and caused
# spurious "Current-year season lookup error: The read operation timed out"
# failures during library sync. 30s comfortably fits normal Cinemeta responses
# while still bounding a single retry.
DEFAULT_METADATA_TIMEOUT = 30.0


def _get_with_retry(url: str, *, timeout: float = DEFAULT_METADATA_TIMEOUT, max_attempts: int = 2, **kwargs) -> httpx.Response:
    """``httpx.get`` with one retry on transient network failures.

    Retries once on ``httpx.TimeoutException`` (read/connect/pool) or
    ``httpx.ConnectError`` so a single slow response doesn't fail the whole
    season lookup. Other exceptions propagate immediately. Tests still
    monkeypatch ``httpx.get`` directly; this wrapper keeps that contract
    because it calls through to the module-level ``httpx.get``.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return httpx.get(url, timeout=timeout, **kwargs)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt + 1 >= max_attempts:
                raise
            time.sleep(0.5)
    raise last_exc  # pragma: no cover


def _search_series(title: str) -> list[dict]:
    query = urllib.parse.quote(title.lower())
    search_url = f"https://v3-cinemeta.strem.io/catalog/series/top/search={query}.json"
    response = _get_with_retry(search_url)
    if response.status_code != 200:
        return []
    return response.json().get("metas", [])


def _best_series_match(title: str) -> dict | None:
    metas = _search_series(title)
    for meta in metas:
        if meta.get("name", "").lower() == title.lower():
            return meta
    return metas[0] if metas else None


def _search_movies(title: str) -> list[dict]:
    query = urllib.parse.quote(title.lower())
    search_url = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={query}.json"
    response = _get_with_retry(search_url)
    if response.status_code != 200:
        return []
    return response.json().get("metas", [])


def _best_movie_match(title: str) -> dict | None:
    metas = _search_movies(title)
    exact = [meta for meta in metas if str(meta.get("name") or "").casefold() == title.casefold()]
    return (exact or metas or [None])[0]


def _normalize_language_values(value) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, dict):
        values = [value.get("name") or value.get("text") or value.get("@value")]
    elif isinstance(value, list):
        values = [
            item if isinstance(item, str) else item.get("name") or item.get("text") or item.get("@value")
            for item in value if isinstance(item, (str, dict))
        ]
    else:
        values = []
    return list(dict.fromkeys(str(item).strip().casefold() for item in values if item and str(item).strip()))


def get_imdb_movie_languages(imdb_id: str) -> list[str]:
    """Read a movie's language list from IMDb's public title markup."""
    try:
        response = _get_with_retry(
            f"https://www.imdb.com/title/{imdb_id}/",
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
        )
        if response.status_code != 200:
            return []
        for raw_json in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', response.text, flags=re.DOTALL
        ):
            try:
                languages = _normalize_language_values(json.loads(raw_json).get("inLanguage"))
            except json.JSONDecodeError:
                continue
            if languages:
                return languages
    except Exception:
        pass
    return []


def get_movie_metadata(title: str, imdb_id: str | None = None) -> dict | None:
    """Resolve one movie folder's canonical title, IMDb ID, and IMDb languages."""
    try:
        match = _best_movie_match(title)
        resolved_id = imdb_id or (match or {}).get("imdb_id") or (match or {}).get("id")
        if not resolved_id:
            return None
        return {
            "imdb_id": resolved_id,
            "title": (match or {}).get("name") or title,
            "languages": get_imdb_movie_languages(resolved_id),
        }
    except Exception:
        return None


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

    # Rows named exactly "Episode #N.M" are a Cinemeta convention for an
    # announced season that has no real episode data yet. The release date
    # on these rows is a placeholder stamp (often 2026-01-01 or similar) and
    # is not a real air-date signal. Always treat them as placeholders.
    if placeholder_episode_name and not has_description and rating in ("", "0", "0.0"):
        return True

    # For TBA/TBD rows, a release date in the past means the episode has
    # aired even if Cinemeta hasn't updated the name/description/rating yet.
    release_date = _video_release_datetime(video)
    if release_date is not None and release_date <= _current_datetime():
        return False

    return tba_name and not has_description and rating in ("", "0", "0.0")


def _is_available_episode(video: dict) -> bool:
    if _is_placeholder_episode(video):
        return False
    release_date = _video_release_datetime(video)
    return release_date is None or release_date <= _current_datetime()


@lru_cache(maxsize=1)
def _load_imdb_max_seasons() -> dict[str, int] | None:
    """Load IMDb parent-series max seasons once for this process."""
    try:
        response = _get_with_retry(IMDB_TITLE_EPISODE_DATASET_URL, timeout=60)
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
        response = _get_with_retry(meta_url, follow_redirects=True)
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
    """Resolve a movie IMDb ID from Cinemeta's movie catalog."""
    metadata = get_movie_metadata(title)
    return metadata.get("imdb_id") if metadata else None


def get_series_imdb_id(title: str, season: int) -> str | None:
    """Get IMDB ID for a series by searching Cinemeta catalog."""
    try:
        meta = _best_series_match(title)
        if meta:
            return meta.get("imdb_id") or meta.get("id")
    except Exception as e:
        print(f"  Series IMDB lookup error: {e}")

    return None


def _series_metadata_from_search_meta(search_meta: dict, title: str, season: int) -> dict | None:
    """Fetch episode metadata for one Cinemeta search result."""
    imdb_id = search_meta.get("imdb_id") or search_meta.get("id")
    if not imdb_id:
        return None

    meta_url = f"https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json"
    response = _get_with_retry(meta_url, follow_redirects=True)
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


def get_series_metadata(title: str, season: int) -> dict | None:
    """Return IMDB ID, canonical title, and available episode count for a season."""
    try:
        metas = _search_series(title)
        if not metas:
            return None

        exact = [m for m in metas if m.get("name", "").lower() == title.lower()]
        ordered_metas = exact + [m for m in metas if m not in exact]
        first_result: dict | None = None
        for search_meta in ordered_metas:
            result = _series_metadata_from_search_meta(search_meta, title, season)
            if result is None:
                continue
            if first_result is None:
                first_result = result
            if result.get("season_exists"):
                return result
        return first_result
    except Exception as e:
        print(f"  Series metadata lookup error: {e}")
        return None
