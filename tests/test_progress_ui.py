"""Tests for terminal progress UI helpers."""

import io

from py_stremio.components.application import _make_progress_printer, _progress_line, render_progress_bar


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


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


def test_threaded_progress_printer_renders_each_active_episode_line():
    stream = TtyBuffer()
    printer = _make_progress_printer(stream)

    printer({
        "type": "bytes",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 9,
        "current": 1,
        "total": 2,
        "downloaded": 512,
        "bytes_total": 1024,
    })
    printer({
        "type": "bytes",
        "title": "House of the Dragon",
        "season": 1,
        "total": 2,
        "episode": 10,
        "current": 2,
        "downloaded": 256,
        "bytes_total": 1024,
    })

    output = stream.getvalue()
    assert "House of the Dragon S01E09" in output
    assert "House of the Dragon S01E10" in output
    assert "\033[F" in output
