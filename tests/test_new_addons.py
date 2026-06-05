"""Tests for newly-added Stremio addon classes (CometNet, EasyNews+)."""

import pytest

from py_stremio.components.addons.builtin import (
    CometNetAddon,
    EasyNewsPlusAddon,
    KnightCrawlerAddon,
)


class TestCometNetAddon:
    """CometNet — Comet's next-gen, actively maintained."""

    def test_name(self):
        addon = CometNetAddon()
        assert addon.name == "CometNet"

    def test_base_url(self):
        addon = CometNetAddon()
        assert addon.base_url == "https://cometnet.elfhosted.com"

    def test_get_url_without_api_key(self):
        addon = CometNetAddon()
        assert addon.get_url() == "https://cometnet.elfhosted.com"

    def test_get_url_with_api_key(self):
        addon = CometNetAddon()
        addon.api_key = "testkey123"
        assert addon.get_url("testkey123") == "https://cometnet.elfhosted.com"

    def test_query_stream_url(self):
        addon = CometNetAddon()
        url = addon.query_stream_url("movie", "tt1375666")
        assert url == "https://cometnet.elfhosted.com/stream/movie/tt1375666.json"

    def test_query_stream_url_series(self):
        addon = CometNetAddon()
        url = addon.query_stream_url("series", "tt0944947:1:1")
        assert url == "https://cometnet.elfhosted.com/stream/series/tt0944947:1:1.json"


class TestEasyNewsPlusAddon:
    """Easynews+ — usenet binary streams via ElfHosted."""

    def test_name(self):
        addon = EasyNewsPlusAddon()
        assert addon.name == "EasyNews+"

    def test_base_url(self):
        addon = EasyNewsPlusAddon()
        assert addon.base_url == "https://easynewsplus.elfhosted.com"

    def test_get_url_without_api_key(self):
        addon = EasyNewsPlusAddon()
        assert addon.get_url() == "https://easynewsplus.elfhosted.com"

    def test_get_url_with_api_key(self):
        addon = EasyNewsPlusAddon()
        addon.api_key = "testkey456"
        assert addon.get_url("testkey456") == "https://easynewsplus.elfhosted.com"

    def test_query_stream_url(self):
        addon = EasyNewsPlusAddon()
        url = addon.query_stream_url("movie", "tt0111161")
        assert url == "https://easynewsplus.elfhosted.com/stream/movie/tt0111161.json"

    def test_http_addon_subclass(self):
        """Should inherit HttpAddon stream-query behaviour."""
        from py_stremio.components.addons.base import HttpAddon
        assert issubclass(CometNetAddon, HttpAddon)
        assert issubclass(EasyNewsPlusAddon, HttpAddon)


class TestKnightCrawlerDeprecation:
    """KnightCrawler is deprecated — the class should still exist
    for backward compat but the docstring should note deprecation."""

    def test_knightcrawler_still_importable(self):
        addon = KnightCrawlerAddon()
        assert addon.name == "KnightCrawler"
        assert addon.base_url == "https://knightcrawler.elfhosted.com"

    def test_knightcrawler_docstring_notes_deprecation(self):
        doc = KnightCrawlerAddon.__doc__
        assert doc is not None
        assert "DEPRECATED" in doc
        assert "MediaFusion" in doc or "Comet" in doc

    def test_knightcrawler_still_functional(self):
        """Even though deprecated, the class still produces working URLs
        for anyone still using it via addons.txt or config."""
        addon = KnightCrawlerAddon()
        url = addon.query_stream_url("movie", "tt1375666")
        assert url == "https://knightcrawler.elfhosted.com/stream/movie/tt1375666.json"

    def test_factory_includes_knightcrawler_for_backward_compat(self):
        """KnightCrawler is still registered in the factory, not removed."""
        from py_stremio.components.addons.factory import _register_builtin_addons
        from py_stremio.components.addons.manager import AddonManager

        manager = AddonManager()
        _register_builtin_addons(manager)

        names = [a.name for a in manager.addons]
        assert "KnightCrawler" in names
        assert "CometNet" in names
        assert "EasyNews+" in names


class TestFactoryRegistration:
    """New addons should be registered by the factory."""

    def test_cometnet_registered(self):
        from py_stremio.components.addons.factory import _register_builtin_addons
        from py_stremio.components.addons.manager import AddonManager

        manager = AddonManager()
        _register_builtin_addons(manager)

        names = [a.name for a in manager.addons]
        assert "CometNet" in names

    def test_easynews_plus_registered(self):
        from py_stremio.components.addons.factory import _register_builtin_addons
        from py_stremio.components.addons.manager import AddonManager

        manager = AddonManager()
        _register_builtin_addons(manager)

        names = [a.name for a in manager.addons]
        assert "EasyNews+" in names

    def test_total_addon_count_increased(self):
        """We should now have at least 2 more addons than before."""
        from py_stremio.components.addons.factory import _register_builtin_addons
        from py_stremio.components.addons.manager import AddonManager

        manager = AddonManager()
        _register_builtin_addons(manager)

        assert len(manager.addons) >= 35  # was ~33+ before, now 35+
