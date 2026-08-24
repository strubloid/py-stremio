"""Tests for addon discovery source generation."""

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


def test_merge_strips_observed_addons_and_drops_new_dead(tmp_path):
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# Active\n"
        "https://active.example\n\n"
        "# ── OBSERVED ADDONS (was down, may come back) ───────────────────\n"
        "# https://previously-down.example/\n\n"
        "# ── END OF ADDONS LIST ───────────────────────────────────────────────\n"
        "# Total active: 1\n"
        "# Total commented (dead): 1\n"
        "# Grand total lines: 6\n"
    )

    result = merge_new_addons(
        str(addons),
        working_urls=[("https://new.example", "New")],
        dead_urls=["https://newly-down.example"],
        verbose=False,
    )

    content = addons.read_text()
    assert content.count("# ── OBSERVED ADDONS") == 0
    assert content.count("# ── END OF ADDONS LIST") == 0
    assert "# Total commented (dead)" not in content
    assert "# Grand total lines" not in content
    assert "https://active.example" in content
    assert "https://new.example  # New" in content
    assert "https://previously-down.example" not in content
    assert "https://newly-down.example" not in content
    assert result["added"] == 1
    assert result["total_active"] == 2


def test_merge_strips_in_place_commented_dead_urls(tmp_path):
    """Previously commented-out URLs from past Validate-addons runs are also purged."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "https://active.example\n"
        "# https://in-place-commented.example\n"
        "# https://also-commented.example/manifest.json\n"
        "# User-written note, NOT a URL comment\n"
        "https://another-active.example\n"
    )

    merge_new_addons(
        str(addons),
        working_urls=[("https://new.example", None)],
        dead_urls=[],
        verbose=False,
    )

    content = addons.read_text()
    assert "https://active.example" in content
    assert "https://another-active.example" in content
    assert "https://new.example" in content
    assert "in-place-commented.example" not in content
    assert "also-commented.example" not in content
    assert "User-written note, NOT a URL comment" in content


def test_merge_dedup_ignores_commented_dead_urls(tmp_path):
    """Commented-out URLs must not block re-adding the same URL as working."""
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "# https://previously-dead.example\n"
    )

    merge_new_addons(
        str(addons),
        working_urls=[("https://previously-dead.example", "Now")],
        dead_urls=[],
        verbose=False,
    )

    content = addons.read_text()
    assert "https://previously-dead.example  # Now" in content
    assert content.count("previously-dead.example") == 1


def test_merge_no_new_addons_keeps_existing_layout(tmp_path):
    addons = tmp_path / "addons.txt"
    addons.write_text(
        "https://active.example\n"
        "# A user comment\n"
    )

    merge_new_addons(
        str(addons),
        working_urls=[],
        dead_urls=["https://whatever.example"],
        verbose=False,
    )

    content = addons.read_text()
    assert "https://active.example" in content
    assert "# A user comment" in content
    assert "https://whatever.example" not in content


def test_torrentio_variants_do_not_embed_real_debrid_key():
    urls = sources.gen_torrentio_variants()

    assert "https://torrentio.strem.fun/" in urls
    assert "https://torrentio.strem.fun/lite/" in urls
    assert "https://torrentio.strem.fun/sort=seeders/" in urls
    assert not any("realdebrid=" in url for url in urls)


def test_torrentio_variants_never_embed_runtime_real_debrid_key():
    urls = sources.gen_torrentio_variants()

    assert not any("realdebrid=" in url for url in urls)
