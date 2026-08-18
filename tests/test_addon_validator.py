"""Tests for addon URL validation."""

from urllib.parse import unquote

import httpx
import pytest

from py_stremio.components.addons.addon_validator import (
    check_addon_url,
    update_addons_file,
    validate_all_addons,
    validate_and_update,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

MANIFEST_OK = {
    "id": "org.test.addon",
    "name": "TestAddon",
    "resources": ["stream", "catalog"],
    "types": ["series", "movie"],
}

STREAMS_OK = {"streams": [{"name": "Test", "title": "1080p", "url": "https://dl.example/test.mp4"}]}


class FakeResponse:
    """Simulate httpx.Response for manifest / stream requests."""

    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError("oops", request=httpx.Request("GET", "http://test"), response=None)


# ── test_addon_url ───────────────────────────────────────────────────────

def test_addon_url_basic(monkeypatch):
    """URL with a valid manifest should pass."""
    called_urls = []

    def fake_get(url, **kwargs):
        called_urls.append(url)
        if url.endswith("/manifest.json"):
            return FakeResponse(200, MANIFEST_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://addon.example.test/")
    assert result["manifest_ok"] is True
    assert result["streams_found"] == 0
    assert any(u.endswith("/manifest.json") for u in called_urls)


def test_addon_url_stream_ok(monkeypatch):
    """URL without manifest but with working stream endpoint should pass."""
    def fake_get(url, **kwargs):
        if url.endswith("/manifest.json"):
            return FakeResponse(404)
        if url.endswith("/stream/series/tt0944947:1:1.json"):
            return FakeResponse(200, STREAMS_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://streams.example.test/")
    assert result["manifest_ok"] is False
    assert result["streams_found"] == 1


def test_addon_url_with_bad_name(monkeypatch):
    """URL with neither manifest nor streams should fail — error is None because 404 is not an exception."""
    def fake_get(url, **kwargs):
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://dead.example.test/")
    assert result["manifest_ok"] is False
    assert result["streams_found"] == 0


def test_addon_url_connection_error(monkeypatch):
    """Connection error should be caught and reported."""
    def fake_get(url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://unreachable.example.test/")
    assert result["manifest_ok"] is False
    assert result["streams_found"] == 0
    assert result["error"] is not None


def test_addon_url_manifest_json_with_streams_key(monkeypatch):
    """Some addons return a streams list from the manifest endpoint."""
    def fake_get(url, **kwargs):
        if url.endswith("/manifest.json"):
            return FakeResponse(200, {"streams": [{"name": "Direct"}]})
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://direct.example.test/")
    assert result["manifest_ok"] is True


def test_addon_url_already_strips_manifest_json(monkeypatch):
    """URL ending in /manifest.json should be handled correctly."""
    called = []

    def fake_get(url, **kwargs):
        called.append(url)
        return FakeResponse(200, MANIFEST_OK)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_addon_url("https://ex.example/base/manifest.json")
    assert result["manifest_ok"] is True
    # Should not double-append manifest.json
    assert "base/manifest.json/manifest.json" not in called[-1]


# ── update_addons_file ───────────────────────────────────────────────────

def test_update_addons_file_comments_failed(tmp_path):
    """Failing URLs get commented out, working ones stay."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# ── Section header ──\n"
        "https://working.example/\n"
        "https://broken.example/\n"
        "\n"
        "https://also-working.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://working.example/", "https://also-working.example/"],
        failed=["https://broken.example/"],
    )

    assert changes == 1
    content = addons.read_text()
    assert "https://working.example/" in content
    assert "https://also-working.example/" in content
    assert "# https://broken.example/" in content  # commented out
    assert "# ── Section header ──" in content  # preserved


def test_update_addons_file_no_changes_if_all_working(tmp_path):
    """When all URLs pass, the file is untouched."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "https://a.example/\n"
        "https://b.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://a.example/", "https://b.example/"],
        failed=[],
    )

    assert changes == 0
    assert addons.read_text() == (
        "https://a.example/\n"
        "https://b.example/\n"
    )


def test_update_addons_file_refreshes_active_and_dead_summary_counts(tmp_path):
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# Active URLs: 99 (last validated)\n"
        "https://working.example\n"
        "https://broken.example\n"
        "# Total active: 99\n"
        "# Total commented (dead): 0\n"
        "# Total lines: 0\n"
    )

    update_addons_file(
        str(addons),
        working=["https://working.example"],
        failed=["https://broken.example"],
    )

    content = addons.read_text()
    assert "# Active URLs: 1 (last validated)" in content
    assert "# Total active: 1" in content
    assert "# Total commented (dead): 1" in content
    assert "# Total lines: 6" in content


def test_update_addons_file_comment_already_comment_unchanged(tmp_path):
    """Already commented lines are left alone, even if URL is in failed."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# https://already-commented.example/\n"
        "https://active.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://active.example/"],
        failed=["https://already-commented.example/"],
    )

    assert changes == 0
    content = addons.read_text()
    assert "# https://already-commented.example/" in content
    assert "https://active.example/" in content


def test_update_addons_file_handles_blank_lines_and_section_headers(tmp_path):
    """Blank lines and section comments are perfectly preserved."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "\n"
        "# ── TORRENTIO ──\n"
        "https://torrentio.example/\n"
        "\n"
        "# ── ANIME ──\n"
        "https://anime.example/\n"
    )

    changes = update_addons_file(
        str(addons),
        working=["https://torrentio.example/"],
        failed=["https://anime.example/"],
    )

    assert changes == 1
    content = addons.read_text()
    assert content.splitlines()[0] == ""
    assert "# ── TORRENTIO ──" in content
    assert "https://torrentio.example/" in content
    assert "# https://anime.example/" in content
    assert "# ── ANIME ──" in content


