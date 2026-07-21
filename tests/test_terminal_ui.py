"""Tests for the unified interactive/plain download presentation."""
import io

from rich.console import Console

from py_stremio.services.terminal_ui import PlainDownloadUI, RichDownloadUI, create_download_ui


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
