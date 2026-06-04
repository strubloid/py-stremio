"""Public Stremio client facade for stream search and downloads."""
from .addons.models import StreamInfo
from .real_debrid import resolve_torrent_with_debrid
from .settings import settings
from .stremio_addon_search import query_addon_for_streams, search_all_addons_for_streams
from .stremio_ids import build_stremio_id
from .stremio_metadata import get_imdb_id, get_series_imdb_id
from .stream_downloads import (
    build_media_filename,
    can_retry_with_debrid,
    download_stream_to_file,
    resolve_stream_download_url,
    select_quality_streams,
)


def search_and_download(
    title: str,
    imdb_id: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
    preferred_quality: str = "1080p",
    working_addons: list[str] | None = None,
    progress_callback=None,
    bandwidth_limiter=None,
) -> dict:
    """Search addons for a stream and download the first usable result."""
    print(f"    Looking up: {title}" + (f" S{season}E{episode}" if season else ""))

    imdb_id = _resolve_imdb_id(title, imdb_id, season)
    id_type = "series" if season else "movie"
    stremio_id = build_stremio_id(imdb_id, title, season, episode)

    streams, working_urls = search_all_addons_for_streams(id_type, stremio_id, working_addons)

    if not streams:
        print(f"    No streams found for ID: {stremio_id}")
        return {"success": False, "error": "No streams found", "working_urls": working_urls}

    print(f"    Found {len(streams)} streams")
    streams_to_try = select_quality_streams(streams, preferred_quality)

    last_error = None
    for index, stream in enumerate(streams_to_try):
        print(f"    Trying stream {index + 1}/{len(streams_to_try)}: {stream.name[:50]}")

        download_url = resolve_stream_download_url(stream)
        if not download_url:
            continue

        if settings.DRY_RUN:
            return {
                "success": True,
                "filename": build_media_filename(title, season, episode),
                "quality": stream.name,
                "provider": "stremio-dry-run",
                "working_urls": working_urls,
            }

        filename = build_media_filename(title, season, episode, folder_path)
        try:
            download_stream_to_file(download_url, filename, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
            return _success_result(filename, stream, working_urls)
        except Exception as e:
            print(f"    Download error: {e}", flush=True)
            if can_retry_with_debrid(stream, download_url):
                retry_result = _retry_with_real_debrid(stream, filename, working_urls, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
                if retry_result:
                    return retry_result
            last_error = str(e)

    return {
        "success": False,
        "error": f"All streams failed. Last error: {last_error}",
        "working_urls": working_urls,
    }


def _resolve_imdb_id(title: str, imdb_id: str | None, season: int | None) -> str | None:
    if not imdb_id:
        imdb_id = get_series_imdb_id(title, season) if season else get_imdb_id(title)

    if imdb_id:
        print(f"    Found IMDB ID: {imdb_id}")
    else:
        print("    Using title-based search")

    return imdb_id


def _retry_with_real_debrid(stream: StreamInfo, filename: str, working_urls: list[str], progress_callback=None, bandwidth_limiter=None) -> dict | None:
    print("    Retrying with info_hash via RealDebrid...")
    rd_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)
    if not rd_url:
        return None

    try:
        download_stream_to_file(rd_url, filename, "    Download complete via RealDebrid!", progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
        return _success_result(filename, stream, working_urls)
    except Exception as e:
        print(f"    RealDebrid download error: {e}")
        return None


def _success_result(filename: str, stream: StreamInfo, working_urls: list[str]) -> dict:
    return {
        "success": True,
        "filename": filename,
        "quality": stream.name,
        "addon_name": getattr(stream, "addon_name", ""),
        "working_urls": working_urls,
    }
