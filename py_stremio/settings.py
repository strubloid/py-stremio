"""Application settings loaded from environment variables."""
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import os


@dataclass
class Settings:
    ROOT_FOLDER: Path = field(default_factory=lambda: Path(os.getenv("ROOT_FOLDER") or os.getenv("ROOT_DOWNLOAD_FOLDER", "/home/strubloid/stremio-downloads")))
    SERIES_FOLDER: Path = field(init=False)
    MOVIES_FOLDER: Path = field(init=False)

    REAL_DEBRID_API_KEY: str | None = field(default_factory=lambda: os.getenv("REAL_DEBRID_API_KEY"))
    MAX_DOWNLOAD_ATTEMPTS: int = field(default_factory=lambda: int(os.getenv("MAX_DOWNLOAD_ATTEMPTS", "5")))
    DRY_RUN: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes"))

    STREMIO_ADDON_URL: str | None = field(default_factory=lambda: os.getenv("STREMIO_ADDON_URL"))
    STREMIO_ADDON_URL_BASE: str = field(default_factory=lambda: os.getenv("STREMIO_ADDON_URL_BASE") or "https://torrentio.strem.fun")

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


settings = Settings()