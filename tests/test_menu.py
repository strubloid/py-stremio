"""Tests for the interactive CLI menu."""

from py_stremio.components import application


def test_menu_choice_one_scans_without_downloading(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr("builtins.input", lambda _: "1")
    monkeypatch.setattr(application, "scan_library", lambda: calls.append("scan") or [])
    monkeypatch.setattr(application, "update_config_imdb_ids", lambda quiet=False: calls.append("metadata"))
    monkeypatch.setattr(application, "download_folders", lambda folders=None, quiet=True: calls.append("download"))

    application.run_menu()

    assert calls == ["scan"]
    output = capsys.readouterr().out
    assert "Py-Stremio" in output
    assert "1" in output
    assert "Scan library" in output


def test_menu_choice_four_runs_ordered_scan_metadata_download(monkeypatch):
    calls = []
    folders = [object()]

    monkeypatch.setattr("builtins.input", lambda _: "4")
    monkeypatch.setattr(application, "scan_library", lambda: calls.append("scan") or folders)
    monkeypatch.setattr(application, "update_config_imdb_ids", lambda quiet=False: calls.append("metadata"))
    monkeypatch.setattr(application, "download_folders", lambda folders=None, quiet=True: calls.append(("download", folders, quiet)))

    application.run_menu()

    assert calls == ["scan", "metadata", ("download", folders, True)]
