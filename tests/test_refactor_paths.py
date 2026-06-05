"""Regression tests for component-domain module refactor paths."""

from pathlib import Path


def test_builtin_addons_live_under_types_not_addons_root():
    assert not Path("py_stremio/components/addons/builtin.py").exists()
    assert not Path("py_stremio/components/addons/types/builtin.py").exists()

    from py_stremio.components.addons.types.builtin_addons import TorrentioAddon

    assert TorrentioAddon().name == "Torrentio"


def test_download_modules_live_under_download_package():
    assert not Path("py_stremio/components/download_discovery.py").exists()
    assert not Path("py_stremio/components/download_manager.py").exists()
    assert not Path("py_stremio/components/download_processing.py").exists()

    from py_stremio.components.download.discovery import find_movie_folders, find_season_folders
    from py_stremio.components.download.manager import run_downloads
    from py_stremio.components.download.processing import process_movie_folder, process_season_folder

    assert callable(find_movie_folders)
    assert callable(find_season_folders)
    assert callable(run_downloads)
    assert callable(process_movie_folder)
    assert callable(process_season_folder)


def test_flat_component_modules_live_under_domain_packages():
    obsolete_paths = [
        "py_stremio/components/addon_validator.py",
        "py_stremio/components/stremio_addon_search.py",
        "py_stremio/components/stremio_client.py",
        "py_stremio/components/stremio_exporter.py",
        "py_stremio/components/stremio_ids.py",
        "py_stremio/components/stremio_metadata.py",
        "py_stremio/components/stremio_urls.py",
        "py_stremio/components/scanner.py",
        "py_stremio/components/media_files.py",
        "py_stremio/components/movies.py",
        "py_stremio/components/series.py",
        "py_stremio/components/downloader.py",
        "py_stremio/components/bandwidth.py",
        "py_stremio/components/stream_download.py",
        "py_stremio/components/provider.py",
        "py_stremio/components/real_debrid.py",
        "py_stremio/components/config_file.py",
        "py_stremio/components/settings.py",
        "py_stremio/components/state.py",
        "py_stremio/components/output.py",
        "py_stremio/components/report.py",
        "py_stremio/components/error_logger.py",
        "py_stremio/components/utils.py",
    ]

    for obsolete_path in obsolete_paths:
        assert not Path(obsolete_path).exists(), obsolete_path

    from py_stremio.components.addons.addon_search_service import search_all_addons_for_streams
    from py_stremio.components.addons.addon_validator import check_addon_url
    from py_stremio.components.configs.app_settings import settings
    from py_stremio.components.configs.config_file import DownloadConfig
    from py_stremio.components.debrid.real_debrid_client import resolve_torrent_with_debrid
    from py_stremio.components.download.bandwidth_service import build_limiter
    from py_stremio.components.download.downloader import Downloader
    from py_stremio.components.download.provider import BaseProvider
    from py_stremio.components.download.stream_download import InvalidVideoDownloadError
    from py_stremio.components.library.library_scanner import Scanner
    from py_stremio.components.library.media_file import detect_existing_season_episodes
    from py_stremio.components.library.movie import detect_existing_movies
    from py_stremio.components.library.series import detect_existing_episodes
    from py_stremio.components.reports.output_writer import suppress_current_thread_output
    from py_stremio.components.reports.report import ReportData
    from py_stremio.components.state.app_state import DownloadState
    from py_stremio.components.stremio.stremio_client import search_and_download
    from py_stremio.components.stremio.stremio_exporter import export_addons_to_file
    from py_stremio.components.stremio.stremio_ids import build_stremio_id
    from py_stremio.components.stremio.stremio_metadata import get_series_metadata
    from py_stremio.components.stremio.stremio_url import normalize_manifest_url
    from py_stremio.utils.media import parse_episode_number

    assert callable(search_all_addons_for_streams)
    assert callable(check_addon_url)
    assert settings is not None
    assert DownloadConfig is not None
    assert callable(resolve_torrent_with_debrid)
    assert callable(build_limiter)
    assert Downloader is not None
    assert BaseProvider is not None
    assert InvalidVideoDownloadError is not None
    assert Scanner is not None
    assert callable(detect_existing_season_episodes)
    assert callable(detect_existing_movies)
    assert callable(detect_existing_episodes)
    assert callable(suppress_current_thread_output)
    assert ReportData is not None
    assert DownloadState is not None
    assert callable(search_and_download)
    assert callable(export_addons_to_file)
    assert callable(build_stremio_id)
    assert callable(get_series_metadata)
    assert callable(normalize_manifest_url)
    assert parse_episode_number("S01E02.mkv") == 2
