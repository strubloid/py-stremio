"""Tests for the unified interactive/plain download presentation."""
import io

from rich.console import Console

from py_stremio.services.terminal_ui import (
    PlainDownloadUI,
    RichDownloadUI,
    _format_eta,
    create_download_ui,
)


class _NoLimiter:
    def get_active_thread_count(self):
        return 0


class _TtyBuffer(io.StringIO):
    def isatty(self):
        return True


def _event(event_type, **values):
    return {
        "type": event_type,
        "title": "Example [red] Show",
        "season": 1,
        "episode": 2,
        "current": 1,
        "total": 1,
        **values,
    }


def test_factory_uses_plain_renderer_when_output_is_not_a_tty():
    ui = create_download_ui(
        io.StringIO(),
        input_stream=_TtyBuffer(),
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=50,
        max_speed_mbps=100,
    )

    assert isinstance(ui, PlainDownloadUI)


def test_plain_renderer_has_no_ansi_and_always_prints_final_outcome():
    output = io.StringIO()
    ui = PlainDownloadUI(
        output,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=50,
        max_speed_mbps=100,
    )

    ui.progress(_event("episode_start"))
    ui.progress(_event("episode_done", success=True, outcome="downloaded", downloaded=1024))

    rendered = output.getvalue()
    assert "\x1b" not in rendered
    assert "[waiting] Example [red] Show S01E02" in rendered
    assert "[downloaded] Example [red] Show S01E02" in rendered


def test_plain_renderer_accepts_legacy_total_size_field():
    output = io.StringIO()
    times = iter([0.0, 2.0, 2.0])
    ui = PlainDownloadUI(
        output,
        limiter=_NoLimiter(),
        max_workers=1,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: next(times),
    )

    ui.progress(_event("bytes", downloaded=50, total_size=100))

    assert "50%" in output.getvalue()


def test_rich_renderer_treats_title_markup_as_literal_and_cleans_up():
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=80, color_system=None)
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
    )

    with ui:
        ui.progress(_event("episode_start"))
        ui.progress(_event("episode_done", success=False, outcome="failed", reason="no stream"))

    rendered = output.getvalue()
    assert "Example [red] Show" in rendered
    assert "[failed]" in rendered
    assert "no stream" in rendered


def test_throughput_uses_shared_byte_deltas_and_expires():
    output = io.StringIO()
    clock = [0.0]
    ui = PlainDownloadUI(
        output,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: clock[0],
    )
    ui.progress(_event("bytes", downloaded=500, bytes_total=1000))
    clock[0] = 1.0
    ui.progress(_event("bytes", downloaded=1500, bytes_total=2000))

    assert ui._throughput() == 1000
    clock[0] = 4.0
    assert ui._throughput() == 0


def test_max_throughput_label_converts_effective_mbps_to_mb_per_second():
    ui = PlainDownloadUI(
        io.StringIO(),
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=80,
        max_speed_mbps=60,
    )

    # 60 Mbps × 80% = 48 Mbps = 6_000_000 B/s → 5.7 MB/s (binary).
    assert ui._max_throughput_label() == "Max 5.7 MB/s"


def test_max_throughput_label_is_omitted_when_unlimited():
    ui = PlainDownloadUI(
        io.StringIO(),
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
    )

    assert ui._max_throughput_label() == ""


def test_max_throughput_label_reflects_speed_percent_change():
    ui = PlainDownloadUI(
        io.StringIO(),
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=50,
        max_speed_mbps=200,
    )

    # 200 Mbps × 50% = 100 Mbps = 12_500_000 B/s → 11.9 MB/s.
    assert ui._max_throughput_label() == "Max 11.9 MB/s"

    ui.speed_ref[0] = 25
    # 200 Mbps × 25% = 50 Mbps = 6_250_000 B/s → 6.0 MB/s.
    assert ui._max_throughput_label() == "Max 6.0 MB/s"


def test_rich_renderer_holds_per_episode_rate_for_display_interval():
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=80, color_system=None)
    clock = [0.0]
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: clock[0],
    )
    key = ("/path", "Example Show", 1, 2)

    # First sample is taken immediately and cached.
    assert ui._stable_rate(key, 5_000_000) == 5_000_000
    # Half a second later the cache is still sticky, even though the
    # instantaneous rate changed dramatically.
    clock[0] = 0.5
    assert ui._stable_rate(key, 9_000_000) == 5_000_000
    # Once the display interval has elapsed the new value takes over.
    clock[0] = 1.6
    assert ui._stable_rate(key, 9_000_000) == 9_000_000


def test_rich_renderer_holds_header_throughput_for_display_interval():
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=80, color_system=None)
    clock = [0.0]
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: clock[0],
    )

    assert ui._stable_throughput(4_000_000) == 4_000_000
    clock[0] = 0.5
    assert ui._stable_throughput(7_500_000) == 4_000_000
    clock[0] = 1.6
    assert ui._stable_throughput(7_500_000) == 7_500_000


