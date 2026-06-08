"""Report generation for terminal and email."""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from py_stremio.components.configs.app_settings import settings
from py_stremio.services.progress import ACCENT, GREEN, YELLOW, DIM, RED, RESET, build_table


@dataclass
class ReportData:
    timestamp: str
    total_folders: int
    processed_folders: int
    skipped_folders: int
    total_downloaded: int
    total_failed: int
    folders: list[dict[str, Any]]
    dry_run: bool


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def _folder_count(folder: dict[str, Any], key: str) -> int:
    count_key = f"{key}_count"
    if count_key in folder:
        return int(folder[count_key] or 0)
    value = folder.get(key, [])
    if isinstance(value, int):
        return value
    return len(value or [])


def _preview_items(items: list[Any], limit: int = 3) -> list[str]:
    preview = [str(item) for item in items[:limit]]
    remaining = len(items) - limit
    if remaining > 0:
        preview.append(f"+ {remaining} more")
    return preview


def _nice_status(entry: dict[str, Any]) -> str:
    """Return a human-friendly one-line status string for a folder entry."""
    if entry.get("skipped"):
        reason = entry.get("reason", "skipped")
        if reason == "disabled":
            return "⬡ disabled"
        if reason == "not_found":
            return "· not found"
        return f"◌ {reason}"

    dl = _folder_count(entry, "downloaded")
    fl = _folder_count(entry, "failed")

    if dl and fl:
        return f"✗ {fl} fail, {dl} ok"
    if dl:
        return f"✓ {dl} new"
    if fl:
        return f"✗ {fl} failed"
    return "· up to date"


def _detail_label(entry: dict[str, Any]) -> str:
    """Return a colorized detail column for a folder entry."""
    if entry.get("skipped"):
        reason = entry.get("reason", "skipped")
        if reason == "disabled":
            return _c("⬡ disabled", DIM)
        if reason == "not_found":
            return _c("· not found", DIM)
        return _c(f"◌ {reason}", DIM)

    dl = _folder_count(entry, "downloaded")
    fl = _folder_count(entry, "failed")

    if dl and fl:
        return _c(f"⚠ {fl} fail", YELLOW)
    if dl:
        return _c(f"✓ {dl} new", GREEN)
    if fl:
        return _c(f"✗ {fl} failed", RED)
    return _c("· up to date", DIM)


def _summary_row(name: str, season_count: int, total_dl: int, total_fail: int, ftype: str) -> list[str]:
    """Build a compact per-series summary row."""
    counts = []
    if total_dl:
        counts.append(_c(str(total_dl), GREEN))
    else:
        counts.append("0")
    if total_fail:
        counts.append(_c(str(total_fail), RED))

    detail = counts[0] if len(counts) == 1 else f"{counts[0]} / {counts[1]}"

    return [
        _c(name, ACCENT),
        _c(f"{season_count} season{'s' if season_count != 1 else ''}", DIM) if season_count else "—",
        detail,
        _c(ftype, DIM),
    ]


