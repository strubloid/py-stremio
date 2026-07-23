"""Tests for addon inventory loading."""

from pathlib import Path

from py_stremio.components.addons.base import UrlAddon
from py_stremio.components.addons.factory import load_addons_from_file, load_addon_urls
from py_stremio.components.addons.types import StremioAddonConfigurer


def test_stremio_type_converts_manifest_url_to_stream_base():
    configurer = StremioAddonConfigurer()
    assert configurer.enabled is True
    assert configurer.matches("https://example.test/addon/manifest.json")
    assert configurer.configure("https://example.test/addon/manifest.json", "KEY") == (
        "https://example.test/addon"
    )


def test_url_addon_loaded_from_manifest_url_queries_stream_endpoint():
    addon = UrlAddon("https://example.test/addon/manifest.json")
    assert addon.get_url(None) == "https://example.test/addon"
    assert addon.query_stream_url("series", "tt123:1:2") == (
        "https://example.test/addon/stream/series/tt123:1:2.json"
    )


def test_load_addon_urls_reads_addons_txt_and_addons_stremio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("addons").mkdir()
    Path("addons/addons.txt").write_text(
        "# clean base URLs\nhttps://base.example/addon\nhttps://duplicate.example/addon\n",
    )
    Path("addons/stremio.txt").write_text(
        "# final manifest URLs\n"
        "https://manifest.example/addon/manifest.json\n"
        "https://duplicate.example/addon/manifest.json\n",
    )

    assert load_addons_from_file("addons/stremio.txt") == [
        "https://manifest.example/addon/manifest.json",
        "https://duplicate.example/addon/manifest.json",
    ]
    assert load_addon_urls() == [
        "https://manifest.example/addon/manifest.json",
        "https://duplicate.example/addon/manifest.json",
        "https://base.example/addon",
    ]
