# Project Documentation

## Overview

**Py-Stremio** is a terminal-based video download manager that monitors local series/movie folders, detects missing content, and downloads via Stremio addons (Torrentio, MediaFusion, Comet, etc.) with RealDebrid support, concurrent addon search, quality fallback, and bandwidth-aware multi-threaded downloads.

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

## Project Structure

```
py-stremio/
├── pyproject.toml                     # Package config with hatch
├── .env.example                       # Environment template
├── README.md                          # User documentation
├── project.md                         # This file
├── AGENTS.md                          # AI agent context
├── addons.txt                         # Custom addon URLs (optional)
├── py_stremio/                        # Package
│   ├── __init__.py                    # Public exports (Settings, settings)
│   ├── main.py                        # Entry: delegates to components.application
│   └── components/                    # All logic lives here
│       ├── __init__.py
│       ├── application.py             # CLI orchestration, menu, pipeline, progress UI
│       ├── settings.py                # Dataclass-based Settings from .env
│       ├── scanner.py                 # Folder discovery (FolderType.SERIES / MOVIES)
│       ├── config_file.py             # DownloadConfig + QualitySettings dataclasses
│       ├── state.py                   # DownloadState (.download-state.json) management
│       ├── media_files.py             # Video file detection, episode parsing helpers
│       ├── utils.py                   # sanitize_filename, parse_episode_number, parse_season_from_folder
│       ├── output.py                  # Thread-aware stdout filtering for parallel downloads
│       ├── bandwidth.py               # BandwidthLimiter with per-second accounting window
│       ├── download_processing.py     # Core logic: process_season_folder / process_movie_folder
│       ├── download_manager.py        # CLI for legacy config/state-driven download path
│       ├── download_discovery.py      # find_season_folders / find_movie_folders
│       ├── downloader.py              # Legacy Downloader class with quality fallback
│       ├── provider.py                # BaseProvider, RealDebrid, Mock, Fallback providers
│       ├── series.py                  # Legacy series processing (uses old downloader)
│       ├── movies.py                  # Legacy movie processing (uses old downloader)
│       ├── stremio_client.py          # Facade: search_and_download (main download path)
│       ├── stremio_addon_search.py    # Query addons for streams, search_all_addons
│       ├── stremio_metadata.py        # Cinemeta metadata lookups, IMDb season dataset
│       ├── stremio_ids.py             # Build Stremio identifiers from IMDB/title
│       ├── stremio_urls.py            # Normalize / deduplicate manifest URLs
│       ├── stremio_exporter.py        # Export addons from Stremio Desktop storage
│       ├── stream_downloads.py        # Stream URL resolution, HTTP download with resume
│       ├── real_debrid.py             # RealDebrid API: magnet → torrent → direct URL
│       ├── report.py                  # Terminal + email report generation
│       ├── error_logger.py             # Legacy error logger (delegates to ErrorReporter)
│       ├── errors/                     # Error deduplication and reporting system
│       │   ├── __init__.py             # Public API: report_error, print_error_summary
│       │   ├── error_category.py       # ErrorCategory enum + normalize_error() classifier
│       │   ├── error_entry.py          # ErrorEntry dataclass (one deduplicated error)
│       │   ├── error_summary.py        # ErrorSummary dataclass (aggregated output)
│       │   └── error_reporter.py       # ErrorReporter singleton + redact_url helpers
│       ├── addon_validator.py         # Validate addon URLs from addons.txt
│       └── addons/                    # Stremio addon abstractions
│           ├── __init__.py
│           ├── base.py                # BaseAddon, HttpAddon, UrlAddon ABCs
│           ├── addon.py               # Addon URL configuration registry (10 configurers)
│           ├── addon_search_service.py # Concurrent addon stream search (10-at-a-time)
│           ├── addon_validator.py     # Validate addon URLs from addons.txt
│           ├── factory.py             # AddonManager construction (types/ + addons.txt)
│           ├── manager.py             # AddonManager: concurrent search, working URL tracking
│           ├── models.py              # StreamInfo dataclass
│           └── types/                 # One file per addon class, organized by category
│               ├── __init__.py        # Re-exports all classes + configurers
│               ├── addon_url_configurer.py  # Abstract URL configurer base
│               ├── addon_registry.py  # AddonDef dataclass + dynamic class factory
│               ├── builtin_addons.py  # Re-exports all addon classes by category
│               ├── stremio.py         # Generic manifest URL handler (StremioAddonConfigurer)
│               ├── torrentio_family/
│               │   ├── __init__.py
│               │   ├── TorrentioAddon.py
│               │   ├── TorrentioSortSeedersAddon.py
│               │   ├── TorrentioPortugueseAddon.py
│               │   ├── TorrentioSpanishAddon.py
│               │   ├── TorrentioHindiAddon.py
│               │   ├── TorrentioLiteAddon.py
│               │   └── TorrentioAddonConfigurer.py
│               ├── comet_family/
│               │   ├── __init__.py
│               │   ├── CometAddon.py
│               │   ├── CometElfHostedAddon.py
│               │   ├── CometNetAddon.py
│               │   ├── HDHubAddon.py
│               │   ├── StremThruAddon.py
│               │   ├── BrazucaTorrentsAddon.py
│               │   ├── GuindexAddon.py
│               │   ├── CometAddonConfigurer.py
│               │   ├── HDHubAddonConfigurer.py
│               │   ├── StremThruAddonConfigurer.py
│               │   ├── BrazucaAddonConfigurer.py
│               │   ├── GuindexAddonConfigurer.py
│               │   └── _comet_build.py       # Shared URL builder helper
│               ├── aggregators/
│               │   ├── __init__.py
│               │   ├── MediaFusionAddon.py
│               │   ├── KnightCrawlerAddon.py
│               │   ├── EasyNewsPlusAddon.py
│               │   ├── PeerflixAddon.py
│               │   ├── NucleusAddon.py
│               │   ├── OrionAddon.py
│               │   ├── DebridSearchAddon.py
│               │   ├── StremifyAddon.py
│               │   ├── JackettioAddon.py
│               │   ├── AIOStreamsAddon.py
│               │   ├── CineTorrentAddon.py
│               │   ├── TorrinAddon.py
│               │   ├── ThePirateBayPlusAddon.py
│               │   └── IntellDebridSearchAddonConfigurer.py
│               ├── anime/
│               │   ├── __init__.py
│               │   ├── AnimeKitsuAddon.py
│               │   ├── AkumaAddon.py
│               │   ├── AnimepaheAddon.py
│               │   ├── AnimeoAddon.py
│               │   ├── OnePaceAddon.py
│               │   ├── HanimeAddon.py
│               │   ├── AnimesSeasonAddon.py
│               │   ├── NyaaAddonConfigurer.py
│               │   └── YomiAddonConfigurer.py
│               ├── iptv/
│               │   ├── __init__.py
│               │   ├── SkyflixAddon.py
│               │   ├── ArgentinaTVAddon.py
│               │   ├── GreekTVAddon.py
│               │   ├── XtreamProAddon.py
│               │   └── AIOStreamingAddon.py
│               ├── regional/
│               │   ├── __init__.py
│               │   ├── NoTorrentAddon.py
│               │   ├── LatinMoviesAddon.py
│               │   ├── RicosStremioAddon.py
│               │   ├── FTVStremioAddon.py
│               │   ├── FigaroCorsoAddon.py
│               │   ├── EinthusanAddon.py
│               │   ├── VStremioAddon.py
│               │   ├── DubbindoAddon.py
│               │   └── MainelocalnewsAddon.py
│               └── misc/
│                   ├── __init__.py
│                   ├── WatchHubAddon.py
│                   ├── YouTubeProAddon.py
│                   ├── FShareAddon.py
│                   └── ConsumetAddon.py
├── tests/                             # 18 test files, 230+ tests
│   ├── test_addon_validator.py
│   ├── test_application.py
│   ├── test_bandwidth.py
│   ├── test_config_file.py
│   ├── test_download_processing.py
│   ├── test_error_reporting.py
│   ├── test_media_files.py
│   ├── test_menu.py
│   ├── test_movies.py
│   ├── test_progress_ui.py
│   ├── test_quality_fallback.py
│   ├── test_report.py
│   ├── test_scanner.py
│   ├── test_series.py
│   ├── test_state.py
│   ├── test_stremio_client.py
│   ├── test_stremio_metadata.py
│   └── test_stream_downloads.py
└── addons.txt                         # Optional: custom addon URLs
```

