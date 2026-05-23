"""Stremio addon client for discovering and downloading streams."""
import httpx
from dataclasses import dataclass
from typing import Any
import urllib.parse

from .settings import settings


@dataclass
class StreamInfo:
    name: str
    url: str | None = None
    info_hash: str | None = None
    file_idx: int | None = None
    title: str | None = None


def get_imdb_id(title: str) -> str | None:
    """Search for IMDB ID using Cinemeta (metadata addon)."""
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
    query = urllib.parse.quote(title.lower())
    search_url = f"https://v3-cinemeta.strem.io/catalog/series/top/search={query}.json"

    try:
        response = httpx.get(search_url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            metas = data.get("metas", [])
            for meta in metas:
                if meta.get("name", "").lower() == title.lower():
                    return meta.get("imdb_id") or meta.get("id")
            if metas:
                return metas[0].get("imdb_id") or metas[0].get("id")
    except Exception as e:
        print(f"  Series IMDB lookup error: {e}")

    return None


def query_addon_for_streams(
    addon_url: str,
    type_: str,
    id_: str
) -> list[StreamInfo]:
    """Query a Stremio addon for streams."""
    streams = []
    url = f"{addon_url.rstrip('/')}/stream/{type_}/{id_}.json"

    print(f"    Querying: {url}")

    try:
        response = httpx.get(
            url,
            timeout=30,
            headers={"User-Agent": "Stremio/4.4.168", "Accept": "application/json"}
        )
        response.raise_for_status()
        data = response.json()

        for stream in data.get("streams", []):
            name = stream.get("name", "unknown")
            url = stream.get("url")
            info_hash = stream.get("infoHash")
            file_idx = stream.get("fileIdx")

            streams.append(StreamInfo(
                name=name,
                url=url,
                info_hash=info_hash,
                file_idx=file_idx,
                title=stream.get("title"),
            ))
    except httpx.RequestError as e:
        print(f"    Network error: {e}")
    except Exception as e:
        print(f"    Error: {e}")

    return streams


def resolve_torrent_with_debrid(info_hash: str, file_idx: int | None = None) -> str | None:
    """Resolve torrent via RealDebrid to get direct download URL."""
    if not settings.REAL_DEBRID_API_KEY:
        print(f"    ERROR: No RealDebrid API key configured!")
        return None

    print(f"    Using RD key: {settings.REAL_DEBRID_API_KEY[:10]}...")
    base_url = "https://api.real-debrid.com/rest/1.0"

    try:
        print(f"    Adding magnet to RealDebrid...")
        torrent_response = httpx.post(
            f"{base_url}/torrents/addMagnet",
            headers={"Authorization": f"Bearer {settings.REAL_DEBRID_API_KEY}"},
            data={"magnet": f"magnet:?xt=urn:btih:{info_hash}"},
            timeout=60
        )
        if torrent_response.status_code != 201:
            print(f"    Failed to add magnet: {torrent_response.status_code} - {torrent_response.text[:100]}")
            return None

        torrent_data = torrent_response.json()
        torrent_id = torrent_data["id"]
        print(f"    Torrent ID: {torrent_id}")

        print(f"    Selecting files...")
        select_response = httpx.post(
            f"{base_url}/torrents/selectFiles/{torrent_id}",
            headers={"Authorization": f"Bearer {settings.REAL_DEBRID_API_KEY}"},
            data={"files": str(file_idx) if file_idx else "all"},
            timeout=30
        )

        print(f"    Waiting for download (checking every 5s)...")
        for i in range(60):
            info_response = httpx.get(
                f"{base_url}/torrents/info/{torrent_id}",
                headers={"Authorization": f"Bearer {settings.REAL_DEBRID_API_KEY}"},
                timeout=30
            )
            if info_response.status_code == 200:
                info = info_response.json()
                status = info["status"]
                print(f"    Status: {status}")
                if status == "downloaded":
                    files = info.get("files", [])
                    if not files:
                        print(f"    No files in torrent")
                        return None
                    for file in files:
                        if file_idx is None or file["id"] == file_idx:
                            links = file.get("links", [])
                            if links:
                                print(f"    Got download link!")
                                return links[0]
                    print(f"    Files found but no links (not cached)")
                    return None
                elif status in ["error", "virus", "duplicate"]:
                    print(f"    Failed: {status}")
                    return None
            import time
            time.sleep(5)

        print(f"    Timeout waiting for download")
    except Exception as e:
        print(f"RealDebrid error: {e}")

    return None


def build_stremio_id(imdb_id: str | None, title: str, season: int | None = None, episode: int | None = None) -> str:
    """Build Stremio ID from IMDB ID or title."""
    if imdb_id:
        if season and episode:
            return f"{imdb_id}:{season}:{episode}"
        elif season:
            return f"{imdb_id}:{season}"
        return imdb_id

    base_id = title.lower().replace(" ", ".").replace("-", ".")
    if season and episode:
        return f"{base_id}:s{season:02d}e{episode:02d}"
    elif season:
        return f"{base_id}:season-{season}"
    return base_id


def _normalize_addon_url(url: str | None) -> str:
    """Normalize addon URLs so saved working URLs can be de-duplicated."""
    if not url:
        return ""
    return url.strip().rstrip("/").removesuffix("/manifest.json")


def _unique_addon_urls(urls: list[str] | None) -> list[str]:
    unique_urls = []
    seen = set()
    for url in urls or []:
        normalized = _normalize_addon_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_urls.append(normalized)
    return unique_urls


def _configured_addon_url(addon: Any) -> str:
    try:
        url = addon.get_url(getattr(addon, "api_key", None))
    except TypeError:
        url = addon.get_url()
    return _normalize_addon_url(url)


def search_all_addons_for_streams(
    type_: str,
    stremio_id: str,
    working_addons: list[str] | None = None,
    max_addons: int = 3
) -> tuple[list, list[str]]:
    """Search addons for streams. Try known working addons before the remaining addons."""
    from .addons import create_addon_manager, create_addon_manager_from_urls

    all_streams = []
    all_working_urls = []
    searched_urls = set()
    working_urls = _unique_addon_urls(working_addons)

    if working_urls:
        print(f"    First trying {len(working_urls)} known working addons...")
        working_manager = create_addon_manager_from_urls(working_urls)
        w_streams, w_urls = working_manager.search_all_addons_and_collect_working(type_, stremio_id)
        all_streams.extend(w_streams)
        all_working_urls.extend(w_urls)
        searched_urls.update(working_urls)

    manager = create_addon_manager()
    if working_urls:
        remaining_addons = []
        for addon in manager.addons:
            addon_url = _configured_addon_url(addon)
            if not addon_url or addon_url in searched_urls:
                continue
            searched_urls.add(addon_url)
            remaining_addons.append(addon)
        manager.addons = remaining_addons
        print(f"    Searching {len(manager.addons)} remaining addons...")
    else:
        print(f"    Searching all {len(manager.addons)} addons...")

    if manager.addons:
        streams, new_working = manager.search_all_addons_and_collect_working(type_, stremio_id)
        all_streams.extend(streams)
        all_working_urls.extend(new_working)

    return all_streams, _unique_addon_urls(all_working_urls)


def search_and_download(
    title: str,
    imdb_id: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
    preferred_quality: str = "1080p",
    working_addons: list[str] | None = None
) -> dict:
    """Search addon for stream and download."""
    print(f"    Looking up: {title}" + (f" S{season}E{episode}" if season else ""))

    if not imdb_id:
        if season:
            imdb_id = get_series_imdb_id(title, season)
        else:
            imdb_id = get_imdb_id(title)

    if imdb_id:
        print(f"    Found IMDB ID: {imdb_id}")
    else:
        print(f"    Using title-based search")

    id_type = "series" if season else "movie"
    stremio_id = build_stremio_id(imdb_id, title, season, episode)

    streams, working_urls = search_all_addons_for_streams(id_type, stremio_id, working_addons)

    if not streams:
        print(f"    No streams found for ID: {stremio_id}")
        return {"success": False, "error": "No streams found", "working_urls": working_urls}

    print(f"    Found {len(streams)} streams")

    quality_streams = [s for s in streams if preferred_quality in s.name.lower() or "1080p" in s.name.lower()]
    streams_to_try = quality_streams if quality_streams else streams[:10]

    last_error = None
    for i, stream in enumerate(streams_to_try):
        print(f"    Trying stream {i+1}/{len(streams_to_try)}: {stream.name[:50]}")

        download_url = stream.url

        if download_url and download_url.startswith("https://torrentio.strem.fun/resolve/"):
            print(f"    Resolving RD proxy URL...")
            try:
                response = httpx.get(download_url, timeout=30, follow_redirects=False, headers={"User-Agent": "Stremio/4.4.168"})
                if response.status_code in (301, 302, 303, 307, 308):
                    download_url = response.headers.get("location", "")
                    print(f"    Resolved to: {download_url[:60]}...")
                else:
                    print(f"    RD proxy failed ({response.status_code}), trying info_hash fallback...")
                    download_url = None
            except Exception as e:
                print(f"    Resolve error: {e}, trying info_hash fallback...")
                download_url = None

        if stream.info_hash and not download_url:
            if settings.REAL_DEBRID_API_KEY:
                print(f"    Resolving torrent via RealDebrid...")
                download_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)
                if not download_url:
                    print(f"    RealDebrid failed, trying next...")
                    continue
            else:
                print(f"    Torrent requires RealDebrid, trying next...")
                continue

        if not download_url:
            print(f"    No download URL, trying next...")
            continue

        if settings.DRY_RUN:
            return {
                "success": True,
                "filename": f"{title}_s{season:02d}e{episode:02d}.mkv" if season else f"{title}.mkv",
                "quality": stream.name,
                "provider": "stremio-dry-run",
                "working_urls": working_urls
            }

        filename = f"{title}_s{season:02d}e{episode:02d}.mkv" if season else f"{title}.mkv"
        if folder_path:
            filename = f"{folder_path}/{filename}"

        print(f"    Downloading to: {filename}", flush=True)
        print(f"    URL: {download_url[:50]}...", flush=True)

        try:
            with httpx.stream("GET", download_url, timeout=300) as r:
                print(f"    Status: {r.status_code}", flush=True)
                r.raise_for_status()
                with open(filename, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)
            print(f"    Download complete!", flush=True)
            return {"success": True, "filename": filename, "quality": stream.name, "addon_name": stream.addon_name, "working_urls": working_urls}
        except Exception as e:
            print(f"    Download error: {e}", flush=True)
            if stream.info_hash and settings.REAL_DEBRID_API_KEY and not download_url.startswith("magnet:"):
                print(f"    Retrying with info_hash via RealDebrid...")
                rd_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)
                if rd_url:
                    download_url = rd_url
                    try:
                        with httpx.stream("GET", download_url, timeout=300) as r:
                            r.raise_for_status()
                            with open(filename, "wb") as f:
                                for chunk in r.iter_bytes(chunk_size=8192):
                                    f.write(chunk)
                        print(f"    Download complete via RealDebrid!", flush=True)
                        return {"success": True, "filename": filename, "quality": stream.name, "addon_name": stream.addon_name, "working_urls": working_urls}
                    except Exception as e2:
                        print(f"    RealDebrid download error: {e2}")
            last_error = str(e)
            continue

    return {"success": False, "error": f"All streams failed. Last error: {last_error}", "working_urls": working_urls}
