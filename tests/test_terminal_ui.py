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


# ── Bottom controls bar ───────────────────────────────────────────────────


class TestControlsBar:
    """The bottom controls bar shows the current state of every interactive
    control (4K filter, worker count, speed limit) plus the keymap.  Pressing
    the documented keys must update both the displayed value and the
    corresponding mutable reference consumed by the download pipeline.
    """

    def _make_ui(self, **overrides):
        output = _TtyBuffer()
        console = Console(
            file=output,
            force_terminal=True,
            width=160,
            color_system=None,
            record=True,
        )
        defaults = dict(
            limiter=_NoLimiter(),
            max_workers=2,
            speed_percent=50,
            max_speed_mbps=100,
        )
        defaults.update(overrides)
        return RichDownloadUI(output, console=console, **defaults), console

    def test_initial_4k_state_is_off(self):
        ui, _ = self._make_ui()
        assert ui.allow_4k_ref[0] is False

    def test_controls_bar_shows_off_state(self):
        ui, console = self._make_ui()
        console.print(ui._build_controls_line())
        rendered = console.export_text(styles=False)
        assert "[B] 4K: OFF" in rendered
        assert "[+/-] Workers: 2" in rendered
        assert "[[/]] Speed: 50%" in rendered
        assert "[Q] Quit" in rendered

    def test_controls_bar_shows_on_state_after_toggle(self):
        ui, console = self._make_ui()
        ui.trigger_4k_toggle()
        console.print(ui._build_controls_line())
        rendered = console.export_text(styles=False)
        assert "[B] 4K: ON" in rendered

    def test_4k_toggle_fires_registered_handlers(self):
        ui, _ = self._make_ui()
        received: list[bool] = []
        ui.on_4k_toggle(received.append)
        ui.trigger_4k_toggle()
        ui.trigger_4k_toggle()
        assert received == [True, False]

    def test_b_key_toggles_4k_via_keyboard(self):
        ui, _ = self._make_ui()
        ui.controls.dispatch("b")
        assert ui.allow_4k_ref[0] is True
        ui.controls.dispatch("B")  # case-insensitive
        assert ui.allow_4k_ref[0] is False

    def test_plus_bumps_workers(self):
        ui, _ = self._make_ui(max_workers=3)
        ui.controls.dispatch("+")
        assert ui.workers_ref[0] == 4
        # Unshifted '+' is '=' on US keyboards — both must work.
        ui.controls.dispatch("=")
        assert ui.workers_ref[0] == 5

    def test_minus_drops_workers(self):
        ui, _ = self._make_ui(max_workers=3)
        ui.controls.dispatch("-")
        assert ui.workers_ref[0] == 2

    def test_workers_clamps_to_bounds(self):
        ui, _ = self._make_ui(max_workers=1)
        ui.controls.dispatch("-")
        assert ui.workers_ref[0] == 1  # min
        for _ in range(20):
            ui.controls.dispatch("+")
        assert ui.workers_ref[0] == RichDownloadUI.MAX_WORKERS  # 16

    def test_brackets_bump_speed_in_steps(self):
        ui, _ = self._make_ui(speed_percent=50)
        ui.controls.dispatch("]")
        assert ui.speed_ref[0] == 55
        ui.controls.dispatch("[")
        ui.controls.dispatch("[")
        assert ui.speed_ref[0] == 45

    def test_speed_clamps_to_bounds(self):
        ui, _ = self._make_ui(speed_percent=1)
        ui.controls.dispatch("[")
        assert ui.speed_ref[0] == 1  # min
        for _ in range(50):
            ui.controls.dispatch("]")
        assert ui.speed_ref[0] == RichDownloadUI.MAX_SPEED  # 100

    def test_q_key_requests_shutdown(self):
        from py_stremio.utils.cancellation import (
            clear_shutdown,
            shutdown_requested,
        )
        clear_shutdown()
        ui, _ = self._make_ui()
        ui.controls.dispatch("q")
        assert shutdown_requested() is True
        clear_shutdown()  # cleanup for subsequent tests

    def test_full_renderable_includes_controls_line(self):
        ui, console = self._make_ui()
        console.print(ui._build_renderable())
        rendered = console.export_text(styles=False)
        # The controls line lives below the existing footer
        assert "[B] 4K: OFF" in rendered
        # and the existing footer is still there
        assert "Worker limit 2" in rendered

    def test_no_op_when_key_not_registered(self):
        ui, _ = self._make_ui()
        # Should not raise even though no handler is registered.
        ui.controls.dispatch("z")
        assert ui.allow_4k_ref[0] is False
        assert ui.workers_ref[0] == 2
        assert ui.speed_ref[0] == 50

    def test_4k_toggle_propagates_to_live_configs(self):
        """The 4K toggle mutates in-memory DownloadConfig objects so the
        next ``select_quality_streams`` call honours the choice.  This is
        exactly the wiring that ``services/download.py`` uses to keep the
        next episode's quality filter in sync with the bottom bar."""
        from py_stremio.components.configs.config_file import (
            DownloadConfig,
            QualitySettings,
        )

        ui, _ = self._make_ui()
        config_a = DownloadConfig(
            type="movies", quality=QualitySettings(preferred="1080p", allow_higher=False)
        )
        config_b = DownloadConfig(
            type="movies", quality=QualitySettings(preferred="1080p", allow_higher=True)
        )
        live_configs: list = [config_a, config_b]

        def _propagate(new_value: bool) -> None:
            for config in live_configs:
                if config and config.quality:
                    config.quality.allow_higher = new_value

        ui.on_4k_toggle(_propagate)

        ui.trigger_4k_toggle()
        assert config_a.quality.allow_higher is True
        assert config_b.quality.allow_higher is True

        ui.trigger_4k_toggle()
        assert config_a.quality.allow_higher is False
        assert config_b.quality.allow_higher is False

    def test_4k_toggle_applies_to_configs_loaded_after_keypress(self):
        from py_stremio.components.configs.config_file import (
            DownloadConfig,
            QualitySettings,
        )
        from py_stremio.services.download import _LiveConfigs

        ui, _ = self._make_ui()
        live_configs = _LiveConfigs()
        ui.on_4k_toggle(live_configs.set_allow_4k)

        ui.trigger_4k_toggle()
        config = DownloadConfig(
            type="series",
            quality=QualitySettings(preferred="1080p", allow_higher=False),
        )
        live_configs.append(config)

        assert config.quality.allow_higher is True

    def test_controls_not_started_when_tty_unsupported(self):
        """In non-TTY contexts (pipes, CI, subprocess captures) the
        keyboard reader must not start a thread that would block on
        stdin or corrupt the terminal mode."""
        from py_stremio.services.controls import KeyboardControls

        ctrl = KeyboardControls()
        # Force the no-raw path even when pytest's stdin happens to be a tty.
        ctrl._supports_raw = False
        ctrl.start()
        try:
            assert ctrl.is_running() is False
        finally:
            ctrl.stop()