## Architecture — Two Processing Paths

The codebase has **two parallel processing paths**:

### 1. Modern Path (primary) — used by `py-stremio` CLI

```
main.py → application.py → download_processing.py
Scanner.scan()
  → update_config_imdb_ids()   # Fetch Cinemeta/IMDb metadata
  → download_folders()         # Process each folder
    → process_season_folder()  # or process_movie_folder()
      → load_config() / load_state()
      → _missing_episodes()    # Determine what needs downloading
      → search_and_download()  # Stremio addon stream search + HTTP download
        → resolve IMDB ID via Cinemeta
        → concurrent search_all_addons_for_streams()  # 10-at-a-time, ~12s for 57 addons
        → select_quality_streams()
        → resolve_stream_download_url()
        → download_stream_to_file()
        → RealDebrid fallback if direct download fails
      → save_state()
```

- Queries Stremio addons concurrently (10 at a time via ThreadPoolExecutor)
- Append-only progress bars with per-episode rate limiting (~1 line/sec/episode)
- Multi-threaded download support with configurable workers and speed %
- Partial download resume via .part files and Range headers
- Working addon URL tracking in config (servers list)

### 2. Legacy Path (maintained)

```
download_manager.py → series.py / movies.py → provider.py
```

- Uses BaseProvider abstraction (RealDebridProvider, MockProvider, FallbackProvider)
- Quality fallback via Downloader.plan_quality_fallback()
- Largely superseded by the modern path but still maintained

