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
├── docs/project.md                         # Technical documentation
├── AGENTS.md                          # This file - agent context
├── addons/                            # Addon inventories
│   ├── addons.txt                     # Local/discovered URLs (gitignored)
│   ├── addons.txt.example             # Custom inventory template
│   ├── stremio.txt                    # Tracked baseline manifests
│   └── experimental.txt               # Option 7 output (gitignored)
├── py_stremio/                        # Package root
│   ├── __init__.py                    # Public exports
│   ├── main.py                        # CLI entry point
│   ├── app.py                         # AppService — single orchestrator (run, run_menu, run_pipeline)
│   ├── services/                      # High-level orchestration services
│   │   ├── __init__.py
│   │   ├── scanner.py                 # ScanService — folder scanning + auto-create seasons
│   │   ├── metadata.py                # MetadataService — Cinemeta/IMDb enrichment
│   │   ├── download.py                # DownloadService — download orchestration + reporting
│   │   └── progress.py                # ProgressRenderer — progress bars, colors, terminal
│   ├── utils/                         # Shared utilities
│   │   ├── __init__.py
│   │   ├── media.py                   # sanitize_filename, parse_episode_number, parse_season_from_folder
│   │   ├── atomic_write.py            # Atomic file write operations
│   │   └── cancellation.py            # Graceful shutdown handling
│   └── components/                    # Domain-specific components
│       ├── __init__.py
│       ├── application.py             # Compat shim (backward compat for tests)
│       ├── configs/                   # Configuration management
│       │   ├── __init__.py
│       │   ├── app_settings.py        # Settings dataclass from .env
│       │   └── config_file.py         # DownloadConfig + QualitySettings
│       ├── state/                     # State persistence
│       │   ├── __init__.py
│       │   └── app_state.py           # DownloadState (.download-state.json) management
│       ├── library/                   # Media library scanning
│       │   ├── __init__.py
│       │   ├── library_scanner.py     # Scanner, FolderType, ScannedFolder
│       │   ├── media_file.py          # Video file detection, episode parsing
│       │   ├── series.py              # Legacy series processing
│       │   └── movie.py               # Legacy movie processing
│       ├── stremio/                   # Stremio API integration
│       │   ├── __init__.py
│       │   ├── stremio_client.py      # Facade: search_and_download
│       │   ├── stremio_metadata.py    # Cinemeta metadata + IMDb season dataset
│       │   ├── stremio_ids.py         # Build Stremio identifiers from IMDB/title
│       │   └── stremio_url.py         # Normalize / deduplicate manifest URLs
│       ├── download/                  # Download execution
│       │   ├── __init__.py
│       │   ├── processing.py          # Core logic: process_season_folder / process_movie_folder
│       │   ├── stream_download.py     # Stream URL resolution, HTTP download with resume
│       │   ├── bandwidth_service.py   # BandwidthLimiter + FairBandwidthLimiter fair-share accounting
│       │   ├── speed_probe.py         # Auto-detect/persist INTERNET_MAX_SPEED_MBPS when missing
│       │   ├── discovery.py           # find_season_folders / find_movie_folders
│       │   ├── downloader.py          # Legacy Downloader class with quality fallback
│       │   └── provider.py            # BaseProvider, RealDebrid, Mock, Fallback providers
│       ├── debrid/                    # Debrid service integration
│       │   ├── __init__.py
│       │   └── real_debrid_client.py  # RealDebrid API: magnet → torrent → direct URL
│       ├── addons/                    # Stremio addon abstractions
│       │   ├── __init__.py
│       │   ├── base.py                # BaseAddon, HttpAddon, UrlAddon ABCs
│       │   ├── addon.py               # Addon URL configuration registry (11 configurers)
│       │   ├── addon_search_service.py # Concurrent addon stream search (preflight scan)
│       │   ├── addon_validator.py     # Validate URLs from addons/addons.txt
│       │   ├── factory.py             # AddonManager construction (types/ + addon files)
│       │   ├── manager.py             # AddonManager: search addons for streams
│       │   ├── models.py              # StreamInfo dataclass
│       │   └── types/                 # 64 addon classes, organized by category
│       │       ├── __init__.py
│       │       ├── addon_url_configurer.py  # Abstract URL configurer base
│       │       ├── addon_registry.py  # AddonDef dataclass + dynamic class factory
│       │       ├── builtin_addons.py  # Re-exports all addon classes by category
│       │       ├── stremio.py         # Generic manifest URL handler (StremioAddonConfigurer)
│       │       ├── torrentio_family/  # 7 Torrentio variants + configurer
│       │       ├── comet_family/      # 7 addons + 6 configurers + _comet_build.py
│       │       ├── aggregators/       # 19 scrapers + configurer
│       │       ├── anime/             # 10 anime addons + 2 configurers
│       │       ├── iptv/              # 6 IPTV addons
│       │       ├── regional/          # 11 regional addons
│       │       └── misc/              # 4 miscellaneous addons
│       ├── collect/                   # Addon discovery/collection
│       │   ├── __init__.py
│       │   ├── discovery.py           # Main addon discovery orchestrator
│       │   ├── sources.py             # Addon source scrapers
│       │   ├── tester.py              # URL validation and testing
│       │   └── merger.py              # Merge discovered addons with addons/addons.txt
│       ├── reports/                   # Reporting
│       │   ├── __init__.py
│       │   ├── report.py              # Terminal + email report generation
│       │   └── output_writer.py       # Thread-aware stdout filtering
│       └── errors/                    # Error deduplication and reporting
│           ├── __init__.py            # Public API: report_error, print_error_summary
│           ├── error_category.py      # ErrorCategory enum + normalize_error() classifier
│           ├── error_entry.py         # ErrorEntry dataclass (one deduplicated error)
│           ├── error_summary.py       # ErrorSummary dataclass (aggregated output)
│           ├── error_reporter.py      # ErrorReporter singleton + redact_url helpers
│           └── error_logger.py        # Legacy error logger (backward compat)
└── tests/                             # 32 test files, 451 tests (10 live-network checks)
    ├── test_addon_enabled.py
    ├── test_addon_type_configurers.py
    ├── test_addon_validator.py
    ├── test_addons_stremio_file.py
    ├── test_application.py
    ├── test_atomic_persistence.py
    ├── test_bandwidth.py
    ├── test_collect_sources.py
    ├── test_config_file.py
    ├── test_download_processing.py
    ├── test_error_reporting.py
    ├── test_media_files.py
    ├── test_menu.py
    ├── test_movies.py
    ├── test_new_addons.py
    ├── test_progress_ui.py
    ├── test_quality_fallback.py
    ├── test_refactor_paths.py
    ├── test_report.py
    ├── test_root_addons_stremio.py
    ├── test_scanner.py
    ├── test_series.py
    ├── test_state.py
    ├── test_stream_downloads.py
    ├── test_stremio_client.py
    ├── test_stremio_metadata.py
    └── test_stremio_urls.py