def test_rich_renderer_drops_cached_rate_when_episode_finishes():
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=80, color_system=None)
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
    )
    # The progress callback uses _key(event), which includes folder_path and
    # the title/season/episode tuple — match that shape exactly.
    key = (None, "Example [red] Show", 1, 2)
    ui._displayed_rates[key] = 6_000_000
    ui._last_rate_update[key] = 0.0

    ui.progress(_event("episode_done", success=True, outcome="downloaded", downloaded=1024))

    assert key not in ui._displayed_rates
    assert key not in ui._last_rate_update


def test_format_eta_uses_compact_human_readable_units():
    assert _format_eta(0) == "--"
    assert _format_eta(-5) == "--"
    assert _format_eta(45) == "45s"
    assert _format_eta(83) == "1:23"
    assert _format_eta(3_725) == "1:02:05"
    assert _format_eta(86_400 + 7_200) == "1d 2h"


def test_rich_renderer_row_includes_left_column_with_eta():
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=160, color_system=None, record=True)
    clock = [0.0]
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: clock[0],
    )
    # 1 MB downloaded out of 11 MB at 1 MB/s ⇒ 10s remaining.
    ui.progress(_event("bytes", downloaded=1_000_000, bytes_total=11_000_000, rate_bps=1_000_000))
    group = ui._build_renderable()
    console.print(group)
    rendered = console.export_text(styles=False)
    # The ETA column is rendered as a separate table column; assert the
    # formatted value reaches the output.
    assert "10s" in rendered
    # Speed cell carries only the rate; size is its own column.
    assert "976.6 KB/s" in rendered
    assert "·" not in rendered.split("S01E02", 1)[1].split("10s", 1)[0]
    # And the Size column shows the total file size separately.
    assert "10.5 MB" in rendered


def test_rich_renderer_size_column_shows_dash_when_total_unknown():
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=160, color_system=None, record=True)
    clock = [0.0]
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: clock[0],
    )
    # No bytes_total — chunked stream.
    ui.progress(_event("bytes", downloaded=1_000_000, rate_bps=1_000_000))
    clock[0] = 2.0
    ui.progress(_event("bytes", downloaded=2_000_000, rate_bps=1_000_000))
    group = ui._build_renderable()
    console.print(group)
    rendered = console.export_text(styles=False)
    row = next(line for line in rendered.splitlines() if "S01E02" in line)
    # The size column sits between the speed and ETA columns; with no
    # bytes_total it should render as "--" rather than a stale value.
    cells = [c.strip() for c in row.split("  ") if c.strip()]
    assert "--" in cells
    assert "976.6 KB/s" in row


def test_rich_renderer_progress_cell_shows_sizing_when_total_unknown():
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=160, color_system=None, record=True)
    clock = [0.0]
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=_NoLimiter(),
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: clock[0],
    )
    # Chunked stream: bytes are flowing, no Content-Length was reported.
    ui.progress(_event("bytes", downloaded=12_582_912, rate_bps=2_000_000))
    group = ui._build_renderable()
    console.print(group)
    rendered = console.export_text(styles=False)

    # Don't show a 0% bar that looks frozen — show the received bytes with
    # a sizing label so the user can see data is actually moving.
    assert "12.0 MB · sizing" in rendered


def test_rich_renderer_header_annotates_downloading_count_when_searching():
    from py_stremio.components.download.bandwidth_service import FairBandwidthLimiter
    output = _TtyBuffer()
    console = Console(file=output, force_terminal=True, width=160, color_system=None, record=True)
    clock = [0.0]
    limiter = FairBandwidthLimiter(total_bytes_per_second=0)
    ui = RichDownloadUI(
        output,
        console=console,
        limiter=limiter,
        max_workers=2,
        speed_percent=100,
        max_speed_mbps=100,
        now=lambda: clock[0],
    )
    # Two items active: one downloading bytes (registered with the
    # bandwidth limiter), one still in episode_start (no bytes yet →
    # not registered).
    limiter.register_thread(4242)
    ui.progress(_event("bytes", downloaded=1_000_000, bytes_total=11_000_000, rate_bps=1_000_000))
    ui.progress({"type": "episode_start", "title": "Example [red] Show", "season": 1, "episode": 3, "current": 2, "total": 6, "folder_path": "/p2"})
    group = ui._build_renderable()
    console.print(group)
    rendered = console.export_text(styles=False)

    # 2 active, but only 1 actually consuming bandwidth — the annotation
    # must make that visible so users don't think the searcher is stealing
    # bandwidth from the real download.
    assert "2 active (1 downloading)" in rendered
    # Footer label was also renamed for clarity.
    assert "Downloading 1" in rendered