## Data Flow (Modern Path — Detailed)

```
Scanner().scan()
  └── series/{show}/s{number}/ → ScannedFolder(type=SERIES)
  └── movies/{group}/           → ScannedFolder(type=MOVIES)

_create_current_year_season_folders()
  └── For each tracked series, checks Cinemeta + IMDb TSV
  └── Creates s{number}/ folders for new-current-year seasons

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
          │
          ├── _missing_episodes()
          │   ├── Filter by current_episode_download
          │   ├── Filter by episode_count
          │   ├── Filter by available_episodes (from metadata)
          │   ├── Check existing files on disk
          │   ├── Check download state
          │   └── Convert tiny/incomplete files to .part for resume
          │
          └── For each missing episode:
              └── search_and_download()
                  ├── resolve IMDB ID (Cinemeta)
                  ├── build_stremio_id()
                  │
                  ├── search_all_addons_for_streams()
                  │   ├── Try known working addons first (from config.servers)
                  │   ├── Otherwise search all configured addons
                  │   │   └── ThreadPoolExecutor(max_workers=10)
                  │   │       one-line spinner: "⠋ Searching addons (X/57)"
                  │   └── Collect working URLs for future use
                  │
                  ├── select_quality_streams()
                  │   └── Sort all streams by quality descending
                  │       2160p=100, 1080p=80, 720p=60, 480p=40,
                  │       360p=20, other=1
                  │       direct URL streams sorted above info_hash-only
                  │       Cap at 20 streams
                  │
                  └── For each selected stream (fall through on failure):
                      ├── resolve_stream_download_url()
                      │   ├── Handle Torrentio RD proxy redirect
                      │   │   └── If redirect → torrentio /videos/* → error page
                      │   │       return None (skip to next stream)
                      │   └── Fallback to info_hash → RealDebrid API
                      │       (may return 451 infringing_file → skip)
                      │
                      └── download_stream_to_file()
                          ├── Check for .part resume
                          ├── Range header for partial resume
                          ├── Bandwidth-limited HTTP streaming
                          ├── Progress callbacks (bytes + rate)
                          ├── Post-download size check:
                          │   < MIN_COMPLETED_VIDEO_SIZE_MB → delete, raise
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

## Key Features

### Concurrent Addon Search

- Instead of querying addons one-at-a-time (which would take 5-14 min for 57 addons),
  all addons are queried concurrently using `ThreadPoolExecutor(max_workers=10)`.
- Each addon has an 8-second timeout (`BaseAddon`) + 10-second HTTP timeout.
- A single rotating spinner shows progress: `"⠋ Searching addons (17/57)"`.
- Verified addon URLs are cached per folder in `config.servers` only after one of that addon's streams completes a real download.
- Addons that only return streams but fail URL resolution or download are not saved; if no missing item downloads, stale cached servers are cleared.
- On subsequent runs, working URLs are queried first for faster results.

### Quality Fallback via Descending Sort

`select_quality_streams()` uses a quality sort key:
- **Quality scores**: 2160p=100, 1080p=80, 720p=60, 480p=40, 360p=20, other=1
- **URL bonus**: streams with a direct `url` get +1 over `info_hash`-only streams at the same quality
- Streams are sorted by `(-qscore, -url_bonus)` — best quality first
- Results are capped at 20 streams
- Each stream is tried in order until a download succeeds or all fail

### Torrentio RD Proxy Error Detection

The top streams often use Torrentio's RealDebrid proxy, which returns redirects
to Torrentio error pages (`failed_infringement_v2.mp4`, `failed_unexpected_v2.mp4`)
when content is DMCA'd or unavailable. The application detects these redirects
by checking if the resolved URL contains `torrentio` + `/videos/` and returns
`None`, allowing fallback to the next stream.

### Minimum File Size Guard

After a download completes, the file size is checked against
`MIN_COMPLETED_VIDEO_SIZE_MB` (default: 100 MB). Files smaller than the threshold
are deleted and a `ValueError` is raised, forcing the next stream to be attempted.
This prevents placeholder/trailer files (e.g. 23 KB from Torz) from being saved
as completed episodes.

### Partial Download Resume

- Data is written to `{filename}.part` during download
- On resume, checks for `.part` file and sends `Range: bytes={existing_size}-`
- If server returns 206 Partial Content, appends to existing file
- On completion, renames `.part` → final filename
- Small incomplete files (under `MIN_COMPLETED_VIDEO_SIZE_MB`) that aren't in
  state are converted back to `.part` for re-download

### Auto-Season Creation

`_create_current_year_season_folders()` in `application.py`:
1. For each series with existing seasons, finds the latest season
2. Checks Cinemeta + IMDb TSV dataset for episodes released in the current year
3. Creates new `s{number}/` folders for seasons that exist in metadata but not on disk
4. Generates default download-config.json for each new season
5. Filters out Cinemeta placeholder seasons and unreleased "TBA" seasons

### Addon URL Validation

`py-stremio --validate` (or menu option 5) tests every URL in `addons.txt`:
- Tests `{base}/manifest.json` for a valid Stremio manifest
- Tests `{base}/stream/series/tt0944947:1:1.json` for stream results
- Runs 10 addons concurrently with 10s timeout each
- Non-working URLs are commented out (`# ` prefix) in `addons.txt`
- One-line spinner shows progress: `"⠙ Testing addons (23/57)"`

