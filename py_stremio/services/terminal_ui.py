"""Single-owner terminal presentation for download progress."""
from __future__ import annotations

from collections import deque
import os
import re
import sys
import threading
import time
from typing import Any, TextIO

from rich.console import Console, Group
from rich.live import Live
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _format_bytes(value: int | float) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "0 B"


def _format_eta(seconds: float) -> str:
    """Return a compact ETA string for the table's ``Left`` column.

    Examples: ``23s``, ``1:23``, ``1:23:45``, ``2d 4h``. Returns ``"--"`` for
    unknown or non-positive durations so the column stays aligned.
    """
    if seconds <= 0 or seconds != seconds:  # NaN-safe
        return "--"
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    if minutes:
        return f"{minutes}:{secs:02d}"
    return f"{secs}s"


def _key(event: dict[str, Any]) -> tuple[Any, ...]:
    return (event.get("folder_path"), event.get("title"), event.get("season"), event.get("episode"))


def _item_label(event: dict[str, Any]) -> str:
    season, episode = event.get("season"), event.get("episode")
    return f"S{season:02d}E{episode:02d}" if season is not None and episode is not None else "movie"


def _outcome(event: dict[str, Any]) -> str:
    value = event.get("outcome")
    if value:
        return str(value)
    return "downloaded" if event.get("success") else "failed"


class DownloadUI:
    """Thread-safe facade shared by interactive and plain renderers."""

    interactive = False

    def __init__(
        self,
        stream: TextIO,
        *,
        limiter: Any,
        max_workers: int,
        speed_percent: int,
        max_speed_mbps: float,
        now=time.monotonic,
    ) -> None:
        self.stream = stream
        self.limiter = limiter
        self.workers_ref = [max(1, max_workers)]
        self.speed_ref = [max(1, min(100, speed_percent))]
        self.max_speed_mbps = max_speed_mbps
        self._now = now
        self._lock = threading.RLock()
        self._tasks: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._active: set[tuple[Any, ...]] = set()
        self._terminal: set[tuple[Any, ...]] = set()
        self._planned_totals: dict[tuple[Any, Any, Any], int] = {}
        self._last_bytes: dict[tuple[Any, ...], int] = {}
        self._samples: deque[tuple[float, int]] = deque()

    def __enter__(self) -> "DownloadUI":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def progress(self, event: dict[str, Any]) -> None:
        with self._lock:
            key = _key(event)
            event_type = event.get("type")
            self._tasks[key] = dict(event) if event_type == "episode_start" else {
                **self._tasks.get(key, {}),
                **event,
            }
            total = event.get("total")
            group = (event.get("folder_path"), event.get("title"), event.get("season"))
            if isinstance(total, int) and total > 0:
                self._planned_totals[group] = max(total, self._planned_totals.get(group, 0))
            if event_type == "episode_start":
                self._active.add(key)
                self._terminal.discard(key)
                self._last_bytes.pop(key, None)
            elif event_type == "bytes":
                self._active.add(key)
                downloaded = max(0, int(event.get("downloaded") or 0))
                previous = self._last_bytes.get(key)
                self._last_bytes[key] = downloaded
                if previous is not None and downloaded >= previous:
                    delta = downloaded - previous
                    if delta:
                        self._samples.append((self._now(), delta))
            elif event_type == "episode_done":
                self._active.discard(key)
                self._terminal.add(key)
                self._last_bytes.pop(key, None)
            self._render_event(event)

    def print(self, message: str, *, error: bool = False) -> None:
        del error
        with self._lock:
            self.stream.write(_ANSI_RE.sub("", message) + "\n")
            self.stream.flush()

    def _throughput(self) -> float:
        now = self._now()
        cutoff = now - 2.0
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        if not self._samples:
            return 0.0
        elapsed = max(1.0, now - self._samples[0][0])
        return sum(delta for _, delta in self._samples) / elapsed

    def _remaining(self) -> int:
        planned = sum(self._planned_totals.values())
        return max(0, planned - len(self._terminal))

    def _active_transfers(self) -> int:
        getter = getattr(self.limiter, "get_active_thread_count", None)
        return int(getter()) if getter else 0

    def _limit_label(self) -> str:
        percent = self.speed_ref[0]
        if percent >= 100 or self.max_speed_mbps <= 0:
            return "Unlimited"
        mbps = self.max_speed_mbps * percent / 100
        return f"Limit {mbps:.0f} Mbps ({percent}%)"

    def _max_throughput_label(self) -> str:
        """Return the effective bandwidth ceiling in MB/s for the footer.

        Mirrors ``_limit_label`` so the Mbps and MB/s numbers reflect the
        same percentage of the configured maximum. Returns an empty string
        when the limit is unlimited (the upstream "Unlimited" already implies
        no cap, and a redundant "Max Unlimited/s" would only add noise).
        """
        percent = self.speed_ref[0]
        if percent >= 100 or self.max_speed_mbps <= 0:
            return ""
        mbps = self.max_speed_mbps * percent / 100
        # 1 Mbps = 1_000_000 bits/s = 125_000 bytes/s; _format_bytes uses 1024
        # for unit conversion so the value matches the byte rates shown in
        # per-episode progress lines.
        return f"Max {_format_bytes(mbps * 125_000)}/s"

    def _render_event(self, event: dict[str, Any]) -> None:
        raise NotImplementedError


