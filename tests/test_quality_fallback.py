"""Tests for quality fallback logic."""
import pytest

from py_stremio.components.config_file import QualitySettings
from py_stremio.components.downloader import plan_quality_fallback


class TestQualityFallback:
    def test_fallback_order_with_preferred(self):
        config = QualitySettings(
            preferred="1080p",
            fallbacks=["720p", "480p"],
        )
        qualities = plan_quality_fallback(config, "1080p")
        assert qualities == ["1080p", "720p", "480p"]

    def test_fallback_respects_config(self):
        config = QualitySettings(
            preferred="720p",
            fallbacks=["1080p", "480p"],
            allow_higher=False,
        )
        qualities = plan_quality_fallback(config, "720p")
        assert qualities[0] == "720p"

    def test_fallback_with_no_fallbacks(self):
        config = QualitySettings(preferred="480p", fallbacks=[])
        qualities = plan_quality_fallback(config, "480p")
        assert qualities == ["480p"]

    def test_allow_higher(self):
        config = QualitySettings(
            preferred="720p",
            fallbacks=["480p"],
            allow_higher=True,
        )
        qualities = plan_quality_fallback(config, "720p")
        assert "720p" in qualities

    def test_allow_lower(self):
        config = QualitySettings(
            preferred="1080p",
            fallbacks=["480p"],
            allow_lower=True,
        )
        qualities = plan_quality_fallback(config, "1080p")
        assert "1080p" in qualities
        assert "480p" in qualities