### Absolute-Numbered Season Support

`media_files.py` handles series where episodes span seasons with absolute numbering
(e.g., Bleach, One Piece). Each config can have an `episode_count` that crosses
season boundaries, with `current_episode_download` tracking progress within the
absolute numbering scheme.

### Thread-Aware Output

When `DOWNLOAD_THREADS > 1`, the application installs a thread-aware stdout filter
so worker threads don't garble the concurrent progress UI. Progress output is
append-only with per-episode rate limiting (~1 line/sec/episode).

## CLI Commands

```bash
# Interactive menu (no thread prompt — uses config value silently)
py-stremio

# Individual steps (menu or CLI)
py-stremio --scan          # or: py-stremio 1
py-stremio --metadata      # or: py-stremio 2
py-stremio --download      # or: py-stremio 3

# Full pipeline (scan → metadata → download)
py-stremio --run           # Also: py-stremio 4

# Full pipeline with threads and speed %
py-stremio --run 7 100     # 7 threads, 100% bandwidth
py-stremio 4 50            # Menu shortcut 4, 50% speed (threads from settings)

# Validate addons
py-stremio --validate      # or: py-stremio 5

# Cron wrapper (5 threads, 80% speed)
py-stremio-cron 2          # update metadata (for crontab)
py-stremio-cron 3          # download missing (for crontab)

# Legacy paths (superseded by `py-stremio`, kept for reference)```
```

## Addon System

- **52 built-in addon classes** in `components/addons/types/`, organized into category folders:
  - `torrentio_family/` — 6 variants: base, SortSeeders, Portuguese, Spanish, Hindi, Lite
  - `comet_family/` — 7 addons: Comet, CometElfHosted, CometNet, HDHub, StremThru, BrazucaTorrents, Guindex
  - `aggregators/` — 13 scrapers: MediaFusion, KnightCrawler, EasyNews+, ThePirateBay+, Peerflix, Nucleus, Orion, DebridSearch, Stremify, Jackettio, AIOStreams, CineTorrent, Torrin
  - `anime/` — 7 addons: Anime-Kitsu, Akuma, Animepahe, Animeo, OnePace, Hanime, Animes Season
  - `iptv/` — 5 addons: Skyflix, ArgentinaTV, GreekTV, XtreamPro, AIOStreaming
  - `regional/` — 9 addons: NoTorrent, LatinMovies, RicosStremio, FTV Stremio, FigaroCorso, Einthusan, VStremio, Dubbindo, Maine Local News
  - `misc/` — 4 addons: WatchHub, YouTubePro, FShare, Consumet
- **Each class in its own file** named after the class (e.g. `TorrentioAddon.py` → `class TorrentioAddon`)
- **10 URL configurers** (in `addon.py` registry), colocated with their addon families:
  - `TorrentioAddonConfigurer`, `CometAddonConfigurer`, `HDHubAddonConfigurer`, `StremThruAddonConfigurer`, `BrazucaAddonConfigurer`, `GuindexAddonConfigurer`, `StremioAddonConfigurer`, `NyaaAddonConfigurer`, `YomiAddonConfigurer`, `IntellDebridSearchAddonConfigurer`
- **Custom addons**: create `addons.txt` with one URL per line (replaces built-ins when present)
- **Verified URL tracking**: only addon URLs that completed an actual download are saved to `config.servers` per folder; stream-only/non-downloading addons are not persisted
- **Addon Discovery**: `py-stremio --discover` scrapes addon sources, tests URLs, and merges working ones into `addons.txt` (replaces the old `py-stremio-export`)

## Important Files for Changes

| Change | Files |
|--------|-------|
| Add new quality levels | `config_file.py` (QualitySettings), `stream_downloads.py` (select_quality_streams) |
| Change folder structure | `scanner.py`, `download_discovery.py` |
| Add new addon classes | `types/<category>/<ClassName>.py` (class) + `types/addon_registry.py` (AddonDef) + `types/builtin_addons.py` (re-export) |
| Modify addon search | `stremio_addon_search.py`, `addons/manager.py` |
| Change download logic | `download_processing.py`, `stream_downloads.py` |
| Change metadata lookup | `stremio_metadata.py` |
| Modify state format | `state.py` |
| Modify config format | `config_file.py` |
| Modify report format | `report.py` |
| Add new settings | `settings.py` |
| Change episode detection | `media_files.py`, `utils.py` |
| Modify progress UI | `application.py` (_progress_line, _make_progress_printer) |
| Add bandwidth limits | `bandwidth.py` |
| Modify addon validation | `addon_validator.py` |
| Add new error categories | `errors/error_category.py` (ErrorCategory enum, normalize_error) |
| Modify error output format | `errors/error_reporter.py` (print_summary) |
| Change URL redaction rules | `errors/error_reporter.py` (redact_url, _REDACT_PARAMS, _PATH_REDACTIONS) |
| Add new provider | `provider.py` (legacy path only) |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| ROOT_FOLDER | `~/stremio-downloads` | Base folder |
| SERIES_FOLDER | `{ROOT}/series` | Series root |
| MOVIES_FOLDER | `{ROOT}/movies` | Movies root |
| REAL_DEBRID_API_KEY | None | Debrid service key |
| MAX_DOWNLOAD_ATTEMPTS | 5 | Retry limit per quality |
| LIMIT_EPISODES | 0 | Max episodes per run (0=unlimited) |
| MIN_COMPLETED_VIDEO_SIZE_MB | 100 | Min size for valid completed file |
| DOWNLOAD_THREADS | 2 | Parallel download workers |
| METADATA_CACHE_HOURS | 24 | Full-run metadata cache TTL; option 2 / `--metadata` forces refresh |
| INTERNET_SPEED_LIMIT | 100 | Bandwidth % (100 = no limit) |
| INTERNET_MAX_SPEED_MBPS | 100 | Max Mbps for bandwidth calculation |
| DRY_RUN | false | Test mode — no actual downloads |
| STREMIO_ADDON_URL | None | Override addon base URL |
| STREMIO_ADDON_URL_BASE | `https://torrentio.strem.fun` | Addon base URL when no RD key |
| SMTP_HOST | None | Email report SMTP server |
| SMTP_PORT | 587 | SMTP port |
| SMTP_USER | None | SMTP login |
| SMTP_PASSWORD | None | SMTP password |
| SMTP_FROM | None | Email from address |
| SMTP_TO | None | Email to address |
| SMTP_USE_TLS | true | Enable STARTTLS |

