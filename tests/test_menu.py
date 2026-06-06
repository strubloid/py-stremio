"""Tests for the interactive CLI menu."""
from py_stremio.components import application


def test_menu_choice_two_scans_without_downloading(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr("builtins.input", lambda _: "2")
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run",
        lambda self: calls.append("scan") or [],
    )

    application.run_menu()

    assert calls == ["scan"]
    output = capsys.readouterr().out
    assert "Py-Stremio" in output
    assert "2" in output
    assert "Scan library" in output


def test_menu_choice_one_runs_ordered_scan_metadata_download(monkeypatch):
    calls = []
    folders = [object()]
    answers = iter(["1", "3"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run",
        lambda self: calls.append("scan") or folders,
    )
    monkeypatch.setattr(
        "py_stremio.services.metadata.MetadataService.run",
        lambda self, quiet=False: calls.append("metadata"),
    )
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1: calls.append(("download", folders, quiet, max_workers)),
    )

    application.run_menu()

    assert calls == ["scan", "metadata", ("download", folders, True, 3)]


def test_cron_positional_run_all_and_speed_limit(monkeypatch):
    calls = []

    monkeypatch.setattr("py_stremio.app.sys", type("sys", (), {"argv": ["py-stremio", "1", "50"]})())
    monkeypatch.setattr(
        "py_stremio.app.AppService.run_pipeline",
        lambda self, download=True, quiet=True, max_workers=1, speed_percent=None: calls.append((download, quiet, max_workers, speed_percent)),
    )

    application.run(interactive=False)

    assert calls == [(True, True, 1, 50)]
