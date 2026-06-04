"""Metadata lookup helpers for Stremio/Cinemeta."""
import urllib.parse

import httpx


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
            return {"imdb_id": imdb_id, "title": search_meta.get("name") or title, "episode_count": None}

        meta = response.json().get("meta", {})
        videos = meta.get("videos", [])
        season_episodes = [
            int(video.get("episode") or video.get("number") or 0)
            for video in videos
            if video.get("season") == season and int(video.get("episode") or video.get("number") or 0) > 0
        ]
        episode_count = max(season_episodes) if season_episodes else None
        return {
            "imdb_id": meta.get("imdb_id") or imdb_id,
            "title": meta.get("name") or search_meta.get("name") or title,
            "episode_count": episode_count,
        }
    except Exception as e:
        print(f"  Series metadata lookup error: {e}")
        return None