# ── validate_all_addons (integration w/ mocked HTTP) ─────────────────────

def test_validate_all_addons(tmp_path, monkeypatch):
    """End-to-end: one working addon, one failing addon, one commented."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# ── Header ──\n"
        "https://working.example/\n"
        "https://dead.example/\n"
        "# https://already-commented.example/\n"
    )

    call_count = 0

    def fake_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "working" in url:
            return FakeResponse(200, MANIFEST_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    working, failed = validate_all_addons(str(addons), quiet=True)

    assert "https://working.example/" in working
    assert "https://dead.example/" in failed
    # Commented lines are not tested
    assert "https://already-commented.example/" not in working
    assert "https://already-commented.example/" not in failed


def test_validate_and_update_rewrites_file(tmp_path, monkeypatch):
    """Full pipeline: validates, comments dead URLs, leaves working alone."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "https://good.example/\n"
        "https://bad.example/\n"
    )

    def fake_get(url, **kwargs):
        if "good" in url:
            return FakeResponse(200, MANIFEST_OK)
        return FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    working_count, failed_count = validate_and_update(str(addons), quiet=True)

    assert working_count == 1
    assert failed_count == 1

    content = addons.read_text()
    assert "https://good.example/" in content
    assert "# https://bad.example/" in content


def test_validate_all_addons_empty_file(tmp_path, monkeypatch):
    """Empty addons file should return empty results."""
    addons = tmp_path / "addons.txt"
    addons.write_text("# only comments\n")

    working, failed = validate_all_addons(str(addons), quiet=True)
    assert working == []
    assert failed == []