def format_terminal_report(data: ReportData) -> str:
    """Format a redesigned terminal report with series grouping and stylish table."""
    mode = "DRY RUN" if data.dry_run else "LIVE"
    status_icon = _c("✓", GREEN) if data.total_failed == 0 else _c("✗", RED)
    status_label = "OK" if data.total_failed == 0 else "FAILURES"

    # ── Summary header (dynamic width) ──────────────────────────────────
    header_content = (
        f"  {mode:<5} · {data.timestamp}  "
        f"{_c(str(data.total_folders), ACCENT)} folders  "
        f"{_c(str(data.total_downloaded), GREEN)} new  "
        f"{_c(str(data.total_failed), RED if data.total_failed else DIM)} failed  "
        f"{status_icon} {status_label}"
    )
    summary_width = max(len(data.timestamp) + 22, 40)
    pad = 2
    total_width = summary_width + pad * 2

    lines = [
        "",
        _c("  ╭─ Py-Stremio Summary ", ACCENT)
        + _c("─" * (total_width - 21), DIM)
        + _c("╮", ACCENT),
        _c(f"  │ {header_content:<{summary_width}} │", ACCENT),
        _c("  ╰" + "─" * total_width + "╯", ACCENT),
    ]

    # Group entries by series (for series type) / stand-alone for movies
    series_groups: OrderedDict[str, list[dict]] = OrderedDict()
    movie_entries: list[dict] = []

    for entry in data.folders:
        ftype = entry.get("type", "")
        fpath = entry.get("path", "")
        if ftype == "series":
            series_name = Path(fpath).parent.name if fpath else "Unknown"
            if series_name not in series_groups:
                series_groups[series_name] = []
            series_groups[series_name].append(entry)
        else:
            movie_entries.append(entry)

    # Build per-folder rows
    table_rows: list[list[str]] = []
    separators_after: set[int] = set()

    row_idx = 0
    for series_name, entries in series_groups.items():
        for i, entry in enumerate(entries):
            folder_name = entry.get("name", "?")
            dl_count = _folder_count(entry, "downloaded")
            detail = _detail_label(entry)
            type_label = _c("series", DIM)

            # Series name on first row (accent), dimmed on sub-rows
            if i == 0:
                name_label = _c(series_name, ACCENT)
            else:
                name_label = _c(series_name, DIM)

            table_rows.append([
                name_label,
                _c(folder_name, GREEN if dl_count else DIM),
                str(dl_count) if not dl_count else _c(str(dl_count), GREEN),
                detail,
                type_label,
            ])
            row_idx += 1

        # Add separator after this group (if more groups follow)
        if row_idx < sum(len(e) for e in series_groups.values()):
            separators_after.add(row_idx - 1)

    for entry in movie_entries:
        name = entry.get("name", "?")
        dl_count = _folder_count(entry, "downloaded")
        detail = _detail_label(entry)
        table_rows.append([
            _c(name, ACCENT),
            _c("—", DIM),
            str(dl_count) if not dl_count else _c(str(dl_count), GREEN),
            detail,
            _c("movie", DIM),
        ])

    if table_rows:
        lines.append("")
        lines.append(build_table(
            ["Series / Movie", "Folder", "DL'd", "Detail", "Type"],
            table_rows,
            colors=[ACCENT, GREEN, GREEN, GREEN, DIM],
            separators_after=separators_after,
        ))

    # Compact per-series summary
    if series_groups:
        lines.append("")
        for series_name, entries in series_groups.items():
            total_dl = sum(_folder_count(e, "downloaded") for e in entries)
            total_fail = sum(_folder_count(e, "failed") for e in entries)
            s_count = len(entries)
            has_issues = any(_folder_count(e, "failed") for e in entries if not e.get("skipped"))
            status_char = _c("✓", GREEN) if total_dl and not total_fail else (_c("⚠", YELLOW) if has_issues else _c("·", DIM))
            detail_parts = []
            if total_dl:
                detail_parts.append(_c(f"{total_dl} downloaded", GREEN))
            if total_fail:
                detail_parts.append(_c(f"{total_fail} failed", RED))
            skipped_count = sum(1 for e in entries if e.get("skipped"))
            if skipped_count:
                detail_parts.append(_c(f"{skipped_count} skipped", DIM))
            detail_str = " · ".join(detail_parts) if detail_parts else _c("nothing to do", DIM)
            season_label = f"{s_count} season{'s' if s_count != 1 else ''}"
            lines.append(
                f"  {status_char} {_c(series_name, ACCENT)}"
                f" — {_c(season_label, DIM)}"
                f" — {detail_str}"
            )

    for entry in movie_entries:
        dl = _folder_count(entry, "downloaded")
        fl = _folder_count(entry, "failed")
        if entry.get("skipped"):
            lines.append(f"  {_c('◌', DIM)} {_c(entry.get('name', '?'), DIM)} — {entry.get('reason', 'skipped')}")
        elif dl and fl:
            lines.append(f"  {_c('⚠', YELLOW)} {_c(entry.get('name', '?'), ACCENT)} — {_c(f'{dl} downloaded, {fl} failed', RED)}")
        elif dl:
            lines.append(f"  {_c('✓', GREEN)} {_c(entry.get('name', '?'), ACCENT)} — {_c(f'{dl} downloaded', GREEN)}")
        elif fl:
            lines.append(f"  {_c('✗', RED)} {_c(entry.get('name', '?'), ACCENT)} — {_c(f'{fl} failed', RED)}")
        else:
            lines.append(f"  {_c('·', DIM)} {_c(entry.get('name', '?'), DIM)}")

    lines.append("")
    return "\n".join(lines)


def send_email_report(data: ReportData) -> bool:
    """Send report via email when all required SMTP settings are present."""
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    user = settings.SMTP_USER
    password = settings.SMTP_PASSWORD
    to_address = settings.SMTP_TO
    from_address = settings.SMTP_FROM or user

    if (
        host is None
        or user is None
        or password is None
        or to_address is None
        or from_address is None
    ):
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Py-Stremio Report - {data.timestamp}"
    msg["From"] = from_address
    msg["To"] = to_address

    text_content = format_terminal_report(data)
    html_content = f"""
    <html>
    <body>
        <h2>Py-Stremio Report</h2>
        <p><strong>Timestamp:</strong> {data.timestamp}</p>
        <p><strong>Mode:</strong> {'DRY RUN' if data.dry_run else 'LIVE'}</p>
        <p><strong>Folders:</strong> {data.total_folders}</p>
        <p><strong>Downloads:</strong> {data.total_downloaded} | <strong>Failures:</strong> {data.total_failed}</p>
    </body></html>
    """

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(host, port) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as exc:
        print(f"  Email report failed: {exc}")
        return False


def print_and_send_report(data: ReportData) -> None:
    """Print terminal report and send email if configured."""
    print(format_terminal_report(data))
    send_email_report(data)
