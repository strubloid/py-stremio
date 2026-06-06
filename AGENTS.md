# AGENTS.md - Context for Future AI Agents

## Project Overview

**py-stremio** is a terminal-based video download manager that monitors local series/movie folders, detects missing content, and downloads via Stremio addons (Torrentio, MediaFusion, etc.) with RealDebrid support and quality fallback.

## Key Technologies

- Python 3.10+
- python-dotenv for settings
- httpx for HTTP requests
- pytest for testing

## Project Structure

```
py-stremio/
├── pyproject.toml                     # Package config with hatch
├── .env.example                       # Environment template
├── README.md                          # User documentation
├── project.md                         # Technical documentation
├── AGENTS.md                          # This file - agent context
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
│       ├── error_logger.py             # Legacy error logger, now delegates to ErrorReporter
│       ├── errors/                     # Error deduplication and reporting system
│       │   ├── __init__.py             # Public API: report_error, print_error_summary
│       │   ├── error_category.py       # ErrorCategory enum + normalize_error() classifier
│       │   ├── error_entry.py          # ErrorEntry dataclass (one deduplicated error)
│       │   ├── error_summary.py        # ErrorSummary dataclass (aggregated output)
│       │   └── error_reporter.py       # ErrorReporter singleton + redact_url helpers
│       └── addons/                    # Stremio addon abstractions
│           ├── __init__.py
│           ├── base.py                # BaseAddon, HttpAddon, UrlAddon ABCs
│           ├── addon.py               # Addon URL configuration registry (10 configurers)
│           ├── addon_search_service.py # Concurrent addon stream search
│           ├── addon_validator.py     # Validate addon URLs from addons.txt
│           ├── factory.py             # AddonManager construction (types/ + addons.txt)
│           ├── manager.py             # AddonManager: search addons for streams
│           ├── models.py              # StreamInfo dataclass
│           └── types/                 # One file per addon class, organized by category
│               ├── __init__.py        # Re-exports all classes + configurers
│               ├── addon_url_configurer.py  # Abstract URL configurer base
│               ├── addon_registry.py  # AddonDef dataclass + dynamic class factory
│               ├── builtin_addons.py  # Re-exports all addon classes by category
│               ├── stremio.py         # Generic manifest URL handler
│               ├── torrentio_family/   # 6 Torrentio variants + configurer
│               ├── comet_family/       # 7 addons + 6 configurers + _comet_build.py
│               ├── aggregators/        # 13 scrapers + configurer
│               ├── anime/             # 7 anime addons + 2 configurers
│               ├── iptv/              # 5 IPTV addons
│               ├── regional/          # 9 regional addons
│               └── misc/              # 4 miscellaneous addons
└── tests/
    ├── test_application.py
    ├── test_bandwidth.py
    ├── test_config_file.py
    ├── test_download_processing.py
    ├── test_media_files.py
    ├── test_menu.py
    ├── test_movies.py
    ├── test_progress_ui.py
    ├── test_quality_fallback.py
    ├── test_report.py
    ├── test_scanner.py
    ├── test_series.py
    ├── test_state.py
    ├── test_stremio_client.py
    ├── test_stremio_metadata.py
    └── test_stream_downloads.py
```

## Architecture — Two Processing Paths

The codebase has **two parallel processing paths**:

### 1. Modern Path (primary) — used by `py-stremio` CLI
`main.py` → `application.py` → `download_processing.py`

```
Scanner.scan()
  → update_config_imdb_ids()   # Fetch Cinemeta/IMDb metadata
  → download_folders()         # Process each folder
    → process_season_folder()  # or process_movie_folder()
      → load_config() / load_state()
      → _missing_episodes()    # Determine what needs downloading
      → search_and_download()  # Stremio addon stream search + HTTP download
        → resolve IMDB ID via Cinemeta
        → search_all_addons_for_streams()
        → select_quality_streams()
        → resolve_stream_download_url()
        → download_stream_to_file()
        → RealDebrid fallback if direct download fails
      → save_state()
```

