"""Tests for Stremio addon URL ordering."""
from types import SimpleNamespace

import py_stremio.components.addons as addons
from py_stremio.components.stremio_client import search_all_addons_for_streams


class FakeAddon:
    def __init__(self, url: str, calls: list[str], has_streams: bool = True):
        self.url = url
        self.name = url
        self.calls = calls
        self.has_streams = has_streams
        self.api_key = None

    def get_url(self, api_key: str | None = None) -> str:
        return self.url

    def get_streams(self, type_: str, id_: str) -> list[SimpleNamespace]:
        self.calls.append(self.url)
        if not self.has_streams:
            return []
        return [SimpleNamespace(name=f"stream:{self.url}", url=f"download:{self.url}")]


class FakeManager:
    def __init__(self, addons: list[FakeAddon]):
        self.addons = addons

    def search_all_addons_and_collect_working(self, type_: str, id_: str):
        all_streams = []
        working_urls = []
        for addon in self.addons:
            streams = addon.get_streams(type_, id_)
            if streams:
                all_streams.extend(streams)
                working_urls.append(addon.get_url())
        return all_streams, working_urls


def test_search_tries_working_urls_before_remaining_addons(monkeypatch):
    calls = []

    def create_addon_manager_from_urls(urls: list[str]) -> FakeManager:
        return FakeManager([FakeAddon(url, calls) for url in urls])

    def create_addon_manager() -> FakeManager:
        return FakeManager([
            FakeAddon("https://saved-addon", calls),
            FakeAddon("https://new-addon", calls),
        ])

    monkeypatch.setattr(addons, "create_addon_manager_from_urls", create_addon_manager_from_urls)
    monkeypatch.setattr(addons, "create_addon_manager", create_addon_manager)

    streams, working_urls = search_all_addons_for_streams(
        "series",
        "tt123:1:1",
        working_addons=["https://saved-addon/manifest.json"],
    )

    assert calls == ["https://saved-addon", "https://new-addon"]
    assert [stream.name for stream in streams] == [
        "stream:https://saved-addon",
        "stream:https://new-addon",
    ]
    assert working_urls == ["https://saved-addon", "https://new-addon"]


def test_search_continues_to_remaining_addons_when_working_url_has_no_streams(monkeypatch):
    calls = []

    def create_addon_manager_from_urls(urls: list[str]) -> FakeManager:
        return FakeManager([
            FakeAddon(url, calls, has_streams=url != "https://dead-addon")
            for url in urls
        ])

    def create_addon_manager() -> FakeManager:
        return FakeManager([
            FakeAddon("https://dead-addon", calls),
            FakeAddon("https://fallback-addon", calls),
        ])

    monkeypatch.setattr(addons, "create_addon_manager_from_urls", create_addon_manager_from_urls)
    monkeypatch.setattr(addons, "create_addon_manager", create_addon_manager)

    streams, working_urls = search_all_addons_for_streams(
        "movie",
        "tt123",
        working_addons=["https://dead-addon"],
    )

    assert calls == ["https://dead-addon", "https://fallback-addon"]
    assert [stream.name for stream in streams] == ["stream:https://fallback-addon"]
    assert working_urls == ["https://fallback-addon"]
