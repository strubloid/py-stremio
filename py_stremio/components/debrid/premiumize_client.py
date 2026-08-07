"""Premiumize.debrid torrent resolving helpers."""

import time

import httpx

from py_stremio.components.configs.app_settings import settings


PMZ_POLL_ATTEMPTS = 6
PMZ_POLL_INTERVAL_SECONDS = 5


def resolve_torrent_with_premiumize(info_hash: str, file_idx: int | None = None) -> str | None:
    """Resolve torrent via Premiumize.me to get direct download URL.

    Adds the magnet to Premiumize, selects files, and polls for completion.
    Returns a direct download URL or None on failure.
    """
    if not settings.PREMIUMIZE_API_KEY:
        return None

    base_url = "https://api.premiumize.me"
    headers = {"Authorization": f"Bearer {settings.PREMIUMIZE_API_KEY}"}

    try:
        torrent_response = httpx.post(
            f"{base_url}/torrent/addMagnet",
            headers=headers,
            data={"magnet": f"magnet:?xt=urn:btih:{info_hash}"},
            timeout=60,
        )
        if torrent_response.status_code not in (200, 201):
            from py_stremio.components.errors import report_error

            report_error(
                context=f"premiumize_magnet({info_hash[:12]})",
                exception=RuntimeError(torrent_response.text[:200]),
                url=f"{base_url}/torrent/addMagnet",
            )
            return None

        result_data = torrent_response.json()
        if result_data.get("status") != "success":
            return None

        torrent_id = result_data.get("id")
        if not torrent_id:
            return None

        for attempt in range(PMZ_POLL_ATTEMPTS):
            info_response = httpx.get(
                f"{base_url}/torrent/info/{torrent_id}",
                headers=headers,
                timeout=30,
            )
            if info_response.status_code == 200:
                info_data = info_response.json()
                if info_data.get("status") == "finished":
                    files = info_data.get("files", [])
                    if file_idx is not None and 0 <= file_idx < len(files):
                        file_info = files[file_idx]
                    else:
                        file_info = max(files, key=lambda f: f.get("size", 0)) if files else None

                    if file_info and file_info.get("link"):
                        return file_info["link"]

                    return None
                elif info_data.get("status") == "error":
                    return None

            if attempt < PMZ_POLL_ATTEMPTS - 1:
                time.sleep(PMZ_POLL_INTERVAL_SECONDS)

    except Exception as exc:
        from py_stremio.components.errors import report_error

        report_error(
            context=f"premiumize_resolve({info_hash[:12]})",
            exception=exc,
            url=f"premiumize://torrents/{info_hash[:12]}",
        )

    return None


def is_premiumize_available() -> bool:
    """Check if Premiumize API is configured and responding."""
    if not settings.PREMIUMIZE_API_KEY:
        return False

    base_url = "https://api.premiumize.me"
    headers = {"Authorization": f"Bearer {settings.PREMIUMIZE_API_KEY}"}

    try:
        resp = httpx.get(f"{base_url}/account/info", headers=headers, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False
