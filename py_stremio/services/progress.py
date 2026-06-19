"""Progress bar rendering for concurrent downloads — with stage indicators.

Each download line now shows **three stage indicators** when active::

    • Below Deck S08E04 [████████████████░░░░░░] 85% 342 MB · 4.2 MB/s  (1/6) T 67% [█████░░░░░░] L 89% [████████░░░░] E 0% [░░░░░░░░░░]

    T = Total servers being tested (addon discovery / preflight scan)
    L = Live / valid servers returning streams (stream resolution)
    E = Experimental / extra servers fallback (last-resort tier)

Stages that aren't applicable show ──.  The renderer redraws at ~10 fps so
changing numbers give a live animation feel without flooding the terminal.
"""
import re
import shutil
import sys
import threading
import time
from typing import Any


def _display_len(text: str) -> int:
    """Return visible character length, ignoring ANSI escape sequences."""
    return len(re.sub(r"\033\[[0-9;]*m", "", text))


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


ACCENT = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"


def _format_bytes(byte_count: int) -> str:
    if byte_count < 1024:
        return f"{byte_count} B"
    if byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f} KB"
    mb = byte_count / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"


def render_progress_bar(current: int, total: int, width: int = 24) -> str:
    """Render a compact 0-100% progress bar."""
    if total <= 0:
        # Unknown total size (chunked / no Content-Length) — show sizing state
        return f"[{'░' * width}] {_format_bytes(current)} · sizing"
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(width * ratio))
    percent = int(round(ratio * 100))
    return f"[{'█' * filled}{'-' * (width - filled)}] {percent}% {_format_bytes(current)} / {_format_bytes(total)}"


def _color(text: str, color: str, enabled: bool) -> str:
    return f"{color}{text}{RESET}" if enabled else text


def _speed_label(rate_bps: int | float | None) -> str:
    if not rate_bps or rate_bps <= 0:
        return ""
    return f" · {_format_bytes(int(rate_bps))}/s"


def _color_bar(bar: str, enabled: bool) -> str:
    if not enabled or not bar.startswith("[") or "]" not in bar:
        return bar
    close = bar.index("]")
    segment = bar[1:close]
    rest = bar[close + 1:]
    filled_count = segment.count("█")
    filled = _color("█" * filled_count, GREEN, True)
    empty = _color(segment[filled_count:], DIM, True)
    return f"[{filled}{empty}]{_color(rest, YELLOW, True)}"