- Queries Stremio addons directly (Torrentio, MediaFusion, ThePirateBay+, etc.)
- Per-episode progress bars with bandwidth limiting and speed display
- Multi-threaded download support (DOWNLOAD_THREADS)
- Partial download resume via .part files and Range headers
- Verified addon URL tracking in config (servers list): only addons whose stream actually completed a download are persisted

### 2. Legacy Path (maintained)
`download_manager.py` → `series.py` / `movies.py` → `provider.py`

- Uses BaseProvider abstraction (RealDebridProvider, MockProvider, FallbackProvider)
- Quality fallback via Downloader.plan_quality_fallback()
- Largely superseded by the modern path but still maintained

## Important Patterns

### Config vs State Files

- **download-config.json**: User preferences + metadata (quality, title, imdb_id, episode_count, servers, enabled, current_episode_download, available_episodes)
- **.download-state.json**: App tracking (filenames downloaded, failed attempts)

### Folder Detection

- Series folders: `series/{show_name}/s{number}/` (e.g. `series/Breaking Bad/s01/`)
- Movies folders: `movies/{group_name}/`
- Season number extracted from folder name via `utils.parse_season_from_folder()` — matches `s03` or `Season_2`

### Episode Number Detection

Uses regex patterns in `utils.parse_episode_number()`:
- `S01E12` → 12
- `episode 01.mkv` → 1
- `E05.mkv` → 5
- `- 12` (standalone number) → 12

### Auto-Season Creation

`_create_current_year_season_folders()` in `application.py`:
- Scans series with existing seasons
- Checks Cinemeta + IMDb TSV dataset for current-year episodes
- Creates season folders for new years automatically

### Quality Fallback Order

1. Preferred quality from config (default: 1080p)
2. Fallback qualities in list order (default: 720p, 480p)
3. Skip if MAX_DOWNLOAD_ATTEMPTS reached

### Addon Server Cache Rule

`download-config.json` `servers` is a verified per-folder cache, not a generic "returned streams" list. A URL may be queried from this cache first, but it may only be saved back into `servers` after one of its streams successfully downloads an episode/movie for that folder. If a missing item is attempted and no download succeeds, clear stale `servers` for that folder instead of keeping previously cached URLs. Do not persist addons merely because they returned stream metadata, because those links may still fail during URL resolution or video download.

### Addon Discovery Order

```
1. Known working addon URLs from config.servers
2. Built-in addons (52 classes in types/, organized by category — Torrentio, Comet, MediaFusion, etc. + Torrentio-PT if RD key present)
3. Custom addons from addons.txt (if file exists)
```

### Provider Selection (Legacy Path Only)

```
IF REAL_DEBRID_API_KEY exists AND valid
  → Use RealDebridProvider
ELIF DRY_RUN=true
  → Use MockProvider
ELSE
  → Use FallbackProvider (no-op)
```

### RealDebrid Integration

- Stream URL proxy resolution via Torrentio RD proxy redirects
- Direct info_hash → magnet → torrent → download URL via RealDebrid API
- Retry fallback: if direct addon download fails and stream has info_hash, retry via RD

## Settings Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| ROOT_FOLDER | `~/stremio-downloads` | Base folder |
| SERIES_FOLDER | `{ROOT}/series` | Series root |
| MOVIES_FOLDER | `{ROOT}/movies` | Movies root |
| REAL_DEBRID_API_KEY | None | Debrid service key |
| MAX_DOWNLOAD_ATTEMPTS | 5 | Retry limit per quality |
| LIMIT_EPISODES | 0 | Max episodes per run (0=unlimited) |
| MIN_COMPLETED_VIDEO_SIZE_MB | 100 | Min size for valid completed file |
| DOWNLOAD_THREADS | 1 | Parallel download workers |
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

## CLI Usage

```bash
# Install
pip install -e .

# Interactive menu
py-stremio

# Full pipeline (non-interactive)
py-stremio --run
py-stremio 4

# Individual steps
py-stremio --scan        # or: py-stremio 1
py-stremio --metadata    # or: py-stremio 2
py-stremio --download    # or: py-stremio 3

# With thread count and speed limit
py-stremio --run 4 50   # 4 threads, 50% speed

# Legacy paths (superseded by `py-stremio`, kept for reference)

# Test
pytest tests/ -v

# Coverage
pytest tests/ --cov=py_stremio --cov-report=term-missing
```

