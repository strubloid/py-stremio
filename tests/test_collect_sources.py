"""Tests for addon discovery source generation."""

from types import SimpleNamespace

from py_stremio.components.collect import sources


def test_torrentio_variants_do_not_embed_static_real_debrid_key(monkeypatch):
    monkeypatch.setattr(
        sources,
        "settings",
        SimpleNamespace(REAL_DEBRID_API_KEY=""),
    )

    urls = sources.gen_torrentio_variants()

    assert "https://torrentio.strem.fun/" in urls
    assert "https://torrentio.strem.fun/lite/" in urls
    assert "https://torrentio.strem.fun/sort=seeders/" in urls
    assert not any("realdebrid=" in url for url in urls)


def test_torrentio_variants_use_runtime_real_debrid_key(monkeypatch):
    monkeypatch.setattr(
        sources,
        "settings",
        SimpleNamespace(REAL_DEBRID_API_KEY="runtime-key"),
    )

    urls = sources.gen_torrentio_variants()

    assert "https://torrentio.strem.fun/realdebrid=runtime-key/" in urls
