"""Regression tests for the subfolder warning at scan time.

The downloader intentionally uses a non-recursive
:func:`iter_video_files` to keep the season-folder model simple. When
a user moves an episode into a subfolder, the file is silently
invisible to the downloader. The warning surfaces that situation at
scan time so the user can act.
"""

import os
from pathlib import Path
from unittest.mock import patch

from py_stremio.components.library.library_scanner import FolderType, Scanner
from py_stremio.components.library.media_file import iter_video_files


def test_scanner_warns_about_ignored_subfolders(capsys, tmp_path, monkeypatch):
    series_root = tmp_path / "series"
    season_folder = series_root / "Test Show" / "s01"
    season_folder.mkdir(parents=True)
    (season_folder / "Test Show_s01e01.mkv").write_bytes(b"x")
    (season_folder / "New folder").mkdir()
    (season_folder / "New folder" / "Test Show_s01e02.mkv").write_bytes(b"x")

    monkeypatch.setattr(
        "py_stremio.components.library.library_scanner.settings",
        _Settings(series_root, tmp_path / "movies"),
    )

    Scanner().scan()
    out = capsys.readouterr().out
    assert "subfolder" in out.lower()
    assert "New folder" in out


def test_scanner_silent_for_clean_season_folder(capsys, tmp_path, monkeypatch):
    series_root = tmp_path / "series"
    season_folder = series_root / "Test Show" / "s01"
    season_folder.mkdir(parents=True)
    (season_folder / "Test Show_s01e01.mkv").write_bytes(b"x")
    (season_folder / "Test Show_s01e02.mkv").write_bytes(b"x")

    monkeypatch.setattr(
        "py_stremio.components.library.library_scanner.settings",
        _Settings(series_root, tmp_path / "movies"),
    )

    Scanner().scan()
    out = capsys.readouterr().out
    assert "subfolder" not in out.lower()


def test_iter_video_files_warns_about_subfolders(capsys, tmp_path):
    folder = tmp_path / "Test Show" / "s01"
    folder.mkdir(parents=True)
    (folder / "top_level.mkv").write_bytes(b"x")
    (folder / "nested").mkdir()
    (folder / "nested" / "hidden.mkv").write_bytes(b"x")

    files = iter_video_files(folder)
    out = capsys.readouterr().out
    # Non-recursive — only the top-level file is returned.
    assert [f.name for f in files] == ["top_level.mkv"]
    assert "subfolder" in out.lower()
    assert "nested" in out


def test_iter_video_files_silent_when_no_subfolders(capsys, tmp_path):
    folder = tmp_path / "Test Show" / "s01"
    folder.mkdir(parents=True)
    (folder / "top_level.mkv").write_bytes(b"x")

    iter_video_files(folder)
    out = capsys.readouterr().out
    assert "subfolder" not in out.lower()


def _Settings(series_root: Path, movies_root: Path):
    class _S:
        pass

    s = _S()
    s.ROOT_FOLDER = series_root.parent
    s.SERIES_FOLDER = series_root
    s.MOVIES_FOLDER = movies_root
    return s
