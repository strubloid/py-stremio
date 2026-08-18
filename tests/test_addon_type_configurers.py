"""Tests for each host-specific addon configurer file."""

import base64
import json
from urllib.parse import unquote, urlparse

import pytest

from py_stremio.components.addons.addon import configure_addon_url, is_addon_url_enabled
from py_stremio.components.addons.types import (
    AddonUrlConfigurer,
    BrazucaAddonConfigurer,
    CometAddonConfigurer,
    GuindexAddonConfigurer,
    HDHubAddonConfigurer,
    IntellDebridSearchAddonConfigurer,
    NyaaAddonConfigurer,
    StremioAddonConfigurer,
    StremThruAddonConfigurer,
    TorrentioAddonConfigurer,
    YomiAddonConfigurer,
)


def _decode_urlsafe_json(encoded: str) -> dict:
    padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


@pytest.mark.parametrize(
    "configurer",
    [
        BrazucaAddonConfigurer(),
        CometAddonConfigurer(),
        GuindexAddonConfigurer(),
        HDHubAddonConfigurer(),
        IntellDebridSearchAddonConfigurer(),
        NyaaAddonConfigurer(),
        StremioAddonConfigurer(),
        StremThruAddonConfigurer(),
        TorrentioAddonConfigurer(),
        YomiAddonConfigurer(),
    ],
)
def test_every_addon_type_file_exposes_enabled_flag(configurer: AddonUrlConfigurer):
    assert isinstance(configurer.enabled, bool)


def test_torrentio_configurer_injects_realdebrid():
    result = TorrentioAddonConfigurer().configure("https://torrentio.strem.fun/sort=seeders", "KEY")
    assert result == "https://torrentio.strem.fun/sort=seeders|realdebrid=KEY/"


def test_guindex_configurer_injects_realdebrid_path():
    result = GuindexAddonConfigurer().configure("https://guindex-stremio.vercel.app", "KEY")
    assert result == "https://guindex-stremio.vercel.app/realdebrid/KEY/"


def test_comet_configurer_builds_encoded_realdebrid_config():
    result = CometAddonConfigurer().configure("https://comet.feels.legal", "KEY")
    assert result.startswith("https://comet.feels.legal/")
    assert result.endswith("/manifest.json")
    assert "KEY" not in result
    encoded = urlparse(result).path.strip("/").split("/")[0]
    config = _decode_urlsafe_json(encoded)
    assert config["debridServices"] == [{"service": "realdebrid", "apiKey": "KEY"}]
    assert config["enableTorrent"] is False


def test_hdhub_configurer_keeps_torbox_unset_when_no_key():
    result = HDHubAddonConfigurer().configure("https://hdhub.thevolecitor.qzz.io", "")
    encoded = urlparse(result).path.strip("/").split("/")[0]
    config = _decode_urlsafe_json(encoded)
    assert config["torbox"] == "unset"
    assert config["qualities"] == "2160p,1080p,720p"
    assert config["sort"] == "desc"


def test_hdhub_configurer_injects_uuid_torbox_key():
    """A UUID-shaped TorBox key must be embedded as the ``torbox`` field."""
    key = "12345678-1234-1234-1234-123456789abc"
    result = HDHubAddonConfigurer().configure("https://hdhub.thevolecitor.qzz.io", key)
    encoded = urlparse(result).path.strip("/").split("/")[0]
    config = _decode_urlsafe_json(encoded)
    assert config["torbox"] == key


def test_hdhub_configurer_ignores_non_uuid_keys():
    """RealDebrid keys or any non-UUID key must NOT be routed into the
    ``torbox`` field — HDHub does not accept them and would 5xx."""
    rd_key = "REALDEBRIDXXXX12345"
    result = HDHubAddonConfigurer().configure("https://hdhub.thevolecitor.qzz.io", rd_key)
    encoded = urlparse(result).path.strip("/").split("/")[0]
    config = _decode_urlsafe_json(encoded)
    assert config["torbox"] == "unset"


def test_brazuca_configurer_injects_realdebrid():
    result = BrazucaAddonConfigurer().configure(
        "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club", "KEY"
    )
    assert result == (
        "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club/"
        "sort=size|realdebrid=KEY/"
    )


def test_nyaa_configurer_injects_realdebrid():
    result = NyaaAddonConfigurer().configure("https://nyaa-scraper-stremio-addon.nmtl.app", "KEY")
    assert result == "https://nyaa-scraper-stremio-addon.nmtl.app/source=nyaa&rd=KEY&v=1.9.1/"


def test_stremio_configurer_normalizes_manifest_url():
    result = StremioAddonConfigurer().configure("https://example.test/addon/manifest.json", "KEY")
    assert result == "https://example.test/addon"


def test_intell_debrid_search_configurer_injects_realdebrid():
    result = IntellDebridSearchAddonConfigurer().configure("https://intell-debridsearch.nepiraw.com", "KEY")
    assert result == "https://intell-debridsearch.nepiraw.com/realdebrid=KEY/"


def test_yomi_configurer_builds_nested_realdebrid_config():
    result = YomiAddonConfigurer().configure("https://yomi.ruka.pw", "KEY")
    outer = json.loads(unquote(urlparse(result).path.strip("/")))
    config = _decode_urlsafe_json(outer["Yomi"])
    assert config["rdKey"] == "KEY"
    assert config["language"] == ["ENG"]


def test_stremthru_configurer_is_disabled_but_builder_is_tested():
    configurer = StremThruAddonConfigurer()
    assert configurer.enabled is False
    result = configurer.configure("https://stremthru.13377001.xyz/stremio/torz", "KEY")
    encoded = urlparse(result).path.strip("/").split("/")[-1]
    config = _decode_urlsafe_json(encoded)
    assert config == {"indexers": None, "stores": [{"c": "rd", "t": "KEY"}]}


def test_disabled_stremthru_rule_is_not_used_for_runtime_url():
    assert is_addon_url_enabled("https://stremthru.13377001.xyz/stremio/torz") is False
    assert configure_addon_url("https://stremthru.13377001.xyz/stremio/torz", "KEY") == (
        "https://stremthru.13377001.xyz/stremio/torz"
    )