## Testing

```bash
# Run all tests (105+ tests across 17 files)
pytest tests/ -v

# Run specific test file
pytest tests/test_download_processing.py -v

# Coverage report
pytest tests/ --cov=py_stremio --cov-report=term-missing
```

### Testing Notes

- Tests use pytest fixtures for temporary directories
- Mock all external HTTP services (httpx mocking)
- State tests handle file I/O with cleanup
- Config tests verify default creation and loading
- Download processing tests mock the Stremio client
- Addon validator tests mock both manifest and stream endpoints
- Stream download tests patch `MIN_COMPLETED_VIDEO_SIZE_MB` to 0 for resume tests
- Progress UI tests verify ANSI escape code rendering and thread-safety
- Metadata tests mock Cinemeta API responses and IMDb TSV dataset

## Folder Detection

- Series folders: `series/{show_name}/s{number}/` (e.g. `series/Breaking Bad/s01/`)
- Movies folders: `movies/{group_name}/`
- Season number extracted from folder name via `utils.parse_season_from_folder()` — matches `s03` or `Season_2`

## Episode Number Detection

Uses regex patterns in `media_files.parse_episode_number()`:
- `S01E12` → 12
- `episode 01.mkv` → 1
- `E05.mkv` → 5
- `- 12` (standalone number) → 12

