"""RealDebrid torrent resolving helpers."""
import time

import httpx

from .settings import settings


def resolve_torrent_with_debrid(info_hash: str, file_idx: int | None = None) -> str | None:
    """Resolve torrent via RealDebrid to get direct download URL."""
    if not settings.REAL_DEBRID_API_KEY:
        print("    ERROR: No RealDebrid API key configured!")
        return None

    print(f"    Using RD key: {settings.REAL_DEBRID_API_KEY[:10]}...")
    base_url = "https://api.real-debrid.com/rest/1.0"
    headers = {"Authorization": f"Bearer {settings.REAL_DEBRID_API_KEY}"}

    try:
        print("    Adding magnet to RealDebrid...")
        torrent_response = httpx.post(
            f"{base_url}/torrents/addMagnet",
            headers=headers,
            data={"magnet": f"magnet:?xt=urn:btih:{info_hash}"},
            timeout=60,
        )
        if torrent_response.status_code != 201:
            print(f"    Failed to add magnet: {torrent_response.status_code} - {torrent_response.text[:100]}")
            return None

        torrent_id = torrent_response.json()["id"]
        print(f"    Torrent ID: {torrent_id}")

        print("    Selecting files...")
        httpx.post(
            f"{base_url}/torrents/selectFiles/{torrent_id}",
            headers=headers,
            data={"files": str(file_idx) if file_idx else "all"},
            timeout=30,
        )

        print("    Waiting for download (checking every 5s)...")
        for _ in range(60):
            info_response = httpx.get(
                f"{base_url}/torrents/info/{torrent_id}",
                headers=headers,
                timeout=30,
            )
            if info_response.status_code == 200:
                download_url = _download_url_from_torrent_info(info_response.json(), file_idx)
                if download_url is not False:
                    return download_url
            time.sleep(5)

        print("    Timeout waiting for download")
    except Exception as e:
        print(f"RealDebrid error: {e}")

    return None


def _download_url_from_torrent_info(info: dict, file_idx: int | None) -> str | None | bool:
    status = info["status"]
    print(f"    Status: {status}")

    if status == "downloaded":
        files = info.get("files", [])
        if not files:
            print("    No files in torrent")
            return None
        for file in files:
            if file_idx is None or file["id"] == file_idx:
                links = file.get("links", [])
                if links:
                    print("    Got download link!")
                    return links[0]
        print("    Files found but no links (not cached)")
        return None

    if status in ["error", "virus", "duplicate"]:
        print(f"    Failed: {status}")
        return None

    return False
