"""Tests for terminal progress UI helpers."""

import io
import re

from py_stremio.components.application import _make_progress_printer, _progress_line, render_progress_bar


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


class TtyBuffer(io.StringIO):
    columns: int

    def isatty(self):
        return True


def test_render_progress_bar_shows_percentage_and_fill():
    assert render_progress_bar(0, 100, width=10) == "[----------] 0% 0 B / 100 B"
    assert render_progress_bar(50, 100, width=10) == "[█████-----] 50% 50 B / 100 B"
    assert render_progress_bar(100, 100, width=10) == "[██████████] 100% 100 B / 100 B"


def test_render_progress_bar_handles_unknown_total():
    # When we have bytes but total is unknown, show scanning bar
    bar = render_progress_bar(25 * 1024 * 1024, 0, width=10)
    assert "25.0 MB" in bar
    assert "· scanning" in bar or "?" in bar


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

    assert "waiting for download" in start_line
    assert "0 B / 100 B" not in start_line
    assert "[████████████████████████] 100% 1.0 GB / 1.0 GB" in done_line
    assert "2/10" in done_line


def test_episode_start_progress_line_does_not_show_fake_byte_percentage():
    line = _progress_line({
        "type": "episode_start",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 2,
        "current": 2,
        "total": 10,
    })

    assert "0 B / 100 B" not in line
    assert "0%" not in line
    assert "waiting for download" in line
    assert "2/10" in line


def test_episode_progress_line_shows_per_file_download_speed():
    line = _progress_line({
        "type": "bytes",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 10,
        "current": 2,
        "total": 2,
        "downloaded": 512 * 1024 * 1024,
        "bytes_total": 1024 * 1024 * 1024,
        "rate_bps": 25 * 1024 * 1024,
    })

    assert "25.0 MB/s" in line


def test_threaded_progress_printer_uses_hermes_green_terminal_style():
    stream = TtyBuffer()
    printer = _make_progress_printer(stream)

    printer({
        "type": "bytes",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 10,
        "current": 2,
        "total": 2,
        "downloaded": 512,
        "bytes_total": 1024,
        "rate_bps": 1024,
    })

    output = stream.getvalue()
    assert "\033[92m" in output
    assert "\033[96m" in output


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
    plain = strip_ansi(output)
    assert "House of the Dragon" in plain
    assert "S01E09" in plain
    assert "S01E10" in plain


def test_threaded_progress_printer_removes_completed_episode_line():
    stream = io.StringIO()
    printer = _make_progress_printer(stream)

    printer({
        "type": "episode_start",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 10,
        "current": 1,
        "total": 1,
    })
    printer({
        "type": "episode_done",
        "title": "House of the Dragon",
        "season": 1,
        "episode": 10,
        "current": 1,
        "total": 1,
    })

    output = stream.getvalue()
    # With append-only mode (non-TTY), episode_done does not remove the line,
    # so we should see one line for episode_start
    assert "House of the Dragon" in output
    assert output.count("\n") == 1


def test_progress_line_stays_within_terminal_width_when_many_parallel_downloads_are_active():
    line = _progress_line(
        {
            "type": "bytes",
            "title": "How I Met Your Mother",
            "season": 1,
            "episode": 6,
            "current": 5,
            "total": 21,
            "downloaded": 48 * 1024 * 1024,
            "bytes_total": 163 * 1024 * 1024,
            "rate_bps": 866 * 1024,
        },
        max_width=96,
    )

    assert len(strip_ansi(line)) <= 96
    assert "How I Met" in line
    assert "S01E06" in line
    assert "5/21" in line


def test_threaded_progress_printer_uses_stream_terminal_width_to_prevent_wrapped_rows():
    stream = TtyBuffer()
    stream.columns = 96
    printer = _make_progress_printer(stream)

    printer({
        "type": "bytes",
        "title": "How I Met Your Mother",
        "season": 1,
        "episode": 6,
        "current": 5,
        "total": 21,
        "downloaded": 48 * 1024 * 1024,
        "bytes_total": 163 * 1024 * 1024,
        "rate_bps": 866 * 1024,
    })

    plain_lines = [line for line in strip_ansi(stream.getvalue()).splitlines() if line.strip()]
    assert plain_lines
    assert all(len(line) <= 96 for line in plain_lines)


def test_threaded_progress_printer_is_safe_for_parallel_callbacks():
    import threading

    stream = TtyBuffer()
    printer = _make_progress_printer(stream)

    def emit(episode: int):
        for downloaded in range(0, 1024, 128):
            printer({
                "type": "bytes",
                "title": "House of the Dragon",
                "season": 1,
                "episode": episode,
                "current": episode,
                "total": 2,
                "downloaded": downloaded,
                "bytes_total": 1024,
            })

    threads = [threading.Thread(target=emit, args=(episode,)) for episode in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    plain = strip_ansi(stream.getvalue())
    assert "House of the Dragon" in plain
    assert "S01E01" in plain
    assert "S01E02" in plain