## Current Status

- Modern Stremio addon-based download path is primary workflow
- Concurrent addon search (10 at a time, ~12s for 57 addons)
- **Preflight optimization**: no_working_addons flag skips per-episode re-scan when preflight finds nothing
- **`py-stremio-cron` wrapper**: 5 threads + 80% speed for crontab
- **No thread prompt**: interactive menu uses config value silently
- RealDebrid integration functional (magnet → torrent → direct URL with polling)
- Torrentio RD proxy error-page detection for DMCA'd/blocked content
- Quality fallback via descending sort (4K → 1080p → 720p → 480p → 360p)
- Minimum file size guard against placeholder/trailer files
- Append-only progress bars with per-episode rate limiting (~1 line/sec/episode)
- Multi-threaded concurrent downloads with thread-aware output
- Partial download resume (.part files + Range headers)
- Working addon URL tracking and caching
- Metadata auto-fetch via Cinemeta + IMDb TSV dataset
- Auto-creation of new season folders for current year
- Absolute-numbered season support (Bleach-style)
- Addon URL validation tool (--validate flag, menu option 5)
- 50 built-in addons + unlimited URL-based addons
- Legacy abstract provider path maintained but secondary
- Email reports via SMTP (optional)

## Error Logging Rule

The project must not print repeated full tracebacks for expected addon failures. Expected external failures such as 404, 400, 403, 429, 500, redirects, timeouts, invalid JSON, DNS failures, and invalid stream size must be grouped through `ErrorReporter`. Full tracebacks should only appear once per unique error type or when debug mode is enabled (`PY_STREMIO_DEBUG=true`). Sensitive tokens in URLs must always be redacted before logging.

