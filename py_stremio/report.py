"""Report generation for terminal and email."""
from dataclasses import dataclass
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from .settings import settings


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


def format_terminal_report(data: ReportData) -> str:
    """Format report for terminal display."""
    lines = []
    lines.append("=" * 60)
    lines.append("  PY-STREMIO DOWNLOAD MANAGER REPORT")
    lines.append("=" * 60)
    lines.append(f"  Timestamp: {data.timestamp}")
    lines.append(f"  Mode: {'DRY RUN' if data.dry_run else 'LIVE'}")
    lines.append("-" * 60)
    lines.append(f"  Total folders scanned: {data.total_folders}")
    lines.append(f"  Folders processed: {data.processed_folders}")
    lines.append(f"  Folders skipped: {data.skipped_folders}")
    lines.append(f"  Total downloads: {data.total_downloaded}")
    lines.append(f"  Total failures: {data.total_failed}")
    lines.append("-" * 60)

    for folder in data.folders:
        lines.append(f"\n  [{folder['type'].upper()}] {folder['name']}")
        if folder.get("skipped"):
            lines.append(f"    Status: SKIPPED ({folder.get('reason', 'unknown')})")
        else:
            downloaded = folder.get("downloaded", [])
            failed = folder.get("failed", [])
            if downloaded:
                lines.append(f"    Downloaded: {len(downloaded)} item(s)")
                for item in downloaded:
                    lines.append(f"      - {item}")
            if failed:
                lines.append(f"    Failed: {len(failed)} item(s)")
                for item in failed:
                    lines.append(f"      - {item}")
            if not downloaded and not failed:
                lines.append("    No items to download")

    lines.append("=" * 60)
    return "\n".join(lines)


def send_email_report(data: ReportData) -> bool:
    """Send report via email if SMTP is configured."""
    if not settings.smtp_configured:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Py-Stremio Report - {data.timestamp}"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = settings.SMTP_TO

    text_content = format_terminal_report(data)
    html_content = f"""
    <html>
    <body>
        <h2>Py-Stremio Download Report</h2>
        <p><strong>Timestamp:</strong> {data.timestamp}</p>
        <p><strong>Mode:</strong> {'DRY RUN' if data.dry_run else 'LIVE'}</p>
        <hr>
        <p><strong>Total Folders:</strong> {data.total_folders}</p>
        <p><strong>Processed:</strong> {data.processed_folders} | <strong>Skipped:</strong> {data.skipped_folders}</p>
        <p><strong>Downloads:</strong> {data.total_downloaded} | <strong>Failures:</strong> {data.total_failed}</p>
        <hr>
        <h3>Folder Details</h3>
    """

    for folder in data.folders:
        html_content += f"<h4>[{folder['type'].upper()}] {folder['name']}</h4>"
        if folder.get("skipped"):
            html_content += f"<p>Skipped: {folder.get('reason', 'unknown')}</p>"
        else:
            downloaded = folder.get("downloaded", [])
            failed = folder.get("failed", [])
            if downloaded:
                html_content += f"<p>Downloaded: {len(downloaded)}</p><ul>"
                for item in downloaded:
                    html_content += f"<li>{item}</li>"
                html_content += "</ul>"
            if failed:
                html_content += f"<p>Failed: {len(failed)}</p><ul>"
                for item in failed:
                    html_content += f"<li>{item}</li>"
                html_content += "</ul>"

    html_content += "</body></html>"

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"  Email report failed: {e}")
        return False


def print_and_send_report(data: ReportData) -> None:
    """Print terminal report and send email if configured."""
    print()
    print(format_terminal_report(data))
    
    ## disabling this for now
    return None
    if settings.smtp_configured:
        if send_email_report(data):
            print("\nEmail report sent successfully.")
        else:
            print("\nFailed to send email report.")
    else:
        print("\n(Note: SMTP not configured, skipping email report)")