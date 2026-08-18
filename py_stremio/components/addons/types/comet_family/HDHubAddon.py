"""HDHub – Brazilian addon with free hosters and torrent support."""
from __future__ import annotations

from ....configs.app_settings import settings
from ....download.hls_download import HLS_PREFERRED_QUALITY_ORDER, HlsDownloader
from ...base import HttpAddon, _is_downloadable_stream_candidate, _is_hls_stream_url
from ...models import StreamInfo
from .HDHubAddonConfigurer import HDHubAddonConfigurer


class HDHubAddon(HttpAddon):
    """HDHub – Brazilian addon with free hosters and torrent support."""

    name = "HDHub"
    base_url = "https://hdhub.thevolecitor.qzz.io"

    # HDHub serves free streams as HLS ``.m3u8`` playlists that Stremio's
    # player can resolve at runtime but py-stremio's single-URL
    # downloader cannot save.  Opting in here re-routes those streams
    # through ``HlsDownloader``, which fetches the master playlist,
    # picks a variant, and concatenates segments into a real video file.
    # Set to ``False`` to fall back to the legacy "drop HLS manifests"
    # behaviour.
    HLS_CAPABLE = True

    # When HDHub returns a master playlist (multiple variants), prefer
    # these qualities in order.  URL-suffix quality
    # (``/resolve/.../1080p.m3u8``) is honoured first regardless of
    # this list.  Adjust to e.g. ``("2160p", "1080p", "720p")`` if your
    # connection can sustain 4K and you prefer max-quality.
    HLS_PREFERRED_QUALITY_ORDER: tuple[str, ...] = HLS_PREFERRED_QUALITY_ORDER

    def get_url(self, api_key=None) -> str:
        # HDHub accepts a TorBox API key (UUID-shaped) under its ``torbox``
        # config field. ``HDHUB_DEBRID_KEY`` is the dedicated env var; the
        # runtime ``api_key`` parameter is the auto-injected RealDebrid key,
        # which HDHub does not accept, so we deliberately ignore it.
        torbox_key = (
            getattr(settings, "HDHUB_DEBRID_KEY", None)
            or (api_key or "")
        )
        return HDHubAddonConfigurer().configure(self.base_url, torbox_key)

    def parse_streams(self, streams_data):
        """Parse HDHub streams, keeping HLS playlists for the HLS downloader.

        HDHub's typical response shape includes ``.m3u8`` URLs flagged
        ``behaviorHints.notWebReady=true``.  The base
        ``_is_downloadable_stream_candidate`` filter drops these, so the
        downloader would never see them.  We pass ``allow_hls=True``
        here so they survive parsing, and tag each surviving stream
        with ``is_hls=True`` so ``download_stream_to_file`` can route
        them to ``HlsDownloader`` instead of treating them as
        single-URL downloads.
        """
        streams: list[StreamInfo] = []
        for stream in streams_data:
            if not _is_downloadable_stream_candidate(stream, allow_hls=True):
                continue
            url = stream.get("url")
            behavior_hints = stream.get("behaviorHints") or {}
            streams.append(
                StreamInfo(
                    name=stream.get("name", "unknown"),
                    url=url,
                    info_hash=None,
                    file_idx=None,
                    title=stream.get("title"),
                    addon_name=self.name,
                    filename=behavior_hints.get("filename"),
                    addon_url=self.get_url(None),
                    sources=stream.get("sources"),
                    seeders=None,
                    imdb_id=None,
                    subtitle_tracks=None,
                    is_hls=_is_hls_stream_url(url),
                )
            )
        return streams

    def create_hls_downloader(self, **kwargs) -> HlsDownloader:
        """Build an ``HlsDownloader`` preconfigured for HDHub.

        All HLS configuration for this addon lives on the class
        (``HLS_PREFERRED_QUALITY_ORDER``) — callers only supply
        per-download context (bandwidth limiter, progress callback,
        stall timeout, thread id).
        """
        kwargs.setdefault(
            "preferred_quality_order", self.HLS_PREFERRED_QUALITY_ORDER
        )
        return HlsDownloader(**kwargs)