### How to report errors

Instead of `print()` or `logging.error()`, use `report_error()`:

```python
from py_stremio.components.errors import report_error

# Include addon name in context as `name(addon_name)`
report_error(context="try_addon(torrentio)", exception=exc, url=addon_url)
report_error(context="invalid_video(Torrentio)", exception=exc, url=stream_url)

# At end of run, the grouped summary is printed automatically
# from application.py — no manual print_error_summary() needed
```

### Error categories

Defined in `ErrorCategory` enum (`errors/error_category.py`):

| Category | Detects |
|----------|---------|
| HTTP_404_NOT_FOUND | httpx.HTTPStatusError with status 404 |
| HTTP_400_BAD_REQUEST | httpx.HTTPStatusError with status 400 |
| HTTP_403_FORBIDDEN | httpx.HTTPStatusError with status 403 |
| HTTP_429_TOO_MANY_REQUESTS | httpx.HTTPStatusError with status 429 |
| HTTP_500_INTERNAL_SERVER_ERROR | httpx.HTTPStatusError with status 500 |
| HTTP_302_REDIRECT | httpx.HTTPStatusError with status 302 |
| CONNECTION_DNS_ERROR | httpx.ConnectError with DNS message |
| READ_TIMEOUT | httpx.TimeoutException |
| JSON_DECODE_ERROR | json.JSONDecodeError |
| INVALID_VIDEO_TOO_SMALL | InvalidVideoDownloadError (from stream_downloads) |
| UNKNOWN_ERROR | Everything else |

### URL redaction

Query params and path segments containing these keys are masked with `***REDACTED***`:
`apikey`, `api_key`, `token`, `realdebrid`, `rd`, `key`, `password`

### Debug mode

Set `PY_STREMIO_DEBUG=true` in your environment or call `ErrorReporter.set_debug(True)` to print full tracebacks for each unique error category.

## Known Limitations

- No anime-style episode naming support (uses Western SxxExx patterns)
- No subtitle download support
- No torrent client integration (uses direct HTTP or RealDebrid)
- RealDebrid poll loop is blocking (5s sleep iterations)
- RealDebrid may return `451 infringing_file` (error_code 35) for DMCA'd content
- No web UI or REST API
- Single-user, single-machine design
- When `addons.txt` exists, built-in addons are not loaded (mutually exclusive)

## todo
check for the file type, maybe with mkv or avi