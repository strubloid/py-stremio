"""Regression tests for the colon-in-title sanitization fix.

The pre-fix :func:`build_media_filename` interpolated the show title
verbatim into the output filename, which produced e.g.
``Bleach: Thousand-Year Blood War_s04e01.mkv``. That file is
unsupported on Windows / NTFS shares, and the legacy
``library/series.py`` path used a *different* sanitised name, so a
later title edit would silently orphan the file.
"""

from pathlib import Path

import pytest

from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings
from py_stremio.components.download.processing import (
    _generated_episode_filename,
    _is_completed_generated_file,
    _legacy_generated_filename,
    _movie_target_path,
)
from py_stremio.components.download.stream_download import build_media_filename


def test_build_media_filename_sanitises_colon_in_title():
    result = build_media_filename("Bleach: Thousand-Year Blood War", season=4, episode=1)
    assert ":" not in Path(result).name
    assert result.endswith("Bleach_ Thousand-Year Blood War_s04e01.mkv")


def test_build_media_filename_sanitises_other_illegal_chars():
    illegal_chars = '<>:"/\\|?*'
    for char in illegal_chars:
        title = f"Show{char}Name"
        result = build_media_filename(title)
        assert char not in Path(result).name, f"'{char}' was not sanitised from {result!r}"


def test_build_media_filename_passes_through_safe_titles():
    assert build_media_filename("Breaking Bad", season=2, episode=3) == "Breaking Bad_s02e03.mkv"


def test_build_media_filename_handles_empty_title():
    assert build_media_filename("", season=1, episode=1) == "_s01e01.mkv"


def test_generated_episode_filename_matches_build_media_filename():
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        imdb_id="tt14986406",
        season=4,
        episode_count=10,
        quality=QualitySettings(),
    )
    generated = _generated_episode_filename(Path("/tmp/series/Bleach/s04"), config, 4, 1)
    assert generated == "Bleach_ Thousand-Year Blood War_s04e01.mkv"


def test_legacy_generated_filename_uses_unsanitised_title():
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        imdb_id="tt14986406",
        season=4,
        episode_count=10,
        quality=QualitySettings(),
    )
    legacy = _legacy_generated_filename(Path("/tmp/series/Bleach/s04"), config, 4, 1)
    assert legacy == "Bleach: Thousand-Year Blood War_s04e01.mkv"


def test_legacy_generated_filename_returns_none_for_safe_titles():
    config = DownloadConfig(
        type="series",
        title="Breaking Bad",
        imdb_id="tt0903747",
        season=2,
        episode_count=13,
        quality=QualitySettings(),
    )
    legacy = _legacy_generated_filename(Path("/tmp/series/Breaking Bad/s02"), config, 2, 1)
    assert legacy is None


def test_legacy_generated_filename_handles_movies():
    config = DownloadConfig(
        type="movies",
        title="2001: A Space Odyssey",
        imdb_id="tt0062622",
        quality=QualitySettings(),
    )
    legacy = _legacy_generated_filename(Path("/tmp/movies/2001"), config, None, None)
    assert legacy == "2001: A Space Odyssey.mkv"


def test_is_completed_generated_file_recognises_legacy_colon_file(tmp_path):
    """A file written by the pre-fix pipeline (with a colon in the name)
    must still be recognised as 'completed' by the new pipeline so it
    is not re-downloaded.
    """
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        imdb_id="tt14986406",
        season=4,
        episode_count=10,
        quality=QualitySettings(),
    )
    legacy_file = tmp_path / "Bleach: Thousand-Year Blood War_s04e01.mkv"
    legacy_file.write_bytes(b"x" * 1024)

    assert _is_completed_generated_file(tmp_path, config, 4, 1) is True


def test_is_completed_generated_file_recognises_new_sanitised_file(tmp_path):
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        imdb_id="tt14986406",
        season=4,
        episode_count=10,
        quality=QualitySettings(),
    )
    new_file = tmp_path / "Bleach_ Thousand-Year Blood War_s04e01.mkv"
    new_file.write_bytes(b"x" * 1024)

    assert _is_completed_generated_file(tmp_path, config, 4, 1) is True


def test_is_completed_generated_file_returns_false_when_no_file(tmp_path):
    config = DownloadConfig(
        type="series",
        title="Bleach: Thousand-Year Blood War",
        imdb_id="tt14986406",
        season=4,
        episode_count=10,
        quality=QualitySettings(),
    )
    assert _is_completed_generated_file(tmp_path, config, 4, 1) is False


def test_movie_target_path_sanitises_title(tmp_path):
    config = DownloadConfig(
        type="movies",
        title="2001: A Space Odyssey",
        imdb_id="tt0062622",
        quality=QualitySettings(),
    )
    target = _movie_target_path(tmp_path, config)
    assert target == tmp_path / "2001_ A Space Odyssey.mkv"