class PlainDownloadUI(DownloadUI):
    """Durable append-only output for cron, pipes, files, and CI."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_print: dict[tuple[Any, ...], float] = {}

    def _render_event(self, event: dict[str, Any]) -> None:
        key = _key(event)
        event_type = event.get("type")
        title = str(event.get("title") or "Download")
        item = _item_label(event)
        if event_type == "episode_start":
            line = f"[waiting] {title} {item}"
        elif event_type == "episode_done":
            outcome = _outcome(event)
            size = int(event.get("downloaded") or 0)
            detail = f": {_format_bytes(size)}" if size else ""
            reason = event.get("reason") or event.get("error")
            if reason and outcome != "downloaded":
                detail = f": {reason}"
            line = f"[{outcome}] {title} {item}{detail}"
        elif event_type == "bytes":
            now = self._now()
            previous = self._last_print.get(key)
            if previous is not None and now - previous < 1.0:
                return
            self._last_print[key] = now
            downloaded = int(event.get("downloaded") or 0)
            total = int(event.get("bytes_total") or event.get("total_size") or 0)
            progress = f"{downloaded / total:.0%}, " if total else ""
            rate = float(event.get("rate_bps") or 0)
            speed = f", {_format_bytes(rate)}/s" if rate > 0 else ""
            line = f"[progress] {title} {item}: {progress}{_format_bytes(downloaded)}{speed}"
        else:
            return
        self.stream.write(_ANSI_RE.sub("", line) + "\n")
        self.stream.flush()


class RichDownloadUI(DownloadUI):
    """One Rich Live display for all interactive download state."""

    interactive = True

    # Speed values (per-episode rate and aggregate throughput) are held in
    # the display for at least this many seconds so the numbers don't flicker
    # every render frame. The raw ``rate_bps`` / throughput values are still
    # refreshed on every event — only the rendered value is sticky.
    RATE_DISPLAY_INTERVAL = 1.5

    def __init__(self, *args, console: Console | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.console = console or Console(file=self.stream, markup=False)
        self._displayed_rates: dict[tuple[Any, ...], float] = {}
        self._last_rate_update: dict[tuple[Any, ...], float] = {}
        self._displayed_throughput: float | None = None
        self._last_throughput_update: float | None = None
        # Use an empty Group as the seed renderable so the init-time call to
        # _build_renderable() doesn't pollute the speed caches with the
        # pre-event 0.0 values.
        self._live = Live(
            Group(),
            console=self.console,
            refresh_per_second=8,
            transient=True,
            redirect_stdout=True,
            redirect_stderr=True,
        )

    def start(self) -> None:
        self._live.start(refresh=True)

    def stop(self) -> None:
        self._live.stop()

    def print(self, message: str, *, error: bool = False) -> None:
        style = "red" if error else None
        with self._lock:
            self.console.print(Text.from_ansi(message), style=style)

    def _stable_rate(self, key: tuple[Any, ...], instant_rate: float) -> float:
        """Hold the displayed per-episode rate for ``RATE_DISPLAY_INTERVAL``."""
        now = self._now()
        last = self._last_rate_update.get(key)
        if last is None or now - last >= self.RATE_DISPLAY_INTERVAL:
            self._displayed_rates[key] = instant_rate
            self._last_rate_update[key] = now
        return self._displayed_rates.get(key) or 0.0

    def _stable_throughput(self, instant_throughput: float) -> float:
        """Hold the displayed aggregate throughput for the same interval."""
        now = self._now()
        last = self._last_throughput_update
        if last is None or now - last >= self.RATE_DISPLAY_INTERVAL:
            self._displayed_throughput = instant_throughput
            self._last_throughput_update = now
        return self._displayed_throughput or 0.0

    def _render_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "episode_done":
            title = str(event.get("title") or "Download")
            item = _item_label(event)
            outcome = _outcome(event)
            color = {"downloaded": "green", "cancelled": "yellow", "skipped": "dim"}.get(outcome, "red")
            reason = event.get("reason") or event.get("error")
            suffix = f": {reason}" if reason and outcome != "downloaded" else ""
            self.console.print(Text(f"[{outcome}] {title} {item}{suffix}", style=color))
            # Drop the cached rate for the finished episode so a later
            # download that reuses the same key (rare) doesn't inherit a
            # stale speed.
            key = _key(event)
            self._displayed_rates.pop(key, None)
            self._last_rate_update.pop(key, None)
        self._live.update(self._build_renderable(), refresh=True)

    def _build_renderable(self) -> Group:
        throughput = self._stable_throughput(self._throughput())
        active_count = len(self._active)
        transferring = self._active_transfers()
        # Only show the "(N downloading)" annotation when some active items
        # are still searching/waiting — otherwise it just adds noise.
        active_label = (
            f"{active_count} active ({transferring} downloading)"
            if transferring < active_count
            else f"{active_count} active"
        )
        header = Text(
            f"Downloads  {active_label} / {self._remaining()} remaining"
            + (f"  {_format_bytes(throughput)}/s" if throughput else ""),
            style="bold cyan",
        )
        table = Table(expand=True, box=None, padding=(0, 1), show_header=True)
        table.add_column("Title", ratio=3, no_wrap=True, overflow="ellipsis")
        table.add_column("Item", width=8, no_wrap=True)
        table.add_column("Stage", width=12, no_wrap=True)
        table.add_column("Progress", ratio=2)
        table.add_column("Speed", width=11, justify="right", no_wrap=True)
        table.add_column("Size", width=9, justify="right", no_wrap=True)
        table.add_column("Left", width=9, justify="right", no_wrap=True)
        for key in list(self._active):
            event = self._tasks.get(key, {})
            downloaded = int(event.get("downloaded") or 0)
            total = int(event.get("bytes_total") or event.get("total_size") or 0)
            if event.get("type") == "bytes" and downloaded > 0:
                stage = "downloading"
            elif any(event.get(name) is not None for name in ("server_total", "live_total", "experimental_total")):
                stage = "searching"
            else:
                stage = "waiting"
            if total > 0:
                progress: Any = ProgressBar(total=total, completed=downloaded, width=None)
            elif downloaded > 0:
                # Chunked / no-Content-Length streams: the source is paying
                # us bytes, we just don't know how many are coming. Show the
                # received total with a sizing label instead of a fake 0%
                # bar that looks stuck.
                progress = Text(
                    f"{_format_bytes(downloaded)} · sizing",
                    style="dim",
                )
            else:
                progress = ProgressBar(total=100, completed=0, width=None)
            instant_rate = float(event.get("rate_bps") or 0)
            rate = self._stable_rate(key, instant_rate)
            speed_cell = f"{_format_bytes(rate)}/s" if rate else "--"
            size_cell = _format_bytes(total) if total else "--"
            if total > 0 and downloaded > 0 and rate > 0:
                eta_seconds = (total - downloaded) / rate
            else:
                eta_seconds = 0
            table.add_row(
                Text(str(event.get("title") or "Download")),
                _item_label(event),
                stage,
                progress,
                speed_cell,
                size_cell,
                _format_eta(eta_seconds),
            )
        max_label = self._max_throughput_label()
        max_segment = f"  |  {max_label}" if max_label else ""
        footer = Text(
            f"{self._limit_label()}{max_segment}  |  Worker limit {self.workers_ref[0]}"
            f"  |  Downloading {self._active_transfers()}  |  Ctrl+C cancel",
            style="dim",
        )
        return Group(header, table, footer)


def create_download_ui(
    stream: TextIO,
    *,
    limiter: Any,
    max_workers: int,
    speed_percent: int,
    max_speed_mbps: float,
    input_stream: TextIO | None = None,
) -> DownloadUI:
    """Select interactive Rich output only when input and output are terminals."""
    input_stream = input_stream or sys.stdin
    interactive = (
        bool(getattr(stream, "isatty", lambda: False)())
        and bool(getattr(input_stream, "isatty", lambda: False)())
        and os.environ.get("TERM", "") != "dumb"
    )
    cls = RichDownloadUI if interactive else PlainDownloadUI
    return cls(
        stream,
        limiter=limiter,
        max_workers=max_workers,
        speed_percent=speed_percent,
        max_speed_mbps=max_speed_mbps,
    )
