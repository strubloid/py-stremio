"""AllDebrid torrent resolving helpers."""

import time

import httpx

from py_stremio.components.configs.app_settings import settings


AD_POLL_ATTEMPTS = 6
AD_POLL_INTERVAL_SECONDS = 5


def resolve_torrent_with_alldebrid(info_hash: str, file_idx: int | None = None) -> str | None:
    """Resolve torrent via AllDebrid to get direct download URL.

    Adds the magnet to AllDebrid, selects files, and polls for completion.
    Returns a direct download URL or None on failure.
    """
    if not settings.ALLDEBRID_API_KEY:
        return None

    base_url = "https://api.alldebrid.com/v4"
    headers = {"Authorization": f"Bearer {settings.ALLDEBRID_API_KEY}"}

    try:
        torrent_response = httpx.post(
            f"{base_url}/torrent/magnet/upload",
            headers=headers,
            data={"magnets[]": [f"magnet:?xt=urn:btih:{info_hash}"]},
            timeout=60,
        )
        if torrent_response.status_code != 200:
            from py_stremio.components.errors import report_error

            report_error(
                context=f"alldebrid_magnet({info_hash[:12]})",
                exception=RuntimeError(torrent_response.text[:200]),
                url=f"{base_url}/torrent/magnet/upload",
            )
            return None

        result_data = torrent_response.json()
        if result_data.get("status") != "success":
            return None

        data = result_data.get("data", {})
        magnets = data.get("magnets", [])
        if not magnets:
            return None

        magnet = magnets[0]
        torrent_id = magnet.get("id")
        if not torrent_id:
            return None

        select_response = httpx.post(
            f"{base_url}/torrent/selectFiles/{torrent_id}",
            headers=headers,
            data={"files": "all" if file_idx is None else str(file_idx + 1)},
            timeout=30,
        )

        for attempt in range(AD_POLL_ATTEMPTS):
            info_response = httpx.get(
                f"{base_url}/torrent/info/{torrent_id}",
                headers=headers,
                timeout=30,
            )
            if info_response.status_code == 200:
                info_data = info_response.json()
                if info_data.get("status") == "success":
                    torrent_data = info_data.get("data", {})
                    if torrent_data.get("status") == "Ready":
                        links = torrent_data.get("links", [])
                        if links:
                            for link in links:
                                if link.get("download"):
                                    return link["download"]
                            return links[0].get("download") if links else None
                        return None
                    elif torrent_data.get("status") in ("Dead", "Error"):
                        return None

            if attempt < AD_POLL_ATTEMPTS - 1:
                time.sleep(AD_POLL_INTERVAL_SECONDS)

    except Exception as exc:
        from py_stremio.components.errors import report_error

        report_error(
            context=f"alldebrid_resolve({info_hash[:12]})",
            exception=exc,
            url=f"alldebrid://torrents/{info_hash[:12]}",
        )

    return None


def is_alldebrid_available() -> bool:
    """Check if AllDebrid API is configured and responding."""
    if not settings.ALLDEBRID_API_KEY:
        return False

    base_url = "https://api.alldebrid.com/v4"
    headers = {"Authorization": f"Bearer {settings.ALLDEBRID_API_KEY}"}

    try:
        resp = httpx.get(f"{base_url}/user", headers=headers, timeout=10)
        return resp.status_code == 200 and resp.json().get("status") == "success"
    except Exception:
        return False
