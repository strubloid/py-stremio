"""Progress bar rendering for concurrent downloads."""
import shutil
import sys
import threading
import time
from typing import Any


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
        return f"[{'?' * width}] {_format_bytes(current)}"
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


def _event_progress_bar(event: dict[str, Any], width: int) -> str:
    if event.get("type") == "bytes":
        return render_progress_bar(event.get("downloaded", 0), event.get("bytes_total", 0), width=width)
    if event.get("type") == "episode_start":
        return render_progress_bar(0, 100, width=width)
    if event.get("type") == "episode_done":
        downloaded = event.get("downloaded")
        bytes_total = event.get("bytes_total")
        if downloaded is not None and bytes_total:
            return render_progress_bar(downloaded, bytes_total, width=width)
        return render_progress_bar(100, 100, width=width)
    return render_progress_bar(event.get("current", 0), event.get("total", 0), width=width)


def _progress_line(event: dict[str, Any], color: bool = False, max_width: int | None = None) -> str:
    title = str(event.get("title") or "Download")
    season = event.get("season")
    episode = event.get("episode")
    current = event.get("current", 0)
    total = event.get("total", 0)
    episode_label_text = f"S{season:02d}E{episode:02d}" if season and episode else "movie"
    bar_width = 24 if not max_width or max_width >= 120 else 14
    bar_text = _event_progress_bar(event, bar_width)
    speed_text = _speed_label(event.get("rate_bps"))
    episode_position_text = f"episode {current}/{total}"

    if max_width:
        episode_position_text = f"{current}/{total}"
        for candidate_bar_width in (bar_width, 8):
            bar_text = _event_progress_bar(event, candidate_bar_width)
            fixed_text = f"  •  {episode_label_text} {bar_text}{speed_text}  ({episode_position_text})"
            title_width = max(8, max_width - len(fixed_text))
            title_text = _truncate_label(title, title_width)
            plain_line = f"  • {title_text} {episode_label_text} {bar_text}{speed_text}  ({episode_position_text})"
            if len(plain_line) <= max_width or candidate_bar_width == 8:
                title = title_text
                break

    title_label = _color(title, ACCENT, color)
    episode_label = _color(episode_label_text, GREEN, color)
    bar = _color_bar(bar_text, color)
    speed = _color(speed_text, GREEN, color)
    episode_position = _color(episode_position_text, DIM, color)
    return f"  {_color('•', GREEN, color)} {title_label} {episode_label} {bar}{speed}  ({episode_position})"


def _progress_key(event: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (event.get("title"), event.get("season"), event.get("episode"))


def build_table(
    headers: list[str],
    rows: list[list[str]],
    colors: list[str] | None = None,
) -> str:
    """Build a Unicode box-drawing table. Cols are auto-sized to content."""
    if not headers:
        return ""
    col_count = len(headers)

    # Normalise rows to col_count
    _rows = []
    for row in rows:
        padded = list(row) + [""] * (col_count - len(row))
        _rows.append(padded[:col_count])

    widths = [len(h) for h in headers]
    for row in _rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

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
    parts.append(_hline("╰", "┴", "╯"))
    return "\n".join(parts)


def make_progress_printer(stream):
    """Return a progress renderer that keeps concurrent episodes on separate lines."""
    active_lines: dict[tuple[Any, Any, Any], str] = {}
    order: list[tuple[Any, Any, Any]] = []
    rendered_count = 0
    last_redraw_at = 0.0
    min_redraw_interval = 0.10
    lock = threading.Lock()
    use_ansi_block = bool(getattr(stream, "isatty", lambda: False)())
    max_line_width = max(40, _terminal_width(stream) - 1) if use_ansi_block else None

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
                stream.write(f"{line}\n")
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
                redraw(force=True)
                return
            is_new_line = key not in active_lines
            if is_new_line:
                order.append(key)
            active_lines[key] = _progress_line(event, color=use_ansi_block, max_width=max_line_width)
            redraw(force=is_new_line or event.get("type") == "episode_start")

    return printer
