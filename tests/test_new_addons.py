"""Tests for newly-added Stremio addon classes (CometNet, EasyNews+, Ext)."""

import pytest

from py_stremio.components.addons.types.builtin_addons import (
    CometAddon,
    CometNetAddon,
    EasyNewsPlusAddon,
    ExtAddon,
    HDHubAddon,
    KnightCrawlerAddon,
)


class TestManifestUrlQueryHandling:
    """Configured addon URLs may include /manifest.json, but stream queries must not."""

    def test_comet_manifest_url_is_stripped_for_stream_query(self):
        addon = CometAddon()
        addon.api_key = "testkey"
        url = addon.query_stream_url("series", "tt0944947:1:1")

        assert "/manifest.json/stream/" not in url
        assert url.endswith("/stream/series/tt0944947:1:1.json")

    def test_comet_embeds_realdebrid_config_when_key_present(self):
        addon = CometAddon()

        url = addon.get_url("testkey")

        assert url.startswith("https://comet.feels.legal/")
        assert url.endswith("/manifest.json")
        assert "testkey" not in url

    def test_comet_config_path_is_stripped_for_stream_query(self):
        addon = CometAddon()
        addon.api_key = "testkey"

        url = addon.query_stream_url("series", "tt0944947:1:1")

        assert "/manifest.json/stream/" not in url
        assert url.endswith("/stream/series/tt0944947:1:1.json")

    def test_hdhub_manifest_url_is_stripped_for_stream_query(self):
        addon = HDHubAddon()
        url = addon.query_stream_url("movie", "tt1375666")

        assert "/manifest.json/stream/" not in url
        assert url.endswith("/stream/movie/tt1375666.json")


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
    def test_parse_streams_drops_advisory_error_url(self):
        addon = CometNetAddon()

        streams = addon.parse_streams([
            {
                "name": "[⛔️] CometNet",
                "description": "Non-debrid searches disabled on ElfHosted, use a debrid provider or another instance",
                "url": "https://www.reddit.com/r/StremioAddons/comments/1plsqv7/elfhosted_addons_disabling_nondebrid_modes/",
            },
            {
                "name": "CometNet 1080p",
                "title": "Jury.Duty.Presents.S02E05.1080p.WEB-DL",
                "url": "https://cdn.example.test/video.mkv",
            },
        ])

        assert len(streams) == 1
        assert streams[0].name == "CometNet 1080p"

    def test_parse_streams_drops_browser_only_external_url(self):
        addon = CometNetAddon()

        streams = addon.parse_streams([
            {
                "name": "Watch in browser",
                "externalUrl": "https://example.test/watch/jury-duty",
            }
        ])

        assert streams == []
    def test_parse_streams_drops_configure_addon_advisory_url(self):
        addon = CometNetAddon()

        streams = addon.parse_streams([
            {
                "name": "Jackettio | ElfHosted",
                "title": "ℹ Kindly configure this addon to access streams.",
                "url": "https://jackettio.elfhosted.com/playback/token/token",
            }
        ])

        assert streams == []


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

    def test_factory_excludes_disabled_knightcrawler_but_keeps_class_for_compat(self):
        """KnightCrawler class remains importable but is not registered while disabled."""
        from py_stremio.components.addons.factory import _register_builtin_addons
        from py_stremio.components.addons.manager import AddonManager

        assert KnightCrawlerAddon.enabled is False

        manager = AddonManager()
        _register_builtin_addons(manager)

        names = [a.name for a in manager.addons]
        assert "CometNet" in names
        assert "KnightCrawler" not in names
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

        assert len(manager.addons) >= 36  # was ~33+ before, now 36+


class TestExtAddon:
    """Ext – ext.to stream aggregator (Cloudflare-protected from many networks)."""

    def test_name(self):
        addon = ExtAddon()
        assert addon.name == "Ext"

    def test_base_url(self):
        addon = ExtAddon()
        assert addon.base_url == "https://ext.to"

    def test_get_url_without_api_key(self):
        addon = ExtAddon()
        # The RealDebrid key is not used by ext.to — its base URL is returned
        # unchanged regardless of whether an api_key is provided.
        assert addon.get_url() == "https://ext.to"

    def test_get_url_with_api_key(self):
        addon = ExtAddon()
        addon.api_key = "testkey123"
        assert addon.get_url("testkey123") == "https://ext.to"

    def test_query_stream_url_series(self):
        addon = ExtAddon()
        url = addon.query_stream_url("series", "tt9170070:5:1")
        assert url == "https://ext.to/stream/series/tt9170070:5:1.json"

    def test_query_stream_url_movie(self):
        addon = ExtAddon()
        url = addon.query_stream_url("movie", "tt11378946")
        assert url == "https://ext.to/stream/movie/tt11378946.json"

    def test_http_addon_subclass(self):
        """Ext is a regular Stremio HTTP addon — no RD injection needed."""
        from py_stremio.components.addons.base import HttpAddon
        assert issubclass(ExtAddon, HttpAddon)

    def test_factory_registers_ext(self):
        """Ext must be auto-registered alongside the other built-in addons."""
        from py_stremio.components.addons.factory import _register_builtin_addons
        from py_stremio.components.addons.manager import AddonManager

        manager = AddonManager()
        _register_builtin_addons(manager)

        names = [a.name for a in manager.addons]
        assert "Ext" in names

    def test_ext_in_aggregators_aggregator_folder(self):
        """The class must live in the aggregators category folder."""
        from py_stremio.components.addons.types.aggregators import ExtAddon as ExtFromAgg
        from py_stremio.components.addons.types.builtin_addons import ExtAddon as ExtFromBuiltin
        assert ExtFromAgg is ExtFromBuiltin

    def test_ext_is_in_explicit_names(self):
        """The dynamic factory must NOT clobber the explicit class."""
        from py_stremio.components.addons.types.addon_registry import _EXPLICIT_NAMES
        assert "ExtAddon" in _EXPLICIT_NAMES
