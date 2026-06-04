# Project Documentation

## Overview

Py-Stremio is a terminal-based video download manager that monitors local folder structures for missing episodes/movies and downloads them via Stremio addons (Torrentio, MediaFusion, etc.) with RealDebrid support and quality fallback.

## Quick Start

1. Install dependencies:
   ```bash
   pip install -e .
   ```

2. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. Create folder structure:
   ```bash
   mkdir -p ~/stremio-downloads/series
   mkdir -p ~/stremio-downloads/movies
   ```

4. Run the application:
   ```bash
   # Interactive menu
   py-stremio

   # Full pipeline (non-interactive)
   py-stremio --run
   ```

## Architecture

### Two Processing Paths

The codebase has two parallel processing paths. The **modern path** (primary) is the default used by the `py-stremio` CLI.

### Modern Path (Primary)

```
main.py → application.py → download_processing.py
```

1. **Scanner** (`scanner.py`)
   - Recursively scans series (`series/{show}/s{number}/`) and movies (`movies/{group}/`) folders
   - Creates folder structure if missing
   - Identifies folder types via FolderType enum

2. **Metadata** (`stremio_metadata.py`)
   - Fetches IMDB IDs and episode counts from Cinemeta API
   - Validates season existence against IMDb TSV dataset
   - Populates `download-config.json` with metadata (title, imdb_id, episode_count, available_episodes)

3. **Config** (`config_file.py`)
   - Manages `download-config.json` with `DownloadConfig` dataclass
   - Auto-creates default configs for new folders
   - `QualitySettings`: preferred quality, fallbacks, allow_higher, allow_lower
   - Tracks working addon server URLs in `servers` list
   - Auto-repairs stale/malformed configs

4. **State** (`state.py`)
   - Tracks downloaded items in `.download-state.json`
   - Records failed download attempts with timestamps
   - Prevents duplicate downloads and resume attempts

5. **Addon System** (`addons/`)
   - **BaseAddon** ABC with `get_url()` and `get_streams()`
   - **HttpAddon**: reusable implementation for standard Stremio stream endpoints
   - **UrlAddon**: generic wrapper for any addon URL
   - **Built-in addons**: Torrentio, Torrentio-SortSeeders, Torrentio-PT, MediaFusion, Anime-Kitsu, Brazuca-Torrents, ThePirateBay+, HDHub, Comet
   - **Custom addons**: loaded from `addons.txt` if present (replaces built-ins)
   - **Working URL tracking**: successful addon URLs cached in config per folder

6. **Stream Search** (`stremio_addon_search.py`)
   - Queries known working addons first, then remaining configured addons
   - Collects working URLs for future use

7. **Stream Resolution** (`stream_downloads.py`)
   - Resolves stream URLs (handles Torrentio RD proxy redirects)
   - Falls back to RealDebrid direct resolution via info_hash
   - Downloads to disk with resume support (.part files + Range headers)
   - Bandwidth-aware download loop

8. **RealDebrid** (`real_debrid.py`)
   - Adds magnet links via RealDebrid API
   - Selects files, polls for completion
   - Returns direct download URLs

9. **Bandwidth Limiting** (`bandwidth.py`)
   - Per-second accounting window with configurable % of max Mbps
   - Process-wide via thread-safe lock

10. **Download Processing** (`download_processing.py`)
    - Determines missing episodes via `_missing_episodes()`
    - Detects small incomplete files and converts to .part for resume
    - Runs parallel downloads with semaphore-controlled thread pool
    - Emits progress events for real-time UI

11. **Progress UI** (`application.py`)
    - ANSI color-coded progress bars per episode
    - Speed display (bytes/sec)
    - Multi-line concurrent download tracking via ANSI escape codes
    - Thread-aware output filtering so worker threads don't garble the display

12. **Report** (`report.py`)
    - Compact terminal summary after download run
    - Optional SMTP email reports (HTML + plain text)

### Legacy Path (Secondary)

```
download.py → download_manager.py → series.py / movies.py → downloader.py → provider.py
```

- Uses abstract BaseProvider interface (RealDebridProvider, MockProvider, FallbackProvider)
- Quality fallback via `Downloader.download_with_fallback()`
- Largely superseded but maintained for compatibility

## Data Flow (Modern Path)

