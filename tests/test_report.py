"""Tests for compact report formatting."""
from py_stremio.components.report import ReportData, format_terminal_report


def test_terminal_report_is_compact_and_limits_failure_details():
    report = ReportData(
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

    output = format_terminal_report(report)

    assert "Py-Stremio" in output
    assert "18 failed" in output
    assert "series" in output
    assert "10 failed" in output
    assert "4: failed" not in output
    assert "+ 7 more" in output
