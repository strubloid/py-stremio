"""Tests for addon enabled flags and addon type coverage."""

from py_stremio.components.addons.addon import _ADDON_CONFIGURERS, configure_addon_url
from py_stremio.components.addons.base import BaseAddon, UrlAddon
from py_stremio.components.addons.factory import _register_builtin_addons
from py_stremio.components.addons.manager import AddonManager
from py_stremio.components.addons.types import AddonUrlConfigurer


class DisabledTestAddon(BaseAddon):
    name = "DisabledTest"
    base_url = "https://disabled.example"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url

    def get_streams(self, type_: str, id_: str):
        return []


def test_base_addons_are_enabled_by_default():
    assert BaseAddon.enabled is True
    assert UrlAddon("https://example.test").enabled is True


def test_addon_manager_skips_disabled_addons():
    manager = AddonManager()
    manager.register(DisabledTestAddon())
    assert manager.addons == []


def test_builtin_registration_excludes_disabled_addons():
    manager = AddonManager()
    _register_builtin_addons(manager)
    assert all(addon.enabled for addon in manager.addons)
    assert "KnightCrawler" not in {addon.name for addon in manager.addons}


def test_every_addon_type_configurer_has_enabled_flag():
    assert _ADDON_CONFIGURERS
    assert all(isinstance(configurer, AddonUrlConfigurer) for configurer in _ADDON_CONFIGURERS)
    assert all(isinstance(configurer.enabled, bool) for configurer in _ADDON_CONFIGURERS)


def test_disabled_addon_type_configurers_are_not_applied(monkeypatch):
    class DisabledConfigurer(AddonUrlConfigurer):
        host_match = "disabled-configurer.example"
        enabled = False

        def configure(self, base_url: str, api_key: str) -> str:
            return f"{base_url}/rd={api_key}/"

    monkeypatch.setattr(
        "py_stremio.components.addons.addon._ADDON_CONFIGURERS",
        [DisabledConfigurer()],
    )

    assert configure_addon_url("https://disabled-configurer.example", "KEY") == (
        "https://disabled-configurer.example"
    )
