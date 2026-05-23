"""Download orchestration with quality fallback."""
from dataclasses import dataclass
from pathlib import Path

from .config_file import DownloadConfig, QualitySettings
from .provider import BaseProvider, get_provider, DownloadResult
from .state import load_state, save_state
from .settings import settings


@dataclass
class DownloadPlan:
    items: list[tuple[str, list[str]]]


def plan_quality_fallback(config: QualitySettings, target_quality: str) -> list[str]:
    """Generate quality fallback order based on config."""
    qualities = [target_quality]
    if config.allow_higher:
        pass
    if config.fallbacks:
        for q in config.fallbacks:
            if q not in qualities:
                qualities.append(q)
    return qualities


class Downloader:
    def __init__(self, folder_path: Path, config: DownloadConfig):
        self.folder_path = folder_path
        self.config = config
        self.provider = get_provider()

    def download_with_fallback(self, filename: str, qualities: list[str]) -> DownloadResult:
        """Try downloading with quality fallback."""
        for quality in qualities:
            attempts = self._get_attempt_count(filename, quality)
            if attempts >= settings.MAX_DOWNLOAD_ATTEMPTS:
                continue
            result = self._attempt_download(filename, quality, attempts + 1)
            if result.success:
                return result
        return DownloadResult(success=False, error="All quality fallback attempts failed", provider=self.provider.name)

    def _get_attempt_count(self, filename: str, quality: str) -> int:
        state = load_state(self.folder_path)
        return state.was_attempted(f"{filename}:{quality}")

    def _attempt_download(self, filename: str, quality: str, attempt: int) -> DownloadResult:
        print(f"  [{self.provider.name}] Attempting {filename} in {quality} (attempt {attempt}/{settings.MAX_DOWNLOAD_ATTEMPTS})")
        if settings.DRY_RUN:
            result = DownloadResult(success=True, filename=filename, quality=quality, provider=self.provider.name)
        else:
            result = self.provider.download("", filename, str(self.folder_path))
        if not result.success:
            state = load_state(self.folder_path)
            state.mark_failed(f"{filename}:{quality}", result.error or "Unknown error", attempt)
            save_state(self.folder_path, state)
        return result