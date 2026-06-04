"""Tests for the interactive CLI menu."""

from py_stremio.components import application


def test_menu_choice_one_scans_without_downloading(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr("builtins.input", lambda _: "1")
    monkeypatch.setattr(application, "scan_library", lambda: calls.append("scan") or [])
    monkeypatch.setattr(application, "update_config_imdb_ids", lambda quiet=False: calls.append("metadata"))
    monkeypatch.setattr(application, "download_folders", lambda folders=None, quiet=True, max_workers=1: calls.append("download"))

    application.run_menu()

    assert calls == ["scan"]
    output = capsys.readouterr().out
    assert "Py-Stremio" in output
    assert "1" in output
    assert "Scan library" in output


def test_menu_choice_four_runs_ordered_scan_metadata_download(monkeypatch):
    calls = []
    folders = [object()]
    answers = iter(["4", "3"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(application, "scan_library", lambda: calls.append("scan") or folders)
    monkeypatch.setattr(application, "update_config_imdb_ids", lambda quiet=False: calls.append("metadata"))
    monkeypatch.setattr(
        application,
        "download_folders",
        lambda folders=None, quiet=True, max_workers=1: calls.append(("download", folders, quiet, max_workers)),
    )

    application.run_menu()

    assert calls == ["scan", "metadata", ("download", folders, True, 3)]


def test_cron_positional_run_all_and_speed_limit(monkeypatch):
    calls = []

    monkeypatch.setattr(application.sys, "argv", ["py-stremio", "4", "50"])
    monkeypatch.setattr(
        application,
        "run_pipeline",
        lambda download=True, quiet=True, max_workers=1, speed_percent=None: calls.append((download, quiet, max_workers, speed_percent)),
    )

    application.run(interactive=False)

    assert calls == [(True, True, 1, 50)]
