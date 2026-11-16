"""Dashboard library and watch-state API behavior."""
from fastapi.testclient import TestClient

from py_stremio.api.main import app
from py_stremio.storage.catalog import (
    get_or_create_season,
    get_or_create_series,
    update_season_artwork,
    update_series_artwork,
    upsert_files,
)
from py_stremio.storage.db import close_connection, fetchone, init_db


def test_dashboard_groups_season_and_persists_episode_watch_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "dashboard.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "test-token")
    close_connection()


def test_library_queues_background_artwork_refresh_for_missing_poster(tmp_path, monkeypatch):
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "artwork-refresh.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "test-token")
    monkeypatch.setattr("py_stremio.storage.compat._storage_backend", "sqlite")
    close_connection()
    refresh_requests = []
    monkeypatch.setattr("py_stremio.api.main._schedule_artwork_refresh", lambda: refresh_requests.append(True))

    with TestClient(app) as client:
        series_id = get_or_create_series("No Poster Show", "series/No Poster Show")
        get_or_create_season(
            series_id,
            1,
            "series/No Poster Show/s01",
            {"episode_count": 1, "available_episodes": [1], "enabled": True},
        )
        response = client.get("/api/library", headers={"Authorization": "Bearer test-token"})

        assert response.status_code == 200
        assert refresh_requests == [True]
    close_connection()

    with TestClient(app) as client:
        series_id = get_or_create_series("Example Show", "series/Example Show", "tt1234567")
        season_id = get_or_create_season(
            series_id,
            1,
            "series/Example Show/s01",
            {"episode_count": 2, "available_episodes": [1, 2], "enabled": True},
        )
        update_series_artwork(series_id, "https://images.example/show.jpg", "https://images.example/backdrop.jpg")
        update_season_artwork(season_id, "https://images.example/season.jpg")
        upsert_files("season", season_id, [{
            "rel_path": "Example.Show.S01E01.mkv",
            "episode": 1,
            "size": 100,
            "mtime_ns": 1,
            "is_part": False,
        }])
        headers = {"Authorization": "Bearer test-token"}

        library = client.get("/api/library", headers=headers).json()
        season = next(entry for entry in library["entries"] if entry["kind"] == "season")
        assert season["series_id"] == series_id
        assert season["episode_numbers"] == [1, 2]
        assert season["poster_url"] == f"/api/artwork/season/{season_id}"
        assert season["background_url"] == f"/api/artwork/series/{series_id}?variant=background"
        poster_file = tmp_path / "poster.jpg"
        poster_file.write_bytes(b"poster-image")
        from py_stremio.api.artwork_cache import CachedArtwork

        monkeypatch.setattr(
            "py_stremio.api.artwork_cache.get_cached_artwork",
            lambda _url: CachedArtwork(poster_file, "image/jpeg"),
        )
        poster_response = client.get(season["poster_url"])
        assert poster_response.status_code == 200
        assert poster_response.content == b"poster-image"

        initial = client.get(f"/api/episodes/{season_id}?kind=season", headers=headers).json()
        assert initial["watched_episodes"] == []

        response = client.put(
            f"/api/episodes/{season_id}/watch",
            headers=headers,
            json={"kind": "season", "episodes": [1, 2], "watched": True},
        )
        assert response.status_code == 200
        watched = client.get(f"/api/episodes/{season_id}?kind=season", headers=headers).json()
        assert watched["watched_episodes"] == [1, 2]

        client.put(
            f"/api/episodes/{season_id}/watch",
            headers=headers,
            json={"kind": "season", "episodes": [1, 2], "watched": False},
        )
        unwatched = client.get(f"/api/episodes/{season_id}?kind=season", headers=headers).json()
        assert unwatched["watched_episodes"] == []

    close_connection()


def _redownload_fixture(tmp_path, monkeypatch):
    root = tmp_path / "media"
    season_folder = root / "series" / "Example Show" / "s01"
    season_folder.mkdir(parents=True)
    media_file = season_folder / "Example.Show.S01E01.mkv"
    media_file.write_bytes(b"old file")
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.ROOT_FOLDER", root)
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "redownload.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "test-token")
    close_connection()
    return root, season_folder, media_file