```

## Architecture — Two Processing Paths

The codebase has **two parallel processing paths**:

### 1. Modern Path (primary) — used by `py-stremio` CLI
`main.py` → `app.py` (AppService) → `services/` → `components/`

```
AppService.run_pipeline()
  → ScanService.run()
    → Scanner.scan()          # library/library_scanner.py
    → auto-create current-year season folders
  → MetadataService.run()
    → update_config_imdb_ids() # stremio/stremio_metadata.py
    → repair_series_season_config()
    → infer_next_episode_download()
    → resolve movie title/IMDb ID/languages for each movies/{title}/ folder
  → DownloadService.run()
    → download_folders()       # download/processing.py
      → process_season_folder() / process_movie_folder()
        → load_config() / load_state()
        → _missing_episodes()
        → preflight_discover_working_addons() # addons/addon_search_service.py
        → no_working_addons flag set if preflight finds nothing
        → skip_full_search=True → episodes skip re-scanning all 54 addons
        → search_and_download(skip_full_search=task.no_working_addons) # stremio/stremio_client.py
          → resolve IMDB ID via Cinemeta
          → search_all_addons_for_streams()
          → select_quality_streams()
          → resolve_stream_download_url()
          → download_stream_to_file() # download/stream_download.py
          → RealDebrid fallback if direct download fails
        → save_state()
        → _remember_working_urls()
```

- Queries Stremio addons directly (Torrentio, MediaFusion, ThePirateBay+, etc.)
- Append-only progress bars emit only the changed episode line in non-TTY output (stable numbering/no repeated full blocks) with per-episode rate limiting (~1 line/sec/episode); non-download/search stages render `waiting for download`, and tiny invalid/error responses under 1 MB render `sizing` instead of fake byte percentages
- Multi-threaded download support (DOWNLOAD_THREADS, default: 2) with FairBandwidthLimiter per-active-download bandwidth sharing and dynamic redistribution when actual stream downloads start/finish; search/probe workers are not counted against the bandwidth share
- **Interactive bottom controls bar** (rich TUI only, no-op on pipes/cron) — single-key controls rendered below the existing footer: `[B]` toggles 4K filter (session-only, propagates to all live folder configs in memory), `[+]`/`[-]` adjusts the worker count (1..16, clamped), `[[]`/`]]` adjusts the speed percent in 5-point steps (1..100, clamped), `[Q]` requests cooperative shutdown. The keyboard reader is implemented in `services/controls.py` (cross-platform: `termios.tty.setcbreak` on Unix, `msvcrt.kbhit`/`getwch` on Windows) and is automatically suppressed when stdin/stdout is not a tty. Toggling 4K does NOT persist to `download-config.json` — the on-disk config is read once at startup and never written by the toggle. The worker count and speed percent also live in `RichDownloadUI.workers_ref` / `RichDownloadUI.speed_ref`; `process_season_folder` re-reads `workers_ref[0]` before every retry round so the `[+/-]` dial takes effect on the next round, and the parallel branch breaks out to the single-worker loop when the user dials down to 1. In-flight downloads finish naturally — a running thread is never aborted by a worker-count change.
- **`py-stremio-cron` console entry point** — uses the same `AppService` path as `py-stremio` with cron preset defaults: 5 threads + 80% speed
- **Interactive prompt split** — normal `py-stremio` menu actions that download ask for thread count and speed; `py-stremio-cron` uses preset defaults (5 threads, 80% speed) without prompts
- Movie partial-download safety: when a movie source ignores its Range request, preserve the existing `.part` unchanged and try another source rather than silently restarting from zero. The same policy now applies to series as well: every failure path in `download_stream_to_file` (httpx.ReadTimeout, invalid content-type, content-length mismatch, too-small response, post-rename size check) leaves the existing `.part` on disk so the next attempt can resume from where the user left off. `_delete_invalid_download` now only removes the final file. Callers that want a clean restart from zero must unlink the `.part` explicitly.
- Per-episode final-file existence guard: download workers skip instead of re-downloading if the expected output file already exists, even if a stale task listed it as missing
- Verified addon URL tracking in config (servers list): only addons whose stream actually completed a download are persisted
- Addon advisory/config/browser-only rows (for example Reddit notices, `configure this addon`, `externalUrl` only) are filtered before download attempts; if every returned stream is filtered out, the item reports `No downloadable streams found after filtering` and is not retried repeatedly in the same run

### 2. Legacy Path (maintained)
`download_manager.py` → `library/series.py` / `library/movies.py` → `download/provider.py`

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
- Each direct child of `movies/` is exactly one movie request, not a multi-title group. Movie
  processing uses `content_type="movie"`, `season=None`, and `episode=None`.
- Season number extracted from folder name via `utils.parse_season_from_folder()` — matches `s03` or `Season_2`

### Movie Metadata and Languages

- `MetadataService._update_movie_metadata()` resolves a movie folder title through Cinemeta's
  movie catalog and persists its canonical title and IMDb ID. A supplied `imdb_id` takes
  precedence over a title match; use it when a folder name is ambiguous.
- Movie languages are read from IMDb title markup when available. New movie configs do **not**
  inherit `PREFERRED_LANGUAGES`; that global setting initializes newly created series-season
  configs only. If IMDb language data cannot be read, keep the movie language-neutral instead
  of inventing a default.
- Movies keep `season=None`, `episode_count=None`, and `current_episode_download=0`. Do not
  reuse series episode metadata or season parsing for a movie folder.

### Episode Number Detection

Uses regex patterns in `utils.parse_episode_number()`:
- `S01E12` → 12
- `episode 01.mkv` → 1
- `E05.mkv` → 5
- `- 12` (standalone number) → 12

### Auto-Season Creation

`_create_current_year_season_folders()` in `services/scanner.py`:
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
1. Preflight scan: when config.servers is empty and IMDB ID exists, run preflight_discover_working_addons()
   - Queries ALL addons concurrently (10 at a time)
   - Uses responders for the current attempt only; cache them only after a successful completed download
2. Known working addon URLs from config.servers (per-folder verified cache)
3. Built-in addons (64 classes in types/, organized by category — Torrentio, Comet, MediaFusion, etc.)
4. Baseline/custom addons from `addons/stremio.txt` and `addons/addons.txt`
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
- Optional local torrent proxy resolution via `TORRENT_PROXY_URL`, preserving Stremio `sources` as repeated `tr=` tracker/DHT query params
- Direct info_hash → magnet → torrent → download URL via RealDebrid API, mapping Stremio zero-based `fileIdx` to RealDebrid file IDs before `selectFiles`; uncached RD polling is capped to a short 6-attempt window so episodes do not sit on `waiting for download` for minutes per stream
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
| DOWNLOAD_THREADS | 2 | Parallel download workers |
| PREFERRED_LANGUAGES | `english` | Default only for new series-season configs; movie metadata sets movie languages |
| INTERNET_SPEED_LIMIT | 100 | Bandwidth % (100 = no limit) |
| INTERNET_MAX_SPEED_MBPS | auto-detected once; fallback 100 | Max Mbps for bandwidth calculation; if missing from env/.env, a short speed probe appends the measured value to .env |
| DRY_RUN | false | Test mode — no actual downloads |
| STREMIO_ADDON_URL | None | Override addon base URL |
| STREMIO_ADDON_URL_BASE | `https://torrentio.strem.fun` | Addon base URL when no RD key |
| TORRENT_PROXY_URL | None | Optional local Stremio-compatible torrent proxy for info-hash streams; tracker/DHT sources are passed as `tr=` params |
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

# Interactive menu (download actions ask for threads and speed)
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

# Cron console entry point (same AppService path; preset 5 threads, 80% speed, no interactive prompts)
py-stremio-cron 3       # update metadata (for crontab)
py-stremio-cron 4       # download missing (for crontab)
py-stremio-cron 2       # update metadata + download (combined)

# Cron setup (crontab -e)
# PATH=/home/strubloid/apps/py-stremio/venv/bin:/usr/local/bin:/usr/bin:/bin
# 0 */3 * * * cd /home/strubloid/apps/py-stremio && py-stremio-cron 3
# 0 */2 * * * cd /home/strubloid/apps/py-stremio && py-stremio-cron 4

# Legacy paths (superseded by `py-stremio`, kept for reference)

# Test
pytest tests/ -v

# Coverage
pytest tests/ --cov=py_stremio --cov-report=term-missing
```

## Addon System

### Built-in Addons

**64 built-in addon classes** in `components/addons/types/`, each class in its own file organized by category folder:
  - `torrentio_family/` (7 variants: Torrentio, SortSeeders, Portuguese, Spanish, Hindi, Lite, TorrentsDB)
  - `comet_family/` (7: Comet, CometElfHosted, CometNet, HDHub, StremThru, BrazucaTorrents, Guindex)
  - `aggregators/` (19: MediaFusion, KnightCrawler, EasyNews+, ThePirateBay+, Peerflix, Nucleus, Orion, DebridSearch, Stremify, Jackettio, AIOStreams, CineTorrent, Torrin, FlixStreams, MyCine, NebulaStreams, StreamViX, VidFastPro, Ytztvio)
  - `anime/` (10: Anime-Kitsu, Akuma, Animepahe, Animeo, OnePace, Hanime, Animes Season, AnimeStream, HiAnimeStreams, YaStream)
  - `iptv/` (6: Skyflix, ArgentinaTV, GreekTV, XtreamPro, AIOStreaming, Watchio)
  - `regional/` (11: NoTorrent, LatinMovies, RicosStremio, FTV, FigaroCorso, Einthusan, VStremio, Dubbindo, MaineLocalNews, FenixFlix, MicoLeaoDublado)
  - `misc/` (4: WatchHub, YouTubePro, FShare, Consumet)

### Addon Loading Behavior (addon files + Built-ins)

When `create_addon_manager()` is called (via `factory.py`):
1. **Always loads all built-in addons first** — these have correct RealDebrid key injection in their `get_url()` methods
2. **Supplements with addon files** — loads tracked `addons/stremio.txt`, then local `addons/addons.txt`
3. **Deduplicates by hostname** — file URLs whose hostname matches a built-in addon are skipped (reported as "covered by built-in")
4. **Wraps file URLs as `UrlAddon`** — URLs from file become generic UrlAddon instances
5. **Applies RealDebrid API key** to all addons (built-in and file-loaded)

The loader reports the current file-addon count and the number skipped as covered by a built-in.
Those values are live inventory, not stable project constants; do not copy them into docs or
assume that a loaded addon is verified for a particular folder.

**Important**: Many file URLs are **non-stream addons** (subtitles, catalogs, metadata, ratings, trackers). These are still loaded but won't return downloadable streams:
- Subtitle addons: OpenSubtitles, Addic7ed, Napisy24, Subscene, Podnapisi, YifySubtitles
- Catalog/metadata: IMDB Catalogs, TMDB, RPDB, Trakt, RottenTomatoes, Netflix Catalog
- Ratings/tracking: Ratings Aggregator, MyTrakt, Serializd, Simkl, Discussio
- Collections/misc: Marvel, Concerts, Radio, Broadcast, Up-Next

When these non-stream addons are queried for `/stream/`, they either:
- Return empty `{"streams": []}` → correctly handled
- Return advisory messages with `url` field → correctly identified and skipped
- Timeout or return errors → correctly logged and skipped

### Addon Features

- **11 URL configurers** colocated with their addon families (in `addon.py` registry)
- **Verified URL tracking**: only addon URLs that completed an actual download are saved to `config.servers` per folder; stream-only/non-downloading addons are not persisted
- **Custom addons**: create `addons/addons.txt` with one URL per line (URLs augment built-ins, not replace)
- **Addon Discovery**: `py-stremio --discover` scrapes addon sources, tests URLs, and merges working ones into `addons/addons.txt`
- **Experimental discovery**: interactive option 7 generates gitignored `addons/experimental.txt`
- **Preflight scan**: `preflight_discover_working_addons()` queries all addons concurrently on first run per folder to populate working server cache
- **Addon HTTP client**: addon stream endpoints use `httpx` first for reliable per-request timeouts; `tls_client`/`cloudscraper` remain fallbacks. The per-host rate limiter uses a re-entrant lock because success/429 reporting can happen while the request lock is still held.

## Important Files for Changes

| Change | Files |
|--------|-------|
| Add new quality levels | `configs/config_file.py` (QualitySettings), `download/stream_download.py` (select_quality_streams) |
| Change folder structure | `library/library_scanner.py`, `download/discovery.py` |
| Add new addons | `types/<category>/<ClassName>.py` (class) + `types/addon_registry.py` (AddonDef) + `types/builtin_addons.py` (re-export) |
| Modify addon search | `addons/addon_search_service.py`, `addons/manager.py` |
| Change download logic | `download/processing.py`, `download/stream_download.py` |
| Change metadata lookup | `stremio/stremio_metadata.py` |
| Modify state format | `state/app_state.py` |
| Modify config format | `configs/config_file.py` |
| Modify report format | `reports/report.py` |
| Add new settings | `configs/app_settings.py` |
| Change episode detection | `utils/media.py`, `library/media_file.py` |
| Add new error categories | `errors/error_category.py` (ErrorCategory enum, normalize_error) |
| Modify error output format | `errors/error_reporter.py` (print_summary) |
| Change URL redaction rules | `errors/error_reporter.py` (redact_url, _REDACT_PARAMS, _PATH_REDACTIONS) |
| Add new provider | `download/provider.py` (legacy path) |
| Modify progress UI | `services/progress.py` (_progress_line, _make_progress_printer) |
| Add bandwidth limits | `download/bandwidth_service.py` |
| Add addon discovery sources | `collect/sources.py` |
| Modify addon URL merging | `collect/merger.py` |

## Testing Notes

- Tests use pytest fixtures for temporary directories
- Mock all external HTTP services in tests (httpx mocking)
- State tests handle file I/O with cleanup
- Config tests verify default creation and loading
- Download processing tests mock the Stremio client
- **Monkeypatch caveat**: `from X import Y` in service modules creates a permanent local binding. When tests monkeypatch `X.Y`, the local binding in the service module is unaffected if the service was already imported by a prior test. Always also monkeypatch the local binding (`py_stremio.services.<name>.<function>`) in tests that need to mock functions imported via `from ... import` in service modules.
- **Test status**: 451 tests. `pytest --ignore=tests/test_new_servers.py -q` runs 441 deterministic tests; `tests/test_new_servers.py` is live-network coverage and can fail when third-party endpoints return 403/502.

## Current Status

- Modern Stremio addon-based download path is primary workflow
- RealDebrid integration functional (magnet → torrent → direct URL with short capped polling, zero-based Stremio fileIdx mapped to RD file IDs)
- Optional local torrent proxy support via `TORRENT_PROXY_URL`, including tracker/DHT source propagation for info-hash streams
- Stream selection tries direct/playable Stremio URLs before info-hash-only streams to avoid slow RealDebrid magnet polling when a cached RD proxy URL is already available.
- Language filtering no longer blocks Russian/Cyrillic-marked streams; those releases may include English audio, so the downloader tries them and relies on target-episode matching plus download validation to reject bad results.
- Append-only progress bars emit only the changed episode line in non-TTY output (stable numbering/no repeated full blocks) with per-episode rate limiting (~1 line/sec), no ANSI cursor blocks; position counters like `(1/6)` are never rendered as byte progress (`1 B / 6 B`), tiny invalid bodies are treated as permanent failed attempts instead of retrying the whole episode repeatedly, and retry rounds stay silent after the initial `Downloading N episodes` header
- Multi-threaded concurrent downloads with configurable workers (default: 2) and fair bandwidth sharing across active stream downloads only; workers that are still searching/resolving are not counted against the bandwidth share
- Partial download resume (.part files + Range headers)
- Final-file existence guard prevents stale tasks from re-downloading episodes already present on disk
- Working addon URL tracking and caching
- Metadata auto-fetch via Cinemeta + IMDb TSV dataset
- Movie folders resolve their own canonical IMDb ID and IMDb-derived language metadata; they remain separate one-request movie workflows, never series seasons.
- Auto-creation of new season folders for current year
- **Preflight optimization**: when preflight scan finds zero working addons, subsequent episodes skip the full addon re-scan (saves ~30s/episode)
- **`py-stremio-cron`** console entry point: same `AppService` path as `py-stremio`, with cron preset defaults (5 threads and 80% speed limit)
- **Interactive prompt split**: normal `py-stremio` menu actions that download ask for thread count and speed; `py-stremio-cron` uses 5 threads and 80% speed without prompts
- **Live bottom-bar controls** (TUI only): the controls bar described above lets the user adjust workers, speed, and 4K filter on the fly — these are session-only, not persisted to disk
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
