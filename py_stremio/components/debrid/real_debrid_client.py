"""RealDebrid torrent resolving helpers."""
import time

import httpx

from py_stremio.components.configs.app_settings import settings


RD_POLL_ATTEMPTS = 6
RD_POLL_INTERVAL_SECONDS = 5


def resolve_torrent_with_debrid(info_hash: str, file_idx: int | None = None) -> str | None:
    """Resolve torrent via RealDebrid to get direct download URL.

    Adds the magnet to RD, selects files, and polls for completion.
    Returns a direct download URL or None on failure.
    All errors are routed through report_error for clean deduplicated output.
    """
    if not settings.REAL_DEBRID_API_KEY:
        return None

    base_url = "https://api.real-debrid.com/rest/1.0"
    headers = {"Authorization": f"Bearer {settings.REAL_DEBRID_API_KEY}"}

    try:
        torrent_response = httpx.post(
            f"{base_url}/torrents/addMagnet",
            headers=headers,
            data={"magnet": f"magnet:?xt=urn:btih:{info_hash}"},
            timeout=60,
        )
        if torrent_response.status_code != 201:
            from py_stremio.components.errors import report_error

            report_error(
                context=f"realdebrid_magnet({info_hash[:12]})",
                exception=RuntimeError(torrent_response.text[:200]),
                url=f"{base_url}/torrents/addMagnet",
            )
            return None

        torrent_id = torrent_response.json()["id"]

        initial_info_response = httpx.get(
            f"{base_url}/torrents/info/{torrent_id}",
            headers=headers,
            timeout=30,
        )
        files = initial_info_response.json().get("files", []) if initial_info_response.status_code == 200 else []
        selection = _real_debrid_file_selection(files, file_idx)

        select_response = httpx.post(
            f"{base_url}/torrents/selectFiles/{torrent_id}",
            headers=headers,
            data={"files": selection},
            timeout=30,
        )
        if select_response.status_code not in (204, 202):
            from py_stremio.components.errors import report_error

            report_error(
                context=f"realdebrid_select({info_hash[:12]})",
                exception=RuntimeError(select_response.text[:200]),
                url=f"{base_url}/torrents/selectFiles/{torrent_id}",
            )
            return None

        # Poll briefly for completion. Long uncached torrent waits make the UI
        # sit on "waiting for download" for minutes; if RD has not produced a
        # link quickly, try the next stream/addon instead.
        for attempt in range(RD_POLL_ATTEMPTS):
            info_response = httpx.get(
                f"{base_url}/torrents/info/{torrent_id}",
                headers=headers,
                timeout=30,
            )
            if info_response.status_code == 200:
                download_url = _download_url_from_torrent_info(info_response.json(), file_idx)
                if isinstance(download_url, str):
                    return download_url
                if download_url is False:
                    return None
            if attempt < RD_POLL_ATTEMPTS - 1:
                time.sleep(RD_POLL_INTERVAL_SECONDS)
    except Exception as exc:
        from py_stremio.components.errors import report_error

        report_error(
            context=f"realdebrid_resolve({info_hash[:12]})",
            exception=exc,
            url=f"realdebrid://torrents/{info_hash[:12]}",
        )

    return None


def _real_debrid_file_selection(files: list[dict], file_idx: int | None) -> str:
    """Map a Stremio zero-based file index to RealDebrid's file ID.

    Stremio addons expose `fileIdx` as a zero-based position in the torrent.
    RealDebrid's `selectFiles/{torrent_id}` endpoint expects the file's RD `id`,
    which is usually one-based but should be read from the torrent info response.
    """
    if file_idx is None:
        return "all"
    if not files:
        return "all"
    if 0 <= file_idx < len(files):
        rd_id = files[file_idx].get("id")
        if rd_id is not None:
            return str(rd_id)
    return "all"


def _real_debrid_file_for_idx(files: list[dict], file_idx: int | None) -> dict | None:
    """Return the RD file dictionary matching a Stremio zero-based file index."""
    if not files:
        return None
    if file_idx is None:
        return files[0]
    if 0 <= file_idx < len(files):
        return files[file_idx]
    return None


def _download_url_from_torrent_info(info: dict, file_idx: int | None) -> str | None | bool:
    """Check RD torrent info and return download URL when ready.

    Returns:
        str           — direct download URL (cached and ready)
        None          — still downloading or not cached
        False (bool)  — permanent failure (error/virus/duplicate)
    """
    status = info["status"]

    if status == "downloaded":
        file_ = _real_debrid_file_for_idx(info.get("files", []), file_idx)
        if not file_:
            return None
        links = file_.get("links", [])
        if links:
            return links[0]
        return None

    if status in ("error", "virus", "duplicate"):
        return False

    # Still processing (status is "magnet_conversion", "waiting_files_selection",
    # "queued", "downloading", "compressing", "uploading")
    return None