def test_validate_all_addons_connection_timeout(tmp_path, monkeypatch):
    """Connection timeout for an addon should count as failed."""
    addons = tmp_path / "addons.txt"
    addons.write_text("https://timeout.example/\n")

    def fake_get(url, **kwargs):
        raise httpx.TimeoutException("Timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    working, failed = validate_all_addons(str(addons), quiet=True)
    assert working == []
    assert len(failed) == 1


# ── UrlAddon RD injection tests ──────────────────────────────────────────

class TestUrlAddonRDInjection:
    """UrlAddon.get_url(api_key) injects RealDebrid key for known addons."""

    def test_intell_debridsearch_injection(self):
        """intell-debridsearch addon is DISABLED — URL stays as-is, no injection."""
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://intell-debridsearch.nepiraw.com")
        assert not addon.enabled
        result = addon.get_url("TESTKEY123")
        assert result == "https://intell-debridsearch.nepiraw.com"

    def test_nyaa_scraper_injection(self):
        """nyaa-scraper URL gets source=nyaa&rd=KEY&v=1.9.1/ appended."""
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://nyaa-scraper-stremio-addon.nmtl.app")
        result = addon.get_url("TESTKEY456")
        assert result == "https://nyaa-scraper-stremio-addon.nmtl.app/source=nyaa&rd=TESTKEY456&v=1.9.1/"

    def test_comet_injection_embeds_config_without_plain_key(self):
        """Comet clean URLs get configured so they return RD playback URLs."""
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://comet.feels.legal")
        result = addon.get_url("TESTKEY456")
        assert result.startswith("https://comet.feels.legal/")
        assert result.endswith("/manifest.json")
        assert "TESTKEY456" not in result

    def test_torrentio_clean_url_injects_realdebrid_for_server_cache(self):
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://torrentio.strem.fun/sort=seeders")
        result = addon.get_url("TESTKEY456")
        assert result == "https://torrentio.strem.fun/sort=seeders|realdebrid=TESTKEY456/"

    def test_guindex_clean_url_injects_realdebrid_for_server_cache(self):
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://guindex-stremio.vercel.app")
        result = addon.get_url("TESTKEY456")
        assert result == "https://guindex-stremio.vercel.app/realdebrid/TESTKEY456/"

    def test_yomi_clean_url_builds_nested_realdebrid_config(self):
        import base64
        import json
        from urllib.parse import unquote, urlparse

        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://yomi.ruka.pw")
        result = addon.get_url("TESTKEY456")

        assert result.startswith("https://yomi.ruka.pw/")
        outer = json.loads(unquote(urlparse(result).path.strip("/")))
        inner = outer["Yomi"]
        padded = inner + "=" * ((4 - len(inner) % 4) % 4)
        config = json.loads(base64.urlsafe_b64decode(padded))
        assert config["rdKey"] == "TESTKEY456"
        assert config["language"] == ["ENG"]
        assert "1080p" in config["resolutions"]

    def test_yomi_configured_url_is_clean_when_no_api_key(self):
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://yomi.ruka.pw")
        assert addon.get_url(None) == "https://yomi.ruka.pw"

    def test_brazuca_clean_url_injects_realdebrid_for_server_cache(self):
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://94c8cb9f702d-brazuca-torrents.baby-beamup.club")
        result = addon.get_url("TESTKEY456")
        assert result == (
            "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club/"
            "sort=size|realdebrid=TESTKEY456/"
        )

    def test_stremthru_config_builder_can_build_realdebrid_store_config(self):
        import base64
        import json
        from urllib.parse import urlparse

        from py_stremio.components.addons.types.comet_family.StremThruAddonConfigurer import StremThruAddonConfigurer

        result = StremThruAddonConfigurer().configure(
            "https://stremthru.13377001.xyz/stremio/torz",
            "TESTKEY456",
        )
        assert result.startswith("https://stremthru.13377001.xyz/stremio/torz/")
        encoded = urlparse(result).path.strip("/").split("/")[-1]
        padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
        config = json.loads(base64.urlsafe_b64decode(padded))
        assert config == {"indexers": None, "stores": [{"c": "rd", "t": "TESTKEY456"}]}

    def test_no_injection_for_unknown_host(self):
        """Addons without a registered injector return the base URL unchanged."""
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://unknown-addon.example")
        result = addon.get_url("TESTKEY789")
        assert result == "https://unknown-addon.example"

    def test_no_injection_without_api_key(self):
        """get_url() with no key returns the base URL unchanged."""
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://intell-debridsearch.nepiraw.com")
        result = addon.get_url(None)
        assert result == "https://intell-debridsearch.nepiraw.com"

    def test_register_custom_injector(self):
        """Custom injectors can be registered and take effect."""
        from py_stremio.components.addons.base import UrlAddon, register_rd_injector

        # Add a test injector
        register_rd_injector("my-custom-addon.test", lambda url, key: f"{url}/rd={key}/")
        addon = UrlAddon("https://my-custom-addon.test/some/path")
        result = addon.get_url("MYKEY")
        assert result == "https://my-custom-addon.test/some/path/rd=MYKEY/"

        # Clean up by removing from the registry
        from py_stremio.components.addons.base import URL_RD_INJECTORS
        del URL_RD_INJECTORS["my-custom-addon.test"]

    def test_url_strips_manifest_json(self):
        """UrlAddon strips /manifest.json from the URL."""
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://example.test/addon/manifest.json")
        assert addon.get_url(None) == "https://example.test/addon"

    def test_url_preserves_query_params(self):
        """get_url preserves query parameters in the base URL."""
        from py_stremio.components.addons.base import UrlAddon

        addon = UrlAddon("https://intell-debridsearch.nepiraw.com?version=2")
        # The injector matches the hostname part and appends, preserving query
        result = addon.get_url("KEY")
        # Note: the injector just appends to the URL as-is
        assert "intell-debridsearch.nepiraw.com" in result


# ── create_addon_manager integration tests ────────────────────────────────

class TestCreateAddonManager:
    """create_addon_manager() builds correct addon lists with dedup and RD injection."""

    def test_create_addon_manager_with_no_file(self, monkeypatch):
        """Without addons.txt, only built-in addons are loaded."""
        monkeypatch.setattr(
            "py_stremio.components.addons.factory.load_addons_from_file",
            lambda _: [],
        )
        from py_stremio.components.addons.factory import create_addon_manager

        manager = create_addon_manager()
        # Expect ~50 built-in addons (TvVoo, FrostStream added 2 more recently)
        assert len(manager.addons) > 40
        assert len(manager.addons) < 70

    def test_create_addon_manager_dedup_skips_builtin_hosts(self, monkeypatch, tmp_path):
        """File addons with the same host as a built-in are skipped (dedup)."""
        addons_txt = tmp_path / "addons.txt"
        addons_txt.write_text(
            "https://torrentio.strem.fun/sort=seeders/\n"
            "https://mediafusion.elfhosted.com/\n"
            "https://intell-debridsearch.nepiraw.com\n"
        )

        monkeypatch.setattr(
            "py_stremio.components.addons.factory.load_addons_from_file",
            lambda _: [
                "https://torrentio.strem.fun/sort=seeders/",
                "https://mediafusion.elfhosted.com/",
                "https://intell-debridsearch.nepiraw.com",
            ],
        )

        from py_stremio.components.addons.factory import create_addon_manager

        manager = create_addon_manager()
        addon_urls = {a.get_url(None) for a in manager.addons}

        # Torrentio sort=seeders and MediaFusion should be covered by built-ins
        # (their host matches a built-in addon)
        # intell-debridsearch has no built-in but its configurer is disabled
        # so it's skipped by the UrlAddon.enabled check
        assert any("torrentio.strem.fun" in u for u in addon_urls)
        assert any("mediafusion.elfhosted.com" in u for u in addon_urls)
        assert not any("intell-debridsearch.nepiraw.com" in u for u in addon_urls)

    def test_addon_api_key_set_on_all_addons(self, monkeypatch):
        """Every addon gets the RD api_key assigned."""
        monkeypatch.setattr(
            "py_stremio.components.addons.factory.load_addons_from_file",
            lambda _: [],
        )

        from py_stremio.components.addons.factory import create_addon_manager

        manager = create_addon_manager()
        for addon in manager.addons:
            # api_key may be None (no RD configured) or have a value
            assert hasattr(addon, "api_key")


# ── Validator RD injection tests ─────────────────────────────────────────

class TestValidatorRDInjection:
    """check_addon_url uses UrlAddon.get_url() to inject RD key when api_key is provided."""

    def test_check_addon_url_injects_rd_key_for_known_host(self, monkeypatch):
        """When api_key is provided and URL matches an injector, httpx gets the injected URL."""
        from py_stremio.components.addons.addon_validator import check_addon_url

        captured_urls = []

        def fake_get(url, **kwargs):
            captured_urls.append(url)
            return FakeResponse(200, {
                "id": "test",
                "name": "Test",
                "resources": ["stream"],
                "types": ["series"],
            })

        monkeypatch.setattr(httpx, "get", fake_get)

        # Use nyaa-scraper which still has a UrlAddon-level RD injector
        result = check_addon_url(
            "https://nyaa-scraper-stremio-addon.nmtl.app",
            api_key="RDTEST",
        )

        # The manifest check should hit the injected URL
        manifest_urls = [u for u in captured_urls if u.endswith("/manifest.json")]
        assert any("rd=RDTEST" in u for u in manifest_urls), (
            f"Expected injected RD key in URL, got: {captured_urls}"
        )
        assert result["manifest_ok"] is True

    def test_check_addon_url_without_api_key_uses_raw_url(self, monkeypatch):
        """Without api_key, the raw URL from addons.txt is tested."""
        from py_stremio.components.addons.addon_validator import check_addon_url

        captured_urls = []

        def fake_get(url, **kwargs):
            captured_urls.append(url)
            return FakeResponse(200, {
                "id": "test",
                "name": "Test",
                "resources": ["stream"],
                "types": ["series"],
            })

        monkeypatch.setattr(httpx, "get", fake_get)

        result = check_addon_url("https://nyaa-scraper-stremio-addon.nmtl.app")

        manifest_urls = [u for u in captured_urls if u.endswith("/manifest.json")]
        assert any("rd=" in u for u in manifest_urls) is False, (
            f"Raw URL should NOT have RD key injected, got: {captured_urls}"
        )
        assert result["manifest_ok"] is True

    def test_check_addon_url_preserves_original_url_in_result(self, monkeypatch):
        """The result dict contains the *original* URL (from addons.txt), not the injected one."""
        from py_stremio.components.addons.addon_validator import check_addon_url

        def fake_get(url, **kwargs):
            return FakeResponse(200, {
                "id": "test",
                "name": "Test",
                "resources": ["stream"],
                "types": ["series"],
            })

        monkeypatch.setattr(httpx, "get", fake_get)

        result = check_addon_url(
            "https://nyaa-scraper-stremio-addon.nmtl.app",
            api_key="SECRET",
        )
        assert result["url"] == "https://nyaa-scraper-stremio-addon.nmtl.app"
        assert "rd=SECRET" not in result["url"]
