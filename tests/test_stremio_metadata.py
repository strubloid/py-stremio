"""Tests for Stremio/Cinemeta metadata helpers."""
import gzip

from datetime import datetime, timezone

from py_stremio.components.stremio.stremio_metadata import get_series_metadata


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeTextResponse(FakeResponse):
    def __init__(self, text: str):
        super().__init__({})
        self.text = text


class FakeContentResponse(FakeResponse):
    def __init__(self, content: bytes):
        super().__init__({})
        self.content = content


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

    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.httpx.get", fake_get)

    metadata = get_series_metadata("House of Dragon", 1)

    assert metadata == {
        "imdb_id": "tt11198330",
        "title": "House of the Dragon",
        "episode_count": 2,
        "available_episodes": [1, 2],
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

    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.httpx.get", fake_get)

    metadata = get_series_metadata("Poppas House", 2)

    assert metadata == {
        "imdb_id": "tt26678932",
        "title": "Poppa's House",
        "episode_count": None,
        "available_episodes": [],
        "season_exists": False,
    }


def test_get_imdb_max_season_reads_highest_season_from_imdb_dataset(monkeypatch):
    from py_stremio.components.stremio.stremio_metadata import _load_imdb_max_seasons, get_imdb_max_season

    dataset = "\n".join(
        [
            "tconst\tparentTconst\tseasonNumber\tepisodeNumber",
            "tt0000001\ttt14986406\t1\t1",
            "tt0000002\ttt14986406\t3\t1",
            "tt0000003\ttt14986406\t\\N\t\\N",
            "tt0000004\ttt2861424\t9\t1",
        ]
    )
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata.httpx.get",
        lambda url, timeout: FakeContentResponse(gzip.compress(dataset.encode("utf-8"))),
    )
    _load_imdb_max_seasons.cache_clear()
    get_imdb_max_season.cache_clear()

    assert get_imdb_max_season("tt14986406") == 3


def test_get_current_year_series_seasons_returns_only_seasons_with_current_year_releases(monkeypatch):
    from py_stremio.components.stremio.stremio_metadata import get_current_year_series_seasons

    def fake_get(url, timeout):
        if "/catalog/" in url:
            return FakeResponse({"metas": [{"imdb_id": "tt2861424", "name": "Rick and Morty"}]})
        return FakeResponse(
            {
                "meta": {
                    "imdb_id": "tt2861424",
                    "name": "Rick and Morty",
                    "videos": [
                        {"season": 8, "episode": 1, "released": "2025-05-26T07:00:00.000Z"},
                        {"season": 8, "episode": 10, "released": "2025-07-28T07:00:00.000Z"},
                        {"season": 9, "episode": 1, "released": "2026-05-25T07:00:00.000Z"},
                        {"season": 9, "episode": 10, "released": "2026-07-27T07:00:00.000Z"},
                    ],
                }
            }
        )

    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.httpx.get", fake_get)
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_imdb_max_season", lambda imdb_id: 9)
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata._current_datetime",
        lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    seasons = get_current_year_series_seasons("Rick and Morty", 2026)

    assert seasons == [
        {"imdb_id": "tt2861424", "title": "Rick and Morty", "season": 9, "episode_count": 10, "available_episodes": [1, 10]}
    ]


def test_get_current_year_series_seasons_filters_cinemeta_placeholder_season(monkeypatch):
    from py_stremio.components.stremio.stremio_metadata import get_current_year_series_seasons

    def fake_get(url, timeout):
        if "/catalog/" in url:
            return FakeResponse({"metas": [{"imdb_id": "tt14986406", "name": "Bleach: Thousand-Year Blood War"}]})
        return FakeResponse(
            {
                "meta": {
                    "imdb_id": "tt14986406",
                    "name": "Bleach: Thousand-Year Blood War",
                    "videos": [
                        {
                            "season": 4,
                            "episode": 1,
                            "name": "Episode #4.1",
                            "overview": "",
                            "rating": "0",
                            "released": "2026-01-01T00:00:00.000Z",
                        },
                    ],
                }
            }
        )

    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.httpx.get", fake_get)
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_imdb_max_season", lambda imdb_id: 4)

    seasons = get_current_year_series_seasons("Bleach Thousand-Year Blood War", 2026)

    assert seasons == []


def test_get_current_year_series_seasons_filters_unreleased_tba_season(monkeypatch):
    from py_stremio.components.stremio.stremio_metadata import get_current_year_series_seasons

    def fake_get(url, timeout):
        if "/catalog/" in url:
            return FakeResponse({"metas": [{"imdb_id": "tt11198330", "name": "House of the Dragon"}]})
        return FakeResponse(
            {
                "meta": {
                    "imdb_id": "tt11198330",
                    "name": "House of the Dragon",
                    "videos": [
                        {"season": 3, "episode": 1, "name": "TBA", "overview": "", "rating": "0", "released": "2026-06-22T05:00:00.000Z"},
                        {"season": 3, "episode": 2, "name": "TBA", "overview": "", "rating": "0", "released": "2026-06-29T05:00:00.000Z"},
                    ],
                }
            }
        )

    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.httpx.get", fake_get)
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_imdb_max_season", lambda imdb_id: 3)
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata._current_datetime",
        lambda: datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    seasons = get_current_year_series_seasons("House of the Dragon", 2026)

    assert seasons == []


def test_get_series_metadata_marks_season_missing_when_only_placeholder_episodes_exist(monkeypatch):
    def fake_get(url, timeout):
        if "/catalog/" in url:
            return FakeResponse({"metas": [{"imdb_id": "tt14986406", "name": "Bleach: Thousand-Year Blood War"}]})
        return FakeResponse(
            {
                "meta": {
                    "imdb_id": "tt14986406",
                    "name": "Bleach: Thousand-Year Blood War",
                    "videos": [
                        {"season": 4, "episode": 1, "name": "Episode #4.1", "overview": "", "rating": "0"},
                    ],
                }
            }
        )

    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.httpx.get", fake_get)
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_imdb_max_season", lambda imdb_id: 4)

    metadata = get_series_metadata("Bleach Thousand-Year Blood War", 4)

    assert metadata == {
        "imdb_id": "tt14986406",
        "title": "Bleach: Thousand-Year Blood War",
        "episode_count": None,
        "available_episodes": [],
        "season_exists": False,
    }


def test_get_series_metadata_marks_unreleased_tba_season_missing(monkeypatch):
    def fake_get(url, timeout):
        if "/catalog/" in url:
            return FakeResponse({"metas": [{"imdb_id": "tt11198330", "name": "House of the Dragon"}]})
        return FakeResponse(
            {
                "meta": {
                    "imdb_id": "tt11198330",
                    "name": "House of the Dragon",
                    "videos": [
                        {"season": 3, "episode": 1, "name": "TBA", "overview": "", "rating": "0", "released": "2026-06-22T05:00:00.000Z"},
                        {"season": 3, "episode": 8, "name": "TBA", "overview": "", "rating": "0", "released": "2026-08-10T05:00:00.000Z"},
                    ],
                }
            }
        )

    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.httpx.get", fake_get)
    monkeypatch.setattr("py_stremio.components.stremio.stremio_metadata.get_imdb_max_season", lambda imdb_id: 3)
    monkeypatch.setattr(
        "py_stremio.components.stremio.stremio_metadata._current_datetime",
        lambda: datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    metadata = get_series_metadata("House of the Dragon", 3)

    assert metadata == {
        "imdb_id": "tt11198330",
        "title": "House of the Dragon",
        "episode_count": None,
        "available_episodes": [],
        "season_exists": False,
    }
