"""Tests for the root addons.stremio manifest list."""

from pathlib import Path

from py_stremio.components.addons.addon import _ADDON_CONFIGURERS


def _active_lines(path: str) -> list[str]:
    return [
        line.strip().split()[0]
        for line in Path(path).read_text().splitlines()
        if line.strip().startswith(("http://", "https://"))
    ]


def test_root_addons_stremio_exists_and_uses_manifest_urls():
    urls = _active_lines("addons.stremio")
    assert urls
    assert all(url.endswith("/manifest.json") for url in urls)


def test_root_addons_stremio_has_unique_manifest_bases():
    urls = _active_lines("addons.stremio")
    bases = [url.rstrip("/").removesuffix("/manifest.json") for url in urls]
    assert len(bases) == len(set(bases))


def test_every_root_stremio_manifest_url_is_covered_by_an_addon_type():
    urls = _active_lines("addons.stremio")
    uncovered = [
        url for url in urls
        if not any(configurer.matches(url) for configurer in _ADDON_CONFIGURERS)
    ]
    assert uncovered == []