def _truncate_label(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    if len(text) <= max_width:
        return text
    if max_width <= 1:
        return "…"
    return f"{text[:max_width - 1]}…"


def _terminal_width(stream) -> int:
    columns = getattr(stream, "columns", None)
    if isinstance(columns, int) and columns > 0:
        return columns
    return shutil.get_terminal_size(fallback=(100, 24)).columns


# ── Stage percent helpers ────────────────────────────────────────────────

_DASH = f"{DIM}──{RESET}"


def _stage_pct(current: int | None, total: int | None) -> str:
    """Return a short percentage string like '67%' or '──' when N/A."""
    if current is None and total is None:
        return _DASH
    if current is None or total is None or total < 0:
        return _DASH
    if total == 0:
        return "0%"
    pct = int(round(max(0, min(100, current / total * 100))))
    # Color the percentage based on value
    if pct >= 100:
        return f"{GREEN}{pct}%{RESET}"
    if pct >= 50:
        return f"{YELLOW}{pct}%{RESET}"
    return f"{pct}%"


def _stage_block(stage: str, event: dict[str, Any], bar_width: int = 10) -> str:
    """Render one stage indicator block (T / L / E) from the event dict.

    Uses prefixed keys::

        T ← server_current / server_total
        L ← live_current / live_total
        E ← experimental_current / experimental_total

    Returns empty string when no stage data is present in the event.

    Renders as: ``T 67% [█████░░░░░]``
    """
    cur = event.get(f"{stage}_current")
    tot = event.get(f"{stage}_total")
    if cur is None and tot is None:
        return ""
    # Hide the block when the stage never did anything (still zeroed)
    if cur == 0 and tot == 0:
        return ""
    label = {"server": "T", "live": "L", "experimental": "E"}.get(stage, stage[:1].upper())
    pct = _stage_pct(cur, tot)

    # Small inline progress bar for this stage
    if tot is not None and tot > 0:
        ratio = max(0.0, min(1.0, cur / tot)) if cur else 0.0
        filled = int(round(bar_width * ratio))
        bar = f"[{'█' * filled}{'░' * (bar_width - filled)}]"
    else:
        bar = f"[{'░' * bar_width}]"

    return f"{label} {pct} {bar}"


# ── Event → line rendering ───────────────────────────────────────────────


def _waiting_progress_bar(width: int) -> str:
    return f"[{'-' * width}] waiting for download"


def _event_progress_bar(event: dict[str, Any], width: int) -> str:
    if event.get("type") == "bytes":
        downloaded = event.get("downloaded", 0)
        bytes_total = event.get("bytes_total", 0)
        # Tiny downloads (< 1 MB total received OR unknown total size) are
        # not real video files — they're error pages, redirect responses,
        # Cloudflare challenges, or addon JSON metadata.  Never show a fake
        # percentage bar for these.
        #
        # bytes_total == 0 means chunked streaming with no Content-Length;
        # the tiny bytes received are addon responses, not video data.
        if downloaded < 1024 * 1024 or bytes_total <= 0:
            if downloaded > 0:
                return f"[{'░' * width}] {_format_bytes(downloaded)} · sizing"
            return _waiting_progress_bar(width)
        return render_progress_bar(downloaded, bytes_total, width=width)
    if event.get("type") == "episode_start":
        return _waiting_progress_bar(width)
    if event.get("type") == "episode_done":
        downloaded = event.get("downloaded")
        bytes_total = event.get("bytes_total")
        if downloaded is not None and bytes_total:
            return render_progress_bar(downloaded, bytes_total, width=width)
        return render_progress_bar(100, 100, width=width)
    # Type-less events with stage data (addon discovery phase) — no byte information
    # to display, so render as a clean "scanning" bar instead of using position
    # values (current/total) as fake byte sizes.
    if not event.get("type") and (event.get("server_total") is not None or event.get("live_total") is not None):
        return _waiting_progress_bar(width)
    # Catch-all: never render current/total (episode position counters) as bytes
    # unless there's a genuine downloaded bytes field in the event.
    if not event.get("downloaded"):
        return _waiting_progress_bar(width)
    return render_progress_bar(event.get("current", 0), event.get("total", 0), width=width)


def _progress_line(event: dict[str, Any], color: bool = False, max_width: int | None = None) -> str:
    """Render one progress line with fixed-width columns for tabular alignment.

    Columns (in order)::

        1. Bullet   (3 chars: `` ·``)
        2. Title    (min 15, grows with terminal, left-aligned)
        3. Episode  (9 chars: ``S08E04  `` or ``movie   ``)
        4. Bar      (24 or 14 chars)
        5. Speed    (variable, e.g. `` · 4.2 MB/s``)
        6. Position (8 chars: ``(  1/6)`` — left-aligned)
        7. Stage    (T/L/E indicators, right-most)

    All lines share the same column widths so everything aligns vertically
    without printing a visible grid.
    """
    title_raw = str(event.get("title") or event.get("type", "Download"))
    season = event.get("season")
    episode_num = event.get("episode")
    current = event.get("current", 0)
    total = event.get("total", 0)

    # ── Build each segment ──
    episode_label = f"S{season:02d}E{episode_num:02d}" if season and episode_num else "movie"
    bar_width = 24 if not max_width or max_width >= 120 else 14
    bar_text = _event_progress_bar(event, bar_width)
    speed_text = _speed_label(event.get("rate_bps"))
    stage_text = " ".join(filter(None, (
        _stage_block("server", event),
        _stage_block("live", event),
        _stage_block("experimental", event),
    )))

    # ── Fixed-width columns ──
    EPISODE_W = 9       # "S08E04  " or "movie   "
    POS_W = 8           # "(  1/6)" — left-aligned

    episode_col = episode_label.ljust(EPISODE_W)
    pos_col = f"({current}/{total})".ljust(POS_W)

    # ── Compute suffix (everything after title) ──
    suffix = f" {episode_col} {bar_text}{speed_text} {pos_col} {stage_text}"
    suffix_len = _display_len(suffix)

    # ── Title column: fill available space, min 15 ──
    bullet_len = _display_len("  · ")
    if max_width:
        title_w = max(15, max_width - bullet_len - suffix_len)
        title = _truncate_label(title_raw, title_w)
    else:
        title = title_raw
    # Left-align the title field to its max width
    title_col = title.ljust(max(15, _display_len(title)))

    # ── Assemble ──
    if color:
        bullet = _color("·", GREEN, True)
        title_label = _color(title_col, ACCENT, True)
        episode_label_colored = _color(episode_col, GREEN, True)
        bar = _color_bar(bar_text, True)
        speed = _color(speed_text, GREEN, True)
        pos_label = _color(pos_col, DIM, True)
        stage = _color(stage_text, YELLOW, True)
        return f"  {bullet} {title_label} {episode_label_colored} {bar}{speed} {pos_label} {stage}"

    return f"  · {title_col} {episode_col} {bar_text}{speed_text} {pos_col} {stage_text}"


def _progress_key(event: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (event.get("title"), event.get("season"), event.get("episode"))


def build_table(
    headers: list[str],
    rows: list[list[str]],
    colors: list[str] | None = None,
    separators_after: set[int] | None = None,
) -> str:
    """Build a Unicode box-drawing table. Cols are auto-sized to content.

    `separators_after` is a set of row indices (0-based) after which a
    horizontal rule (`├─┼─┤`) will be drawn -- useful for grouping rows.
    """
    if not headers:
        return ""
    col_count = len(headers)

    # Normalise rows to col_count
    _rows = []
    for row in rows:
        padded = list(row) + [""] * (col_count - len(row))
        _rows.append(padded[:col_count])

    widths = [_display_len(h) for h in headers]
    for row in _rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_len(cell))

    pad = 2  # one space each side
    col_widths = [w + pad for w in widths]

    def _hline(left: str, mid: str, right: str) -> str:
        return left + mid.join("─" * w for w in col_widths) + right

    def _cell(row_idx: int | None, col_idx: int) -> str:
        """Render one cell with optional color."""
        if row_idx is not None and row_idx < len(_rows) and col_idx < len(_rows[row_idx]):
            cell = _rows[row_idx][col_idx]
        elif row_idx is None and col_idx < len(headers):
            cell = headers[col_idx]
        else:
            cell = ""
        text = f" {cell:<{widths[col_idx]}} "
        if row_idx is not None and colors and col_idx < len(colors):
            text = f"{colors[col_idx]}{text}{RESET}"
        return text

    parts = [_hline("╭", "┬", "╮")]
    # Header row
    parts.append("│" + "│".join(_cell(None, i) for i in range(col_count)) + "│")
    parts.append(_hline("├", "┼", "┤"))
    # Data rows
    for ri in range(len(_rows)):
        row = _rows[ri]
        parts.append("│" + "│".join(_cell(ri, i) for i in range(col_count)) + "│")
        if separators_after and ri in separators_after:
            parts.append(_hline("├", "┼", "┤"))
    parts.append(_hline("╰", "┴", "╯"))
    return "\n".join(parts)


def make_progress_printer(stream):
    """Return a progress renderer that keeps concurrent episodes on separate lines.

    Each event dict can carry optional **stage keys** that get rendered as T/L/E
    indicators at the end of the progress line::

        server_current  / server_total     → T xx%  (addon preflight scan)
        live_current    / live_total       → L xx%  (stream resolution)
        experimental_current / experimental_total  → E xx%  (experimental fallback)
    """
    active_lines: dict[tuple[Any, Any, Any], str] = {}
    order: list[tuple[Any, Any, Any]] = []
    rendered_count = 0
    last_redraw_at = 0.0
    last_print_at: dict[tuple[Any, Any, Any], float] = {}
    min_redraw_interval = 0.10
    min_print_interval = 1.0  # at most 1 line per second per episode in append-only mode
    lock = threading.Lock()
    use_ansi_block = bool(getattr(stream, "isatty", lambda: False)())
    use_color = bool(getattr(stream, "isatty", lambda: False)())
    max_line_width = _terminal_width(stream) - 1

    def redraw(force: bool = False) -> None:
        nonlocal rendered_count, last_redraw_at
        now = time.monotonic()
        if not force and use_ansi_block and now - last_redraw_at < min_redraw_interval:
            return
        previous_count = rendered_count
        if use_ansi_block and previous_count:
            stream.write("\033[F" * previous_count)
        for key in order:
            line = active_lines[key]
            if use_ansi_block:
                stream.write(f"\r\033[K{line}\n")
            else:
                # Rate-limit: skip this line if we printed it less than 1s ago
                last = last_print_at.get(key)
                if last is not None and not force and now - last < min_print_interval:
                    continue
                stream.write(f"{line}\n")
                last_print_at[key] = now
        if use_ansi_block and previous_count > len(order):
            extra_lines = previous_count - len(order)
            for _ in range(extra_lines):
                stream.write("\r\033[K\n")
            stream.write("\033[F" * extra_lines)
        stream.flush()
        rendered_count = len(order) if use_ansi_block else 0
        last_redraw_at = now

    def printer(event: dict[str, Any]) -> None:
        with lock:
            key = _progress_key(event)
            if event.get("type") == "episode_done":
                active_lines.pop(key, None)
                if key in order:
                    order.remove(key)
                if use_ansi_block:
                    redraw(force=True)
                return
            is_new_line = key not in active_lines
            if is_new_line:
                order.append(key)
            active_lines[key] = _progress_line(event, color=use_color, max_width=max_line_width)
            if not use_ansi_block:
                now = time.monotonic()
                last = last_print_at.get(key)
                force_line = is_new_line or event.get("type") == "episode_start"
                if force_line or last is None or now - last >= min_print_interval:
                    stream.write(f"{active_lines[key]}\n")
                    stream.flush()
                    last_print_at[key] = now
                return
            redraw(force=is_new_line or event.get("type") == "episode_start")

    return printer