## Addon System

- **52 built-in addon classes** in `components/addons/types/`, each class in its own file organized by category folder:
  - `torrentio_family/` (6 variants: Torrentio, SortSeeders, Portuguese, Spanish, Hindi, Lite)
  - `comet_family/` (7: Comet, CometElfHosted, CometNet, HDHub, StremThru, BrazucaTorrents, Guindex)
  - `aggregators/` (13: MediaFusion, KnightCrawler, EasyNews+, ThePirateBay+, Peerflix, Nucleus, etc.)
  - `anime/` (7: Anime-Kitsu, Akuma, Animepahe, Animeo, OnePace, Hanime, Animes Season)
  - `iptv/` (5: Skyflix, ArgentinaTV, GreekTV, XtreamPro, AIOStreaming)
  - `regional/` (9: NoTorrent, LatinMovies, RicosStremio, FTV, FigaroCorso, Einthusan, etc.)
  - `misc/` (4: WatchHub, YouTubePro, FShare, Consumet)
- **10 URL configurers** colocated with their addon families (in `addon.py` registry)
- **Verified URL tracking**: only addon URLs that completed an actual download are saved to `config.servers` per folder; stream-only/non-downloading addons are not persisted
- **Custom addons**: create `addons.txt` in project root with one URL per line (URLs replace built-ins entirely)
- **Addon Discovery**: `py-stremio --discover` scrapes addon sources, tests URLs, and merges working ones into `addons.txt` (replaces the old `py-stremio-export`)

## Important Files for Changes

| Change | Files |
|--------|-------|
| Add new quality levels | `config_file.py` (QualitySettings), `stream_downloads.py` (select_quality_streams) |
| Change folder structure | `scanner.py`, `download_discovery.py` |
| Add new addons | `types/<category>/<ClassName>.py` (class) + `types/addon_registry.py` (AddonDef) + `types/builtin_addons.py` (re-export) |
| Modify addon search | `stremio_addon_search.py`, `addons/manager.py` |
| Change download logic | `download_processing.py`, `stream_downloads.py` |
| Change metadata lookup | `stremio_metadata.py` |
| Modify state format | `state.py` |
| Modify config format | `config_file.py` |
| Modify report format | `report.py` |
| Add new settings | `settings.py` |
| Change episode detection | `utils.py` |
| Add new error categories | `errors/error_category.py` (ErrorCategory enum, normalize_error) |
| Modify error output format | `errors/error_reporter.py` (print_summary) |
| Change URL redaction rules | `errors/error_reporter.py` (redact_url, _REDACT_PARAMS, _PATH_REDACTIONS) |
| Add new provider | `provider.py` (legacy path) |
| Modify progress UI | `application.py` (_progress_line, _make_progress_printer) |
| Add bandwidth limits | `bandwidth.py` |

## Testing Notes

- Tests use pytest fixtures for temporary directories
- Mock all external HTTP services in tests (httpx mocking)
- State tests handle file I/O with cleanup
- Config tests verify default creation and loading
- Download processing tests mock the Stremio client

## Current Status

- Modern Stremio addon-based download path is primary workflow
- RealDebrid integration functional (magnet → torrent → direct URL with polling)
- Per-episode progress bars with speed display and bandwidth limiting
- Multi-threaded concurrent downloads
- Partial download resume (.part files + Range headers)
- Working addon URL tracking and caching
- Metadata auto-fetch via Cinemeta + IMDb TSV dataset
- Auto-creation of new season folders for current year
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

Example:
```
https://torrentio.strem.fun/realdebrid=abc123
→ realdebrid=***REDACTED***

https://torrentio.strem.fun/resolve/realdebrid/abc123/stream.mkv
→ /realdebrid/***REDACTED***/stream.mkv
```

### Debug mode

Set `PY_STREMIO_DEBUG=true` in your environment or call `ErrorReporter.set_debug(True)` to print full tracebacks for each unique error category.

### Known Limitations

- No anime-style episode naming support
- No subtitle download support
- No torrent client integration (uses direct HTTP or RealDebrid)
- No web UI or API
- Single-user, single-machine design
