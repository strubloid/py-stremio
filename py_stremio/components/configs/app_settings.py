"""Application settings loaded from environment variables."""
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# ``load_dotenv()`` with no arguments only looks at the current
# working directory.  That breaks the network-share workflow: the
# source tree is mounted somewhere the user can ``cd`` into, but
# ``py-stremio`` may be invoked from any other shell (or via a cron
# job whose cwd is ``$HOME``).  To make the .env always reachable,
# we try several locations in order and stop at the first hit.
#
# Lookup order (first hit wins, then ``override=False`` so the shell
# environment always wins over the .env file):
#
#   1. ``$PY_STREMIO_ENV`` if set (explicit override for power users)
#   2. The current working directory (the default ``load_dotenv`` behaviour)
#   3. The project root — where ``pyproject.toml`` lives, which is
#      where ``.env`` normally sits on the network share
#   4. The directory that contains this source file
#   5. The user's home directory (``~/.env``) as a last resort
#
# The selected file is echoed to stderr (and also exposed via
# ``SETTINGS_DOTENV_PATH`` for ``--show-config``) so a user whose
# settings look wrong can immediately see which file was read.
import os
import sys
from pathlib import Path as _Path

_THIS_DIR = _Path(__file__).resolve().parent
# ``__file__`` is .../py_stremio/components/configs/app_settings.py,
# so the project root is three levels up, not two.  Walk up until we
# find a directory that contains ``pyproject.toml`` (cheap heuristic
# for "this is the repo root") instead of hard-coding a depth.
_PROJECT_ROOT = _THIS_DIR
while _PROJECT_ROOT != _PROJECT_ROOT.parent:
    if (_PROJECT_ROOT / "pyproject.toml").is_file():
        break
    _PROJECT_ROOT = _PROJECT_ROOT.parent

# Module-level so other code (``--show-config``) can read which file
# was actually used.  ``None`` when no .env was found and the
# hardcoded defaults are in effect.
SETTINGS_DOTENV_PATH: _Path | None = None

_DOTENV_CANDIDATES: list[_Path] = []
_explicit = os.environ.get("PY_STREMIO_ENV")
if _explicit:
    _DOTENV_CANDIDATES.append(_Path(_explicit).expanduser())
_DOTENV_CANDIDATES.extend([
    _Path.cwd() / ".env",
    _PROJECT_ROOT / ".env",
    _THIS_DIR / ".env",
    _Path.home() / ".env",
])

for _candidate in _DOTENV_CANDIDATES:
    if _candidate.is_file():
        load_dotenv(_candidate, override=False)
        SETTINGS_DOTENV_PATH = _candidate
        # Surface the path in stderr so a user whose settings look
        # wrong can see exactly which .env was read.  Kept terse so
        # it does not pollute the normal interactive banner.
        print(
            f"[py-stremio] loaded .env from {_candidate}",
            file=sys.stderr,
        )
        break


