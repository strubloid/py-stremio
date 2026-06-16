"""Tests for the interactive CLI menu."""
from py_stremio.components import application


def test_menu_choice_two_updates_library(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr("builtins.input", lambda _: "2")
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run",
        lambda self: calls.append("scan") or [],
    )
    monkeypatch.setattr(
        "py_stremio.services.metadata.MetadataService.run",
        lambda self, quiet=False, **kwargs: calls.append("metadata"),
    )

    application.run_menu()

    assert calls == ["scan", "metadata"]
    output = capsys.readouterr().out
    assert "Py-Stremio" in output
    assert "2" in output
    assert "Update library" in output


def test_menu_choice_one_uses_combined_library_sync_before_download(monkeypatch):
    calls = []
    folders = [object()]
    answers = iter(["1"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run_with_metadata",
        lambda self, metadata, quiet=False: calls.append(("library-sync", metadata, quiet)) or folders,
    )
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1: calls.append(("download", folders, quiet, max_workers)),
    )

    application.run_menu()

    assert calls[0][0] == "library-sync"
    assert calls[0][2] is False
    assert calls[1] == ("download", folders, True, 2)


def test_menu_choice_one_prints_library_sync_status_before_blocking_work(monkeypatch, capsys):
    answers = iter(["1"])
    folders = []

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    def fake_sync(self, metadata, quiet=False):
        output_before_sync = capsys.readouterr().out
        assert "Library sync" in output_before_sync
        assert "scan" in output_before_sync.lower()
        assert "metadata" in output_before_sync.lower()
        return folders

    monkeypatch.setattr("py_stremio.services.scanner.ScanService.run_with_metadata", fake_sync)
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1: None,
    )

    application.run_menu()

def test_run_pipeline_uses_combined_library_sync(monkeypatch, capsys):
    from py_stremio.app import AppService

    folders = []

    def fake_sync(self, metadata, quiet=False):
        output_before_sync = capsys.readouterr().out
        assert "Library sync" in output_before_sync
        assert "scan" in output_before_sync.lower()
        assert "metadata" in output_before_sync.lower()
        return folders

    monkeypatch.setattr("py_stremio.services.scanner.ScanService.run_with_metadata", fake_sync)
    monkeypatch.setattr("py_stremio.app.validate_and_update", lambda: None)
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: None,
    )

    AppService().run_pipeline(download=True, quiet=True, max_workers=2)


def test_cron_positional_run_all_and_speed_limit(monkeypatch):
    calls = []

    monkeypatch.setattr("py_stremio.app.sys", type("sys", (), {"argv": ["py-stremio", "1", "50"]})())
    monkeypatch.setattr(
        "py_stremio.app.AppService.run_pipeline",
        lambda self, download=True, quiet=True, max_workers=1, speed_percent=None: calls.append((download, quiet, max_workers, speed_percent)),
    )

    application.run(interactive=False)

    assert calls == [(True, True, 2, 50)]


def test_cron_entrypoint_delegates_to_same_appservice_with_presets(monkeypatch):
    from py_stremio import main

    calls = []

    class FakeAppService:
        def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("py_stremio.main.AppService", lambda: FakeAppService())

    main.run_cron()

    assert calls == [
        {
            "interactive": False,
            "default_max_workers": 5,
            "default_speed_percent": 80,
        }
    ]


def test_cron_entrypoint_download_uses_shared_parser_with_cron_presets(monkeypatch):
    from py_stremio.app import AppService

    calls = []

    monkeypatch.setattr("py_stremio.app.sys", type("sys", (), {"argv": ["py-stremio-cron", "3"]})())
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: calls.append((folders, quiet, max_workers, speed_percent)),
    )

    AppService().run(interactive=False, default_max_workers=5, default_speed_percent=80)

    assert calls == [(None, True, 5, 80)]


def test_run_pipeline_ctrl_c_exits_cleanly(monkeypatch, capsys):
    from py_stremio.app import AppService

    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run_with_metadata",
        lambda self, metadata, quiet=False: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    AppService().run_pipeline(download=True, quiet=True, max_workers=2)

    output = capsys.readouterr().out
    assert "Interrupted" in output
    assert "shutting down" in output.lower()
