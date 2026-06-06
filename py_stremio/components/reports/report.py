"""Report generation for terminal and email."""
from dataclasses import dataclass
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from py_stremio.components.configs.app_settings import settings
from py_stremio.services.progress import build_table


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


def format_terminal_report(data: ReportData) -> str:
    """Format a compact modern terminal report with tables."""
    mode = "DRY RUN" if data.dry_run else "LIVE"
    status = "OK" if data.total_failed == 0 else "ATTENTION"
    lines = [
        "",
        "╭─ Py-Stremio summary ─────────────────────────────╮",
        f"│ {mode:<8} · {data.total_folders} folders · {data.total_downloaded} downloaded · {data.total_failed} failed",
        f"│ {data.timestamp} · {status}",
        "╰──────────────────────────────────────────────────╯",
    ]

    # Build per-folder table
    rows: list[list[str]] = []
    for folder in data.folders:
        folder_type = folder.get("type", "folder")
        name = folder.get("name", "unknown")

        if folder.get("skipped"):
            skip_reason = folder.get("reason", "unknown")
            rows.append([name, folder_type, "--", "◌", skip_reason])
            continue

        downloaded_count = _folder_count(folder, "downloaded")
        failed_count = _folder_count(folder, "failed")

        dsp = str(downloaded_count) if downloaded_count else "0"
        if failed_count:
            fsp = str(failed_count)
            rows.append([name, folder_type, dsp, "!", f"{failed_count} failed"])
        elif downloaded_count:
            rows.append([name, folder_type, dsp, "✓", ""])
        else:
            rows.append([name, folder_type, "0", "·", "nothing to do"])

    if rows:
        lines.append("")
        lines.append(build_table(
            ["Folder", "Type", "Downloaded", "", "Detail"],
            rows,
        ))

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