```
Scanner().scan()
  └── series/{show}/s{number}/ → ScannedFolder(type=SERIES)
  └── movies/{group}/           → ScannedFolder(type=MOVIES)

update_config_imdb_ids()
  └── load_config() / repair_series_season_config()
  └── get_series_metadata() via Cinemeta
  └── infer_next_episode_download()
  └── Write updated download-config.json

download_folders()
  └── For each folder:
      └── process_season_folder() or process_movie_folder()
          ├── load_config() → DownloadConfig
          ├── load_state()  → DownloadState
          ├── _missing_episodes()
          │   ├── Filter by current_episode_download
          │   ├── Filter by episode_count
          │   ├── Filter by available_episodes
          │   ├── Check existing files on disk
          │   ├── Check download state
          │   └── Convert tiny incomplete files to .part
          │
          └── For each missing episode:
              └── search_and_download()
                  ├── resolve IMDB ID (Cinemeta)
                  ├── build_stremio_id()
                  ├── search_all_addons_for_streams()
                  │   ├── Try known working addons first
                  │   └── Search remaining configured addons
                  │
                  ├── select_quality_streams()
                  │   └── Prefer preferred_quality, fallback to first 10
                  │
                  └── For each selected stream:
                      ├── resolve_stream_download_url()
                      │   ├── Handle Torrentio RD proxy redirect
                      │   └── Fallback to info_hash → RealDebrid API
                      │
                      └── download_stream_to_file()
                          ├── Check for .part resume
                          ├── Range header for partial resume
                          ├── Bandwidth-limited HTTP streaming
                          ├── Progress callbacks (bytes + rate)
                          └── Rename .part → final on success

              └── If all streams fail:
                  └── RealDebrid retry (if stream has info_hash)

              └── save_state() on episode success/failure
              └── _remember_working_urls()
```

## Config Files

### download-config.json (per folder)
```json
{
  "type": "series",
  "quality": {
    "preferred": "1080p",
    "fallbacks": ["720p", "480p"],
    "allow_higher": false,
    "allow_lower": true
  },
  "language": "any",
  "subtitles": "any",
  "provider": "auto",
  "enabled": true,
  "title": "Breaking Bad",
  "imdb_id": "tt0903747",
  "season": 1,
  "episode_count": 7,
  "available_episodes": [1, 2, 3, 4, 5, 6, 7],
  "current_episode_download": 5,
  "search_group": "S01",
  "download_all_related": true,
  "working_addons": [],
  "servers": ["https://torrentio.strem.fun"]
}
```

### .download-state.json (per folder)
```json
{
  "items": {
    "Breaking Bad_s01e01.mkv": {
      "filename": "Breaking Bad_s01e01.mkv",
      "quality": "1080p",
      "provider": "stremio",
      "timestamp": "2026-01-15T10:30:00",
      "attempts": 1
    }
  },
  "last_scan": "2026-01-15T10:30:00",
  "total_downloaded": 1,
  "failed_items": {}
}
```

## Auto-Season Creation

On each scan, `_create_current_year_season_folders()` in `application.py`:
1. For each series with existing seasons, finds the latest season
2. Checks Cinemeta + IMDb TSV dataset for episodes released in the current year
3. Creates new `s{number}/` folders for seasons that exist in metadata but not on disk
4. Generates default download-config.json for each new season

## Addon URL Resolution

Working addon URLs are cached per folder in `config.servers`:
- On first run, all configured addons are searched
- Addons that return streams are saved as "working" URLs
- On subsequent runs, working URLs are queried first (faster)
- New addons from config are searched if working URLs don't return streams

## Quality Matching

`select_quality_streams()` in `stream_downloads.py`:
- Filters streams where preferred_quality (e.g. "1080p") appears in the stream name
- Falls back to any stream containing "1080p"
- If no match, returns first 10 streams

## Partial Download Resume

- During download, data goes to `{filename}.part`
- On resume, checks for `.part` file and sends `Range: bytes={existing_size}-`
- If server returns 206 Partial Content, appends to existing file
- On completion, renames `.part` → final filename
- Tiny files (under MIN_COMPLETED_VIDEO_SIZE_MB) are converted back to .part for re-download

## CLI Commands

```bash
# Entry points (from pyproject.toml scripts)
py-stremio           # Interactive menu with scan/metadata/download/exit
py-stremio --run     # Full pipeline non-interactive
py-stremio --scan    # Scan only
py-stremio --metadata # Metadata refresh only
py-stremio --download # Download only
py-stremio 4 3 50   # Pipeline with 3 threads at 50% speed

py-stremio-download  # Legacy config/state-driven path
py-stremio-export    # Export addons from Stremio Desktop
```

## Testing

```bash
pytest tests/ -v
pytest tests/test_download_processing.py -v
pytest tests/ --cov=py_stremio --cov-report=term-missing
```

## Environment Variables

See [Settings Reference in AGENTS.md](./AGENTS.md#settings-reference) for full list.

## Known Limitations

- No anime-style episode naming support (uses Western SxxExx patterns)
- No subtitle download support
- No torrent client integration (direct HTTP or RealDebrid only)
- No web UI or REST API
- Single-user, single-machine design
- Addon search is sequential (not parallel)
- RealDebrid poll loop is blocking (5s sleep iterations)
