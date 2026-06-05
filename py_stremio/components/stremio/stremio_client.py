"""Public Stremio client facade for stream search and downloads."""
from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.debrid.real_debrid_client import resolve_torrent_with_debrid
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.addons.addon_search_service import (
    search_all_addons_for_streams,
    search_remaining_addons_for_streams,
    search_working_addons_for_streams,
)
from py_stremio.components.stremio.stremio_ids import build_stremio_id
from py_stremio.components.stremio.stremio_metadata import get_imdb_id, get_series_imdb_id
from py_stremio.components.download.stream_download import (
    InvalidVideoDownloadError,
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
    preferred_languages: list[str] | None = None,
    working_addons: list[str] | None = None,
    progress_callback=None,
    bandwidth_limiter=None,
) -> dict:
    """Search addons for a stream and download the first usable result."""
    print(f"    Looking up: {title}" + (f" S{season}E{episode}" if season else ""))

    imdb_id = _resolve_imdb_id(title, imdb_id, season)
    id_type = "series" if season else "movie"
    stremio_id = build_stremio_id(imdb_id, title, season, episode)

    if working_addons:
        cached_streams, cached_working_urls = search_working_addons_for_streams(
            id_type,
            stremio_id,
            working_addons,
        )
        cached_result = _try_download_streams(
            title=title,
            streams=cached_streams,
            working_urls=cached_working_urls,
            season=season,
            episode=episode,
            folder_path=folder_path,
            preferred_quality=preferred_quality,
            preferred_languages=preferred_languages,
            progress_callback=progress_callback,
            bandwidth_limiter=bandwidth_limiter,
        )
        if cached_result.get("success"):
            return cached_result
        print("    Cached server did not complete this item; trying remaining addons...")

        remaining_streams, remaining_working_urls = search_remaining_addons_for_streams(
            id_type,
            stremio_id,
            excluded_addons=working_addons,
        )
        combined_working_urls = [*cached_working_urls, *remaining_working_urls]
        remaining_result = _try_download_streams(
            title=title,
            streams=remaining_streams,
            working_urls=combined_working_urls,
            season=season,
            episode=episode,
            folder_path=folder_path,
            preferred_quality=preferred_quality,
            preferred_languages=preferred_languages,
            progress_callback=progress_callback,
            bandwidth_limiter=bandwidth_limiter,
        )
        if remaining_result.get("success"):
            return remaining_result
        if cached_streams or remaining_streams:
            return remaining_result if remaining_streams else cached_result
        print(f"    No streams found for ID: {stremio_id}")
        return {"success": False, "error": "No streams found", "working_urls": combined_working_urls}

    streams, working_urls = search_all_addons_for_streams(id_type, stremio_id, working_addons)
    return _try_download_streams(
        title=title,
        streams=streams,
        working_urls=working_urls,
        season=season,
        episode=episode,
        folder_path=folder_path,
        preferred_quality=preferred_quality,
        preferred_languages=preferred_languages,
        progress_callback=progress_callback,
        bandwidth_limiter=bandwidth_limiter,
    )


def _try_download_streams(
    title: str,
    streams: list[StreamInfo],
    working_urls: list[str],
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
    preferred_quality: str = "1080p",
    preferred_languages: list[str] | None = None,
    progress_callback=None,
    bandwidth_limiter=None,
) -> dict:
    if not streams:
        return {"success": False, "error": "No streams found", "working_urls": working_urls}

    print(f"    Found {len(streams)} streams")
    streams_to_try = select_quality_streams(
        streams,
        preferred_quality,
        preferred_languages=preferred_languages,
        target_season=season,
        target_episode=episode,
        title=title,
    )
    print(f"    {len(streams_to_try)} usable streams after quality filter")

    last_error = None
    invalid_download_errors = 0
    for index, stream in enumerate(streams_to_try):
        print(f"    Stream {index + 1}/{len(streams_to_try)}: {stream.name[:50]} "
              f"{'(direct URL)' if stream.url else '(info_hash, needs RD)'}", flush=True)

        download_url = resolve_stream_download_url(stream)
        if not download_url:
            print(f"    -> No download URL, trying next", flush=True)
            continue

        if settings.DRY_RUN:
            return {
                "success": True,
                "filename": build_media_filename(title, season, episode),
                "quality": stream.name,
                "provider": "stremio-dry-run",
                "working_urls": working_urls,
                "successful_url": stream.addon_url,
            }

        filename = build_media_filename(title, season, episode, folder_path)
        try:
            download_stream_to_file(download_url, filename, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
            return _success_result(filename, stream, working_urls)
        except InvalidVideoDownloadError as e:
            invalid_download_errors += 1
            print(f"    Invalid video stream: {e}", flush=True)
            from py_stremio.components.errors.error_logger import log_error

            log_error(f"invalid_video({stream.addon_name})", e, stream.url or stream.info_hash or "?")
            if can_retry_with_debrid(stream, download_url):
                retry_result = _retry_with_real_debrid(stream, filename, working_urls, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
                if retry_result:
                    return retry_result
            last_error = str(e)
        except Exception as e:
            print(f"    Download error: {e}", flush=True)
            from py_stremio.components.errors.error_logger import log_error

            log_error(f"download_stream({stream.addon_name})", e, stream.url or stream.info_hash or "?")
            if can_retry_with_debrid(stream, download_url):
                retry_result = _retry_with_real_debrid(stream, filename, working_urls, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
                if retry_result:
                    return retry_result
            last_error = str(e)

    permanent_failure = bool(streams_to_try) and invalid_download_errors == len(streams_to_try)
    return {
        "success": False,
        "error": f"All streams failed. Last error: {last_error}",
        "working_urls": working_urls,
        "permanent_failure": permanent_failure,
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
    if not stream.info_hash:
        return None

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
        "successful_url": getattr(stream, "addon_url", None),
    }