@dataclass
class Settings:
    ROOT_FOLDER: Path = field(default_factory=lambda: Path(os.getenv("ROOT_FOLDER") or os.getenv("ROOT_DOWNLOAD_FOLDER", "/home/strubloid/stremio-downloads")))
    SERIES_FOLDER: Path = field(init=False)
    MOVIES_FOLDER: Path = field(init=False)

    REAL_DEBRID_API_KEY: str | None = field(default_factory=lambda: os.getenv("REAL_DEBRID_API_KEY", "").strip('"').strip("'"))
    PREMIUMIZE_API_KEY: str | None = field(default_factory=lambda: os.getenv("PREMIUMIZE_API_KEY", "").strip('"').strip("'"))
    ALLDEBRID_API_KEY: str | None = field(default_factory=lambda: os.getenv("ALLDEBRID_API_KEY", "").strip('"').strip("'"))
    # HDHub-specific debrid key. HDHub accepts a TorBox API key (UUID format)
    # in its ``torbox`` config field. Without a key, HDHub falls back to HLS
    # manifest placeholders that py-stremio cannot download — the HLS filter
    # in addon base discards them. Set this to a TorBox key to receive
    # direct video URLs from HDHub instead. RealDebrid is intentionally not
    # routed here because HDHub does not accept it.
    HDHUB_DEBRID_KEY: str | None = field(default_factory=lambda: os.getenv("HDHUB_DEBRID_KEY", "").strip('"').strip("'"))
    MAX_DOWNLOAD_ATTEMPTS: int = field(default_factory=lambda: int(os.getenv("MAX_DOWNLOAD_ATTEMPTS", "5")))
    LIMIT_EPISODES: int = field(default_factory=lambda: int(os.getenv("LIMIT_EPISODES", "0")))
    MIN_COMPLETED_VIDEO_SIZE_MB: int = field(default_factory=lambda: int(os.getenv("MIN_COMPLETED_VIDEO_SIZE_MB", "100")))
    DOWNLOAD_THREADS: int = field(default_factory=lambda: int(os.getenv("DOWNLOAD_THREADS", "2")))
    DOWNLOAD_STALL_TIMEOUT: float = field(default_factory=lambda: float(os.getenv("DOWNLOAD_STALL_TIMEOUT", "60")))
    VALIDATE_DOWNLOAD_STRUCTURE: bool = field(default_factory=lambda: os.getenv("VALIDATE_DOWNLOAD_STRUCTURE", "true").lower() in ("true", "1", "yes"))
    METADATA_CACHE_HOURS: int = field(default_factory=lambda: int(os.getenv("METADATA_CACHE_HOURS", "24")))
    INTERNET_SPEED_LIMIT: int = field(default_factory=lambda: int(os.getenv("INTERNET_SPEED_LIMIT", "100")))
    INTERNET_MAX_SPEED_MBPS: float = field(default_factory=lambda: float(os.getenv("INTERNET_MAX_SPEED_MBPS", "100")))
    DRY_RUN: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes"))

    # How to download HLS ``.m3u8`` streams once one is found:
    #   ``"ffmpeg"``   — shell out to ``ffmpeg -i <url> -c copy <out>``.
    #                    Handles every HLS variant (encrypted segments,
    #                    discontinuity tags, byte-range / init segments,
    #                    live edge, etc.) and is the recommended option.
    #                    Falls back to ``"segment"`` if ffmpeg is not
    #                    installed and a warning is emitted.
    #   ``"segment"``  — pure-Python downloader that fetches the
    #                    playlist, picks a variant, downloads each
    #                    ``.ts``/``.m4s`` segment and concatenates
    #                    them.  No external dependency but limited to
    #                    unencrypted playlists.
    HLS_DOWNLOAD_METHOD: str = field(default_factory=lambda: os.getenv("HLS_DOWNLOAD_METHOD", "ffmpeg").lower().strip())

    PREFERRED_LANGUAGES: list[str] = field(default_factory=lambda: [
        lang.strip() for lang in os.getenv("PREFERRED_LANGUAGES", "english").split(",") if lang.strip()
    ])

    STREMIO_ADDON_URL: str | None = field(default_factory=lambda: os.getenv("STREMIO_ADDON_URL"))
    STREMIO_ADDON_URL_BASE: str = field(default_factory=lambda: os.getenv("STREMIO_ADDON_URL_BASE") or "https://torrentio.strem.fun")

    # Local torrent proxy for fast RD cached content resolution.
    # When set, resolve_stream_download_url tries this proxy first before
    # the full RealDebrid API flow. Format: http://127.0.0.1:11470
    TORRENT_PROXY_URL: str | None = field(default_factory=lambda: os.getenv("TORRENT_PROXY_URL"))

    @property
    def effective_addon_url(self) -> str:
        """Get the effective addon URL with RD key if configured."""
        if self.STREMIO_ADDON_URL:
            return self.STREMIO_ADDON_URL
        if self.REAL_DEBRID_API_KEY:
            return f"{self.STREMIO_ADDON_URL_BASE}/realdebrid={self.REAL_DEBRID_API_KEY}"
        return self.STREMIO_ADDON_URL_BASE

    SMTP_HOST: str | None = field(default_factory=lambda: os.getenv("SMTP_HOST"))
    SMTP_PORT: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    SMTP_USER: str | None = field(default_factory=lambda: os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER"))
    SMTP_PASSWORD: str | None = field(default_factory=lambda: os.getenv("SMTP_PASSWORD"))
    SMTP_FROM: str | None = field(default_factory=lambda: os.getenv("EMAIL_FROM") or os.getenv("SMTP_FROM"))
    SMTP_TO: str | None = field(default_factory=lambda: os.getenv("EMAIL_TO") or os.getenv("SMTP_TO"))
    SMTP_USE_TLS: bool = field(default_factory=lambda: os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"))

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_USER and self.SMTP_PASSWORD and self.SMTP_TO)

    def __post_init__(self):
        self.SERIES_FOLDER = self.ROOT_FOLDER / "series"
        self.MOVIES_FOLDER = self.ROOT_FOLDER / "movies"

    def reapply_root(self, root: str | os.PathLike) -> None:
        """Re-root the live settings at *root* and re-derive the series/movies paths.

        Used by the ``--root`` CLI flag to override the value loaded
        from ``.env`` at startup without restarting the process.  Also
        updates ``os.environ`` so any later ``os.getenv`` lookups stay
        consistent.
        """
        new_root = Path(root).expanduser()
        self.ROOT_FOLDER = new_root
        self.SERIES_FOLDER = new_root / "series"
        self.MOVIES_FOLDER = new_root / "movies"
        os.environ["ROOT_FOLDER"] = str(new_root)


settings = Settings()