"""Tests for compact report formatting."""
from py_stremio.components.reports import report as report_module
from py_stremio.components.reports.report import (
    ReportData,
    format_terminal_report,
    print_and_send_report,
    send_email_report,
)


def _report_data() -> ReportData:
    return ReportData(
        timestamp="2026-06-04 00:42:52",
        total_folders=2,
        processed_folders=2,
        skipped_folders=0,
        total_downloaded=0,
        total_failed=18,
        dry_run=False,
        folders=[
            {
                "name": "s01",
                "type": "series",
                "path": "/tmp/s01",
                "downloaded": [],
                "failed": [f"{i}: failed" for i in range(1, 11)],
            }
        ],
    )


def test_terminal_report_is_compact_and_limits_failure_details():
    report = _report_data()

    output = format_terminal_report(report)

    assert "Py-Stremio" in output
    assert "18 failed" in output
    assert "series" in output
    assert "10 failed" in output
    assert "4: failed" not in output
    assert "+ 7 more" in output


def test_send_email_report_requires_core_smtp_settings(monkeypatch):
    monkeypatch.setattr(report_module.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(report_module.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(report_module.settings, "SMTP_USER", None)
    monkeypatch.setattr(report_module.settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(report_module.settings, "SMTP_FROM", None)
    monkeypatch.setattr(report_module.settings, "SMTP_TO", "to@example.com")

    assert send_email_report(_report_data()) is False


def test_send_email_report_uses_smtp_user_as_default_from(monkeypatch):
    sent_messages = []

    class FakeSMTP:
        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.started_tls = False
            self.login_args = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def starttls(self):
            self.started_tls = True

        def login(self, user, password):
            self.login_args = (user, password)

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(report_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(report_module.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(report_module.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(report_module.settings, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(report_module.settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(report_module.settings, "SMTP_FROM", None)
    monkeypatch.setattr(report_module.settings, "SMTP_TO", "to@example.com")
    monkeypatch.setattr(report_module.settings, "SMTP_USE_TLS", True)

    assert send_email_report(_report_data()) is True
    assert sent_messages[0]["From"] == "user@example.com"
    assert sent_messages[0]["To"] == "to@example.com"


def test_print_and_send_report_sends_email(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(report_module, "send_email_report", lambda data: calls.append(data) or True)

    data = _report_data()
    print_and_send_report(data)

    assert "Py-Stremio" in capsys.readouterr().out
    assert calls == [data]
