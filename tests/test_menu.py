"""Tests for the interactive CLI menu."""
from py_stremio.components import application


def test_menu_choice_two_updates_library(monkeypatch, capsys):
    """Menu option 2 = Update library only (no downloads)."""
    calls = []
    answers = iter(["2", "5"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))
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
    """Menu option 1 = Download (does scan + metadata + download)."""
    calls = []
    folders = [object()]
    answers = iter(["1", "4", "55", "5"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run_with_metadata",
        lambda self, metadata, quiet=False: calls.append(("library-sync", metadata, quiet)) or folders,
    )
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: calls.append(("download", folders, quiet, max_workers, speed_percent)),
    )

    application.run_menu()

    assert calls[0][0] == "library-sync"
    assert calls[0][2] is False
    assert calls[1] == ("download", folders, True, 4, 55)


def test_menu_choice_one_combined_download(monkeypatch):
    """Menu option 1 = combined download (no separate update step needed)."""
    calls = []
    folders = [object()]
    answers = iter(["1", "4", "60", "5"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run_with_metadata",
        lambda self, metadata, quiet=False: calls.append(("library-sync", metadata)) or folders,
    )
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: calls.append(("download", folders, quiet, max_workers, speed_percent)),
    )

    application.run_menu()

    assert calls[0][0] == "library-sync"
    assert calls[1] == ("download", folders, True, 4, 60)


def test_menu_choice_one_asks_threads_and_speed_before_download(monkeypatch):
    """Menu option 1 should ask for threads and speed before downloading."""
    calls = []
    answers = iter(["1", "4", "60", "5"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run_with_metadata",
        lambda self, metadata, quiet=False: [],
    )
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: calls.append((folders, quiet, max_workers, speed_percent)),
    )

    application.run_menu()

    assert calls == [([], True, 4, 60)]


def test_menu_choice_three_addons_submenu_experimental(monkeypatch, capsys):
    """Menu option 3 = Addons submenu, then 4 = Experimental addons."""
    answers = iter(["3", "4", "5", "5"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        "py_stremio.components.addons.experimental.generate_experimental_urls",
        lambda: ["https://example.test"],
    )

    application.run_menu()

    output = capsys.readouterr().out
    assert "Generated 1 URL(s) in addons/experimental.txt" in output


def test_menu_choice_one_prints_library_sync_status_before_blocking_work(monkeypatch, capsys):
    answers = iter(["1", "2", "100", "5"])
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
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: None,
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
    """`py-stremio --run THREADS SPEED` runs the full pipeline with cron-friendly defaults."""
    calls = []

    def fake_run_pipeline(self, download=True, quiet=True, max_workers=1, speed_percent=None):
        calls.append((download, quiet, max_workers, speed_percent))
        return None

    monkeypatch.setattr("py_stremio.app.sys", type("sys", (), {"argv": ["py-stremio", "--run", "5", "80"]})())
    monkeypatch.setattr("py_stremio.app.AppService.run_pipeline", fake_run_pipeline)

    application.run(interactive=False)

    assert calls == [(True, True, 5, 80)]


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
            "cli_overrides": {},
        }
    ]


def test_cron_entrypoint_download_uses_shared_parser_with_cron_presets(monkeypatch):
    from py_stremio.app import AppService

    calls = []

    monkeypatch.setattr("py_stremio.app.sys", type("sys", (), {"argv": ["py-stremio-cron", "--download-only"]})())
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: calls.append((folders, quiet, max_workers, speed_percent)),
    )

    AppService().run(interactive=False, default_max_workers=5, default_speed_percent=80)

    assert calls == [(None, True, 5, 80)]


def test_cron_entrypoint_update_and_download_uses_shared_parser(monkeypatch):
    from py_stremio.app import AppService

    calls = []
    folders = [object()]

    monkeypatch.setattr("py_stremio.app.sys", type("sys", (), {"argv": ["py-stremio-cron", "--update-and-download"]})())
    monkeypatch.setattr(
        "py_stremio.services.scanner.ScanService.run",
        lambda self: calls.append("scan") or folders,
    )
    monkeypatch.setattr(
        "py_stremio.services.metadata.MetadataService.run",
        lambda self, folders=None, quiet=False, **kwargs: calls.append(("metadata", folders)),
    )
    monkeypatch.setattr(
        "py_stremio.services.download.DownloadService.run",
        lambda self, folders=None, quiet=True, max_workers=1, speed_percent=None: calls.append(("download", folders, quiet, max_workers, speed_percent)),
    )

    AppService().run(interactive=False, default_max_workers=5, default_speed_percent=80)

    assert calls[0] == "scan"
    assert calls[1] == ("metadata", folders)
    assert calls[2] == ("download", folders, True, 5, 80)


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


def test_root_cli_flag_overrides_env(monkeypatch):
    """The ``--root PATH`` flag must override the ``.env``-loaded
    ``ROOT_FOLDER`` without requiring the user to edit the shared
    ``.env``.  Critical for the network-share workflow where the
    ``.env`` lives on a mount that is read-only on some clients."""
    import sys
    from py_stremio import main
    from py_stremio.components.configs.app_settings import settings

    # Pretend the .env says /mnt/d/shared/stremio-downloads, which
    # is the original author's machine.  The user on the network
    # share wants to point at their own /home/strubloid/windows/...
    # path instead.
    original_root = settings.ROOT_FOLDER
    sys.argv = ["py-stremio", "--root", "/home/strubloid/windows/stremio-downloads"]
    try:
        overrides = main._apply_cli_env_overrides()
    finally:
        sys.argv = ["py-stremio"]
    assert overrides == {"ROOT_FOLDER": "/home/strubloid/windows/stremio-downloads"}
    assert settings.ROOT_FOLDER.as_posix() == "/home/strubloid/windows/stremio-downloads"
    assert settings.SERIES_FOLDER.as_posix() == "/home/strubloid/windows/stremio-downloads/series"
    assert settings.MOVIES_FOLDER.as_posix() == "/home/strubloid/windows/stremio-downloads/movies"
    # Restore so we do not leak the override into other tests.
    settings.reapply_root(original_root)


def test_root_cli_flag_equals_syntax(monkeypatch):
    """``--root=PATH`` (single-arg form) must also work."""
    import sys
    from py_stremio import main
    from py_stremio.components.configs.app_settings import settings

    original_root = settings.ROOT_FOLDER
    sys.argv = ["py-stremio", "--root=/tmp/alt-library"]
    try:
        overrides = main._apply_cli_env_overrides()
    finally:
        sys.argv = ["py-stremio"]
    assert overrides == {"ROOT_FOLDER": "/tmp/alt-library"}
    assert settings.ROOT_FOLDER.as_posix() == "/tmp/alt-library"
    settings.reapply_root(original_root)


def test_key_cli_flag_overrides_env(monkeypatch):
    """The ``--key NAME=VALUE`` flag must promote a one-off env var."""
    import os
    import sys
    from py_stremio import main

    sys.argv = ["py-stremio", "--key", "DOWNLOAD_THREADS=8"]
    try:
        overrides = main._apply_cli_env_overrides()
    finally:
        sys.argv = ["py-stremio"]
    assert overrides == {"DOWNLOAD_THREADS": "8"}
    assert os.environ.get("DOWNLOAD_THREADS") == "8"
