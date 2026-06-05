"""Tests for persisted Stremio addon URL normalization."""

from py_stremio.components.addons.types import (
    BrazucaAddonConfigurer,
    StremThruAddonConfigurer,
    TorrentioAddonConfigurer,
    YomiAddonConfigurer,
)
from py_stremio.components.stremio.stremio_url import normalize_manifest_url


def test_normalize_yomi_configured_url_to_clean_host():
    configured = (
        "https://yomi.ruka.pw/"
        "%7B%22Yomi%22%3A%22encoded-config-containing-rd-key%22%7D/"
    )
    assert normalize_manifest_url(configured) == "https://yomi.ruka.pw"


def test_normalize_stremthru_configured_url_to_clean_torz_endpoint():
    configured = "https://stremthru.13377001.xyz/stremio/torz/encoded-rd-config/"
    assert normalize_manifest_url(configured) == "https://stremthru.13377001.xyz/stremio/torz"


def test_normalize_brazuca_configured_url_to_clean_host():
    configured = (
        "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club/"
        "sort=size|realdebrid=SECRET/"
    )
    assert normalize_manifest_url(configured) == (
        "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club"
    )


def test_addon_types_own_manifest_url_normalization_rules():
    assert YomiAddonConfigurer().normalize(
        "https://yomi.ruka.pw/%7B%22Yomi%22%3A%22encoded-config-containing-rd-key%22%7D/"
    ) == "https://yomi.ruka.pw"
    assert StremThruAddonConfigurer().normalize(
        "https://stremthru.13377001.xyz/stremio/torz/encoded-rd-config/"
    ) == "https://stremthru.13377001.xyz/stremio/torz"
    assert BrazucaAddonConfigurer().normalize(
        "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club/sort=size|realdebrid=SECRET/"
    ) == "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club"
    assert TorrentioAddonConfigurer().normalize(
        "https://torrentio.strem.fun/sort=seeders|realdebrid=SECRET/manifest.json"
    ) == "https://torrentio.strem.fun/sort=seeders"
