"""Tests for terminal progress UI helpers."""

from py_stremio.components.application import _progress_line, render_progress_bar


def test_render_progress_bar_shows_percentage_and_fill():
    assert render_progress_bar(0, 100, width=10) == "[----------] 0% 0 B / 100 B"
    assert render_progress_bar(50, 100, width=10) == "[█████-----] 50% 50 B / 100 B"
    assert render_progress_bar(100, 100, width=10) == "[██████████] 100% 100 B / 100 B"


def test_render_progress_bar_handles_unknown_total():
    assert render_progress_bar(25 * 1024 * 1024, 0, width=10) == "[??????????] 25.0 MB"


def test_render_progress_bar_uses_mb_or_gb_size_units():
    assert render_progress_bar(512 * 1024 * 1024, 1024 * 1024 * 1024, width=10) == "[█████-----] 50% 512.0 MB / 1.0 GB"


def test_episode_progress_line_uses_episode_percentage_not_season_percentage():
    start_line = _progress_line({
        "type": "episode_start",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 2,
        "current": 2,
        "total": 10,
    })
    done_line = _progress_line({
        "type": "episode_done",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 2,
        "current": 2,
        "total": 10,
        "downloaded": 1024 * 1024 * 1024,
        "bytes_total": 1024 * 1024 * 1024,
    })

    assert "[------------------------] 0%" in start_line
    assert "[████████████████████████] 100% 1.0 GB / 1.0 GB" in done_line
    assert "episode 2/10" in done_line
