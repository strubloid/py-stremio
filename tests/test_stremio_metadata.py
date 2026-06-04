"""Tests for Stremio/Cinemeta metadata helpers."""

from py_stremio.components.stremio_metadata import get_series_metadata


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_get_series_metadata_returns_imdb_title_and_episode_count(monkeypatch):
    def fake_get(url, timeout):
        if "/catalog/" in url:
            return FakeResponse({"metas": [{"imdb_id": "tt11198330", "name": "House of the Dragon"}]})
        return FakeResponse(
            {
                "meta": {
                    "imdb_id": "tt11198330",
                    "name": "House of the Dragon",
                    "videos": [
                        {"season": 1, "episode": 1},
                        {"season": 1, "episode": 2},
                        {"season": 0, "episode": 1},
                        {"season": 2, "episode": 1},
                    ],
                }
            }
        )

    monkeypatch.setattr("py_stremio.components.stremio_metadata.httpx.get", fake_get)

    metadata = get_series_metadata("House of Dragon", 1)

    assert metadata == {
        "imdb_id": "tt11198330",
        "title": "House of the Dragon",
        "episode_count": 2,
        "season_exists": True,
    }


def test_get_series_metadata_marks_missing_season_when_series_exists_but_season_has_no_episodes(monkeypatch):
    def fake_get(url, timeout):
        if "/catalog/" in url:
            return FakeResponse({"metas": [{"imdb_id": "tt26678932", "name": "Poppa's House"}]})
        return FakeResponse(
            {
                "meta": {
                    "imdb_id": "tt26678932",
                    "name": "Poppa's House",
                    "videos": [
                        {"season": 1, "episode": 1},
                        {"season": 1, "episode": 2},
                    ],
                }
            }
        )

    monkeypatch.setattr("py_stremio.components.stremio_metadata.httpx.get", fake_get)

    metadata = get_series_metadata("Poppas House", 2)

    assert metadata == {
        "imdb_id": "tt26678932",
        "title": "Poppa's House",
        "episode_count": None,
        "season_exists": False,
    }