# ── KeyboardControls unit tests ───────────────────────────────────────────


class TestKeyboardControls:
    def test_on_dispatch_invokes_handler(self):
        from py_stremio.services.controls import KeyboardControls

        ctrl = KeyboardControls()
        calls: list[str] = []
        ctrl.on("a", lambda: calls.append("a"))
        ctrl.dispatch("a")
        assert calls == ["a"]

    def test_dispatch_is_case_insensitive(self):
        from py_stremio.services.controls import KeyboardControls

        ctrl = KeyboardControls()
        calls: list[str] = []
        ctrl.on("b", lambda: calls.append("b"))
        ctrl.dispatch("B")
        ctrl.dispatch("b")
        assert calls == ["b", "b"]

    def test_dispatch_unknown_key_is_noop(self):
        from py_stremio.services.controls import KeyboardControls

        ctrl = KeyboardControls()
        # Should not raise
        ctrl.dispatch("z")

    def test_dispatch_isolates_handler_exceptions(self):
        from py_stremio.services.controls import KeyboardControls

        ctrl = KeyboardControls()
        seen: list[str] = []
        ctrl.on("x", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        ctrl.on("x", lambda: seen.append("ok"))
        # First handler raises, second must still run.
        ctrl.dispatch("x")
        assert seen == ["ok"]

    def test_multiple_handlers_for_same_key_fire_in_order(self):
        from py_stremio.services.controls import KeyboardControls

        ctrl = KeyboardControls()
        seen: list[str] = []
        ctrl.on("p", lambda: seen.append("first"))
        ctrl.on("p", lambda: seen.append("second"))
        ctrl.dispatch("p")
        assert seen == ["first", "second"]

    def test_start_is_idempotent(self):
        from py_stremio.services.controls import KeyboardControls

        ctrl = KeyboardControls()
        ctrl._supports_raw = False
        ctrl.start()
        ctrl.start()  # second call must not spawn another thread
        ctrl.stop()
