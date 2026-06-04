"""Stream URL resolving and file download helpers."""
import httpx

from .addons.models import StreamInfo
from .real_debrid import resolve_torrent_with_debrid
from .settings import settings


RD_PROXY_PREFIX = "https://torrentio.strem.fun/resolve/"


def select_quality_streams(streams: list, preferred_quality: str) -> list:
    """Prefer matching-quality streams, falling back to the first results."""
    quality_streams = [
        stream
        for stream in streams
        if preferred_quality in stream.name.lower() or "1080p" in stream.name.lower()
    ]
    return quality_streams if quality_streams else streams[:10]


def resolve_stream_download_url(stream: StreamInfo) -> str | None:
    """Resolve a Stremio stream into a direct download URL when possible."""
    download_url = stream.url

    if download_url and download_url.startswith(RD_PROXY_PREFIX):
        print("    Resolving RD proxy URL...")
        download_url = resolve_real_debrid_proxy_url(download_url)

    if stream.info_hash and not download_url:
        if settings.REAL_DEBRID_API_KEY:
            print("    Resolving torrent via RealDebrid...")
            download_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)
            if not download_url:
                print("    RealDebrid failed, trying next...")
        else:
            print("    Torrent requires RealDebrid, trying next...")

    if not download_url:
        print("    No download URL, trying next...")

    return download_url


def resolve_real_debrid_proxy_url(download_url: str) -> str | None:
    """Resolve Torrentio RealDebrid proxy redirects."""
    try:
        response = httpx.get(
            download_url,
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": "Stremio/4.4.168"},
        )
        if response.status_code in (301, 302, 303, 307, 308):
            resolved_url = response.headers.get("location", "")
            print(f"    Resolved to: {resolved_url[:60]}...")
            return resolved_url
        print(f"    RD proxy failed ({response.status_code}), trying info_hash fallback...")
    except Exception as e:
        print(f"    Resolve error: {e}, trying info_hash fallback...")
    return None


def build_media_filename(
    title: str,
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
) -> str:
    """Build the output filename for a movie or episode."""
    if season:
        filename = f"{title}_s{season:02d}e{episode:02d}.mkv"
    else:
        filename = f"{title}.mkv"

    if folder_path:
        return f"{folder_path}/{filename}"
    return filename


def _total_size_from_headers(headers: dict, existing_size: int) -> int:
    content_range = headers.get("content-range") or headers.get("Content-Range")
    if content_range and "/" in content_range:
        total_text = content_range.rsplit("/", 1)[-1]
        if total_text.isdigit():
            return int(total_text)

    content_length = headers.get("content-length") or headers.get("Content-Length")
    if content_length and content_length.isdigit():
        return existing_size + int(content_length)
    return 0


def download_stream_to_file(
    download_url: str,
    filename: str,
    complete_message: str = "    Download complete!",
    progress_callback=None,
    bandwidth_limiter=None,
) -> None:
    """Download a direct stream URL to disk, resuming partial files when possible."""
    from pathlib import Path

    file_path = Path(filename)
    partial_path = file_path.with_name(f"{file_path.name}.part")
    existing_size = partial_path.stat().st_size if partial_path.exists() else 0
    headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}

    print(f"    Downloading to: {filename}", flush=True)
    if existing_size:
        print(f"    Resuming from {existing_size} bytes", flush=True)

    with httpx.stream("GET", download_url, timeout=300, headers=headers) as response:
        response.raise_for_status()
        resumed = bool(existing_size and response.status_code == 206)
        mode = "ab" if resumed else "wb"
        downloaded = existing_size if resumed else 0
        total_size = _total_size_from_headers(response.headers, downloaded)

        if progress_callback:
            progress_callback(downloaded, total_size)

        with open(partial_path, mode) as file:
            for chunk in response.iter_bytes(chunk_size=8192):
                if not chunk:
                    continue
                if bandwidth_limiter:
                    bandwidth_limiter.wait_for(len(chunk))
                file.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_size)

    partial_path.replace(file_path)
    print(complete_message, flush=True)


def can_retry_with_debrid(stream: StreamInfo, download_url: str) -> bool:
    """Return True when a failed direct download can be retried via RealDebrid."""
    return bool(
        stream.info_hash
        and settings.REAL_DEBRID_API_KEY
        and not download_url.startswith("magnet:")
    )