def test_redownload_replaces_existing_file_only_after_success(tmp_path, monkeypatch):
    _root, _folder, media_file = _redownload_fixture(tmp_path, monkeypatch)
    import py_stremio.components.download.processing as processing

    def successful_download(folder, **kwargs):
        assert kwargs["force_episode"] == 1
        media_file.write_bytes(b"replacement")
        return {"downloaded": 1}

    monkeypatch.setattr(processing, "process_season_folder", successful_download)
    with TestClient(app) as client:
        series_id = get_or_create_series("Example Show", "series/Example Show")
        season_id = get_or_create_season(
            series_id,
            1,
            "series/Example Show/s01",
            {"episode_count": 1, "available_episodes": [1], "enabled": True},
        )
        upsert_files("season", season_id, [{
            "rel_path": media_file.name, "episode": 1, "size": 8, "mtime_ns": 1, "is_part": False,
        }])
        response = client.post(
            f"/api/episodes/{season_id}/redownload",
            headers={"Authorization": "Bearer test-token"},
            json={"kind": "season", "episode": 1},
        )
        assert response.status_code == 202
        assert media_file.read_bytes() == b"replacement"
        assert not list(media_file.parent.glob(".py-stremio-redownload-*.backup"))
        assert fetchone("SELECT status FROM job_runs WHERE job='redownload'")["status"] == "ok"
    close_connection()


def test_failed_redownload_restores_original_file(tmp_path, monkeypatch):
    _root, _folder, media_file = _redownload_fixture(tmp_path, monkeypatch)
    import py_stremio.components.download.processing as processing

    monkeypatch.setattr(
        processing,
        "process_season_folder",
        lambda *_args, **_kwargs: {"downloaded": 0, "failed": 1, "error": "no source"},
    )
    with TestClient(app) as client:
        series_id = get_or_create_series("Example Show", "series/Example Show")
        season_id = get_or_create_season(
            series_id,
            1,
            "series/Example Show/s01",
            {"episode_count": 1, "available_episodes": [1], "enabled": True},
        )
        upsert_files("season", season_id, [{
            "rel_path": media_file.name, "episode": 1, "size": 8, "mtime_ns": 1, "is_part": False,
        }])
        response = client.post(
            f"/api/episodes/{season_id}/redownload",
            headers={"Authorization": "Bearer test-token"},
            json={"kind": "season", "episode": 1},
        )
        assert response.status_code == 202
        assert media_file.read_bytes() == b"old file"
        assert not list(media_file.parent.glob(".py-stremio-redownload-*.backup"))
        assert fetchone("SELECT status FROM job_runs WHERE job='redownload'")["status"] == "failed"
    close_connection()


def test_calendar_refresh_caches_upcoming_cinemeta_events(tmp_path, monkeypatch):
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "calendar.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "test-token")
    close_connection()
    from py_stremio.services import calendar as calendar_service

    init_db()
    series_id = get_or_create_series("Example Show", "series/Example Show", "tt1234567")
    monkeypatch.setattr(calendar_service, "get_series_calendar_episodes", lambda _imdb: [{
        "season": 2,
        "episode": 4,
        "title": "The Return",
        "overview": "A new chapter.",
        "release_at": "2027-02-11T18:00:00+00:00",
        "thumbnail_url": "https://images.example/episode.jpg",
    }])

    result = calendar_service.refresh_calendar(force=True)
    month = calendar_service.get_calendar_month(2027, 2)

    assert result == {"checked": 1, "updated": 1, "failed": 0}
    assert month["events"][0]["series_id"] == series_id
    assert month["events"][0]["episode"] == 4

    with TestClient(app) as client:
        response = client.get(
            "/api/calendar?year=2027&month=2",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        assert response.json()["events"][0]["series_title"] == "Example Show"
    close_connection()


def test_settings_api_persists_preferences_but_never_returns_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "settings.sqlite"))
    monkeypatch.setenv("PY_STREMIO_API_TOKEN", "test-token")
    monkeypatch.setenv("REAL_DEBRID_API_KEY", "")
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.REAL_DEBRID_API_KEY", None)
    close_connection()

    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            headers={"Authorization": "Bearer test-token"},
            json={
                "download_threads": 6,
                "preferred_languages": ["english", "spanish"],
                "real_debrid_api_key": "runtime-only-key",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["download_threads"] == 6
        assert body["preferred_languages"] == ["english", "spanish"]
        assert body["secrets_configured"]["real_debrid"] is True
        assert "runtime-only-key" not in response.text

        stored = client.get("/api/settings", headers={"Authorization": "Bearer test-token"}).json()
        assert stored["internet_speed_limit"] == body["internet_speed_limit"]
        assert "real_debrid_api_key" not in stored

    from py_stremio.services.preferences import load_saved_preferences
    from py_stremio.components.configs.app_settings import settings

    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.DOWNLOAD_THREADS", 2)
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.REAL_DEBRID_API_KEY", None)
    load_saved_preferences()
    assert settings.DOWNLOAD_THREADS == 6
    assert settings.REAL_DEBRID_API_KEY == "runtime-only-key"
    close_connection()
