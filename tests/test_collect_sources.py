"""Tests for addon discovery source generation."""

from types import SimpleNamespace

from py_stremio.components.collect import sources
from py_stremio.components.collect.merger import merge_new_addons


def test_official_collection_keeps_only_http_movie_or_series_stream_addons(monkeypatch):
    payload = [
        {
            "transportUrl": "https://streams.example/manifest.json",
            "manifest": {"resources": ["stream", "catalog"], "types": ["movie", "series"]},
        },
        {
            "transportUrl": "https://catalog.example/manifest.json",
            "manifest": {"resources": ["catalog"], "types": ["movie", "series"]},
        },
        {
            "transportUrl": "https://anime.example/manifest.json",
            "manifest": {"resources": ["stream"], "types": ["anime"]},
        },
        {
            "transportUrl": "https://invalid.example/manifest.json",
            "manifest": "not-a-manifest",
        },
        {
            "transportUrl": "stremio://local-addon",
            "manifest": {"resources": ["stream"], "types": ["series"]},
        },
    ]
    monkeypatch.setattr(
        sources,
        "_fetch",
        lambda *_args, **_kwargs: (200, __import__("json").dumps(payload).encode()),
    )

    assert sources.scrape_stremio_addons_collection() == {"https://streams.example"}


def test_merge_preserves_observed_addons_without_duplicate_sections(tmp_path):
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# Active\n"
        "https://active.example\n\n"
        "# ── OBSERVED ADDONS (was down, may come back) ───────────────────\n"
        "# https://previously-down.example/\n\n"
        "# ── END OF ADDONS LIST ───────────────────────────────────────────────\n"
    )

    merge_new_addons(
        str(addons),
        working_urls=[("https://new.example", "New")],
        dead_urls=["https://newly-down.example"],
        verbose=False,
    )

    content = addons.read_text()
    assert content.count("# ── OBSERVED ADDONS") == 1
    assert content.count("# ── END OF ADDONS LIST") == 1
    assert "https://active.example" in content
    assert "https://new.example  # New" in content
    assert "# https://previously-down.example/" in content
    assert "# https://newly-down.example/" in content


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
