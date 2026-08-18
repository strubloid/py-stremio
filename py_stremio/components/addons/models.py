"""Shared addon data models."""
from dataclasses import dataclass, field


@dataclass
class StreamInfo:
    name: str
    url: str | None = None
    info_hash: str | None = None
    file_idx: int | None = None
    title: str | None = None
    addon_name: str = ""
    filename: str | None = None
    addon_url: str | None = None
    sources: list[str] | None = None
    seeders: int | None = None
    imdb_id: str | None = None
    subtitle_tracks: list[dict] | None = field(default=None, repr=False)
    is_hls: bool = field(default=False, repr=False)
