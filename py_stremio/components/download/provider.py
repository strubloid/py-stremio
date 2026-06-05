"""Content providers for downloading videos."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import httpx
import re

from py_stremio.components.configs.app_settings import settings


@dataclass
class DownloadResult:
    success: bool
    filename: str | None = None
    quality: str | None = None
    provider: str = "unknown"
    error: str | None = None


class BaseProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def search(self, query: str, quality: str, language: str = "any") -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def download(self, torrent_url: str, filename: str, folder: str) -> DownloadResult:
        pass

    def is_available(self) -> bool:
        return True


class RealDebridProvider(BaseProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.REAL_DEBRID_API_KEY
        self.base_url = "https://api.real-debrid.com/api/1.0"

    @property
    def name(self) -> str:
        return "realdebrid"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            response = httpx.get(f"{self.base_url}/user", headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def search(self, query: str, quality: str, language: str = "any") -> list[dict[str, Any]]:
        return [{"type": "placeholder", "title": query, "quality": quality}]

    def download(self, torrent_url: str, filename: str, folder: str) -> DownloadResult:
        quality = quality_from_filename(filename)
        if settings.DRY_RUN:
            return DownloadResult(success=True, filename=filename, quality=quality, provider=self.name)
        return DownloadResult(success=False, error="RealDebrid download not implemented in MVP", provider=self.name)


class MockProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "mock"

    def is_available(self) -> bool:
        return True

    def search(self, query: str, quality: str, language: str = "any") -> list[dict[str, Any]]:
        return [{"type": "mock", "title": query, "quality": quality, "mock": True}]

    def download(self, torrent_url: str, filename: str, folder: str) -> DownloadResult:
        quality = quality_from_filename(filename)
        if settings.DRY_RUN:
            return DownloadResult(success=True, filename=filename, quality=quality, provider=self.name)
        fake_path = f"{folder}/{filename}"
        return DownloadResult(success=True, filename=fake_path, quality=quality, provider=self.name)


class FallbackProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "fallback"

    def is_available(self) -> bool:
        return True

    def search(self, query: str, quality: str, language: str = "any") -> list[dict[str, Any]]:
        return []

    def download(self, torrent_url: str, filename: str, folder: str) -> DownloadResult:
        return DownloadResult(success=False, error="No provider available", provider=self.name)


def quality_from_filename(filename: str) -> str:
    """Extract quality from filename."""
    match = re.search(r"(2160p|1080p|720p|480p|360p|240p)", filename, re.IGNORECASE)
    return match.group(1) if match else "unknown"


def get_provider() -> BaseProvider:
    """Get appropriate provider based on configuration."""
    if settings.REAL_DEBRID_API_KEY:
        provider = RealDebridProvider()
        if provider.is_available():
            return provider
    if settings.DRY_RUN:
        return MockProvider()
    return FallbackProvider()