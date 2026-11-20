"""Dashboard background jobs retain their progress output after completion."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from py_stremio.api.main import app
from py_stremio.storage.db import close_connection


def test_completed_library_update_returns_progress_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "job-progress.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "")
    monkeypatch.setattr("py_stremio.api.main._active_jobs", {})
    monkeypatch.setattr("py_stremio.api.main._completed_job_output", {})
    close_connection()

    class Scanner:
        def run(self, progress_callback):
            progress_callback("Scanning series seasons and movies")
            return ["Example Show S01"]

        def sync_catalog(self, folders, progress_callback):
            progress_callback(f"Catalog updated: {folders[0]} · 0 file(s)")

    class Metadata:
        def run(self, folders, quiet, progress_callback, item_callback):
            progress_callback("Refreshing series metadata: Example Show S01")
            item_callback({
                "title": "Example Show",
                "season": "S01",
                "episodes": "8",
                "imdb_id": "tt1234567",
                "status": "✓",
            })
            progress_callback("Updated series metadata: Example Show S01")
            return 1

    monkeypatch.setattr(
        "py_stremio.app.AppService",
        lambda: SimpleNamespace(scanner=Scanner(), metadata=Metadata()),
    )

    try:
        with TestClient(app) as client:
            started = client.post("/api/jobs/configs")
            assert started.status_code == 202

            jobs = client.get("/api/jobs").json()
            completed = next(run for run in jobs["history"] if run["job"] == "configs")
            messages = [line["message"] for line in completed["output"]]
            assert "Scanning series seasons and movies" in messages
            assert "Refreshing series metadata: Example Show S01" in messages
            assert "✓ Job completed" in messages
            metadata_row = next(line["item"] for line in completed["output"] if line.get("item"))
            assert metadata_row["title"] == "Example Show"
            assert metadata_row["episodes"] == "8"
    finally:
        close_connection()


def test_dashboard_download_sends_progress_to_web_clients_without_terminal_ui(tmp_path, monkeypatch):
    from py_stremio.api import main as api

    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "download-progress.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "")
    monkeypatch.setattr(api, "_active_jobs", {})
    monkeypatch.setattr(api, "_completed_job_output", {})
    close_connection()
    observed = []

    class Downloader:
        def run(self, **kwargs):
            assert kwargs["terminal_output"] is False
            event = {
                "type": "bytes",
                "title": "Below Deck",
                "season": 13,
                "episode": 6,
                "downloaded": 65,
                "bytes_total": 100,
                "rate_bps": 4_000_000,
            }
            kwargs["progress_callback"](event)
            active = api.jobs()["active"]
            observed.extend(active[0]["progress"])
            return SimpleNamespace(
                total_downloaded=1,
                total_failed=0,
                skipped_folders=0,
                folders=[{
                    "type": "series",
                    "path": "/media/series/Below Deck/s13",
                    "downloaded": ["Below Deck_s13e06.mkv"],
                    "failed": [],
                    "failed_reasons": [],
                    "downloaded_count": 1,
                    "failed_count": 0,
                }],
            )

    monkeypatch.setattr("py_stremio.app.AppService", lambda: SimpleNamespace(downloader=Downloader()))

    try:
        with TestClient(app) as client:
            response = client.post("/api/jobs/download-quick")
            assert response.status_code == 202
            assert observed[0]["title"] == "Below Deck"
            assert observed[0]["episode"] == 6
            assert observed[0]["downloaded"] == 65
            completed = next(run for run in api.jobs()["history"] if run["job"] == "download-quick")
            messages = [line["message"] for line in completed["output"]]
            assert "Download report: 1 downloaded · 0 failed · 0 skipped" in messages
            assert "✓ Downloaded: Below Deck s13 · Below Deck_s13e06.mkv" in messages
    finally:
        close_connection()


def test_stop_download_endpoint_requests_cooperative_cancellation(tmp_path, monkeypatch):
    from py_stremio.api import main as api
    from py_stremio.utils.cancellation import clear_shutdown, shutdown_requested

    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "stop-download.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "")
    monkeypatch.setattr(api, "_active_jobs", {
        "download-quick": {
            "job": "download-quick",
            "status": "running",
            "output": [],
            "progress": {},
        },
    })
    clear_shutdown()

    try:
        with TestClient(app) as client:
            response = client.post("/api/jobs/download/stop")

        assert response.status_code == 202
        assert response.json() == {"job": "download-quick", "status": "stopping"}
        assert api._active_jobs["download-quick"]["status"] == "stopping"
        assert api._active_jobs["download-quick"]["stop_requested"] is True
        assert shutdown_requested()
    finally:
        clear_shutdown()
