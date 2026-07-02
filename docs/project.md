# Project Documentation

## Overview

**Py-Stremio** is a terminal-based video download manager that monitors local series/movie
folders, detects missing content, and downloads via Stremio addons (Torrentio, MediaFusion,
CIN, Comet, Guindex, etc.) with RealDebrid support, concurrent addon search, quality
fallback, and bandwidth-aware multi-threaded downloads.

## Quick Start

```bash
pip install -e .
cp .env.example .env
mkdir -p ~/stremio-downloads/series
mkdir -p ~/stremio-downloads/movies
py-stremio             # interactive menu
py-stremio --run       # full pipeline
```

## Project Structure

```
py-stremio/
├── pyproject.toml                    # Package config with hatch
├── .env.example                      # Environment template
├── AGENTS.md                         # AI agent context (stays at root)
├── addons.txt                        # Custom addon URLs (optional, data file)
├── addons_experimental.txt           # Experimental addon URLs (optional, data file)
├── README.md                         # User documentation
├── docs/                             # Detailed documentation
│   ├── project.md                    # This file — technical reference
│   ├── addons-check.md               # Addon health audit findings
│   ├── errors.md                     # Error classification & reporting
│   ├── newserver.md                  # 3rd-party server analysis notes
│   └── plan-fix-search.md            # Implementation plan (historical)
├── scripts/
│   └── audit_addons.py               # Re-runnable addon audit script
├── py_stremio/                       # Package root
│   ├── __init__.py                   # Public exports
│   ├── main.py                       # CLI entry point
│   ├── app.py                        # AppService — orchestrator
│   ├── services/                     # High-level pipeline services
│   │   ├── scanner.py                # ScanService
│   │   ├── metadata.py               # MetadataService
│   │   ├── download.py               # DownloadService
│   │   └── progress.py               # ProgressRenderer
│   ├── components/                   # Domain-specific components
│   │   ├── configs/                  # Settings + config file management
│   │   ├── state/                    # Download state persistence
│   │   ├── library/                  # Media library scanning
│   │   ├── stremio/                  # Stremio API integration
│   │   ├── download/                 # Download execution + filter
│   │   ├── debrid/                   # RealDebrid API
│   │   ├── addons/                   # 64+ addon classes + types/
│   │   ├── collect/                  # Addon discovery/collection
│   │   ├── reports/                  # Terminal + email reports
│   │   └── errors/                   # Error deduplication
│   └── utils/                        # Shared utilities
├── tests/                            # 388 tests across 30+ files
└── scripts/
    └── audit_addons.py
```

## Architecture — Two Processing Paths

### 1. Modern Path (primary)

```
AppService.run_pipeline()
  → ScanService.run() → Scanner.scan()
  → MetadataService.run() → fetch Cinemeta/IMDb IDs
  → DownloadService.run()
    → process_season_folder() / process_movie_folder()
      → search_and_download()
        → search_all_addons_for_streams()   # 10 at a time
        → select_quality_streams()           # filter + sort
        → resolve_stream_download_url()
        → download_stream_to_file()          # HTTP with resume + stall detection
```

### 2. Legacy Path (maintained)

```
download_manager.py → library/series.py + movies.py → download/provider.py
```

## The Filter Pipeline

`select_quality_streams()` applies checks in this order:

1. **Usable** — must have `url` or `info_hash`
2. **Advisory rejection** — "configure this addon", "⛔", "ℹ" messages
3. **IMDB ID validation** — if both target and stream have an IMDB ID, they must match
4. **Title matching** — show title must appear in combined text (title+name+filename):
   - Diacritics-insensitive: `Fiancé` → `Fiance`
   - Whitespace-tolerant: `90  Day  Fiance` matches too
   - No-title-signal pass-through: pure codec/quality/release-group tokens are not
     counted as show-name signals (CIN's "CIN 4K 🛠 MeGusta" passes through)
   - Release group names in `_NON_TITLE_TOKENS`: MeGusta, EDITH, TRB, Kitsune, ...
5. **Episode matching** — S##E## / s##e## / season##episode## tokens:
   - Finished-release heuristic: year + resolution/format → strict check
   - No metadata → passes through (CIN, info-hash addons)
   - Contradicting S/E → rejected (correct show, wrong episode)
6. **Language filtering** — Russian kept, no-detection kept, multi-language kept
7. **Quality sort** — 4K > 1080p > 720p > 480p; URL bonus for direct streams

## Stall Detection

Downloads that stop receiving bytes are aborted via httpx's `read` timeout
(default: 60s, `DOWNLOAD_STALL_TIMEOUT`). `httpx.ReadTimeout` is caught and
translated to `StreamStallError`, which cleans up the `.part` file and falls
through to the next stream without attempting a RealDebrid retry.

## Addon System

**64+ built-in addon classes** across 8 categories:

| Category | Count | Examples |
|----------|-------|----------|
| Torrentio family | 7 | Torrentio, TorrentsDB, SortSeeders, Portuguese, Spanish, Hindi, Lite |
| Comet family | 7 | Comet, El fHosted, CometNet, HDHub, StremThru, Brazuca, Guindex |
| Aggregators | 23 | MediaFusion, KnightCrawler, EasyNews+, TPB+, Peerflix, Nucleus, Orion, DebridSearch, Stremify, Jackettio, AIOStreams, CineTorrent, Torrin, CIN, FlixStreams, MyCine, NebulaStreams, StreamViX, VidFastPro, Ytztvio, Till, Cinescrape, Supreme, Kod |
| Anime | 10 | AnimeKitsu, Akuma, Animepahe, Animeo, OnePace, Hanime, AnimesSeason, HiAnimeStreams, AnimeStream, YaStream |
| IPTV | 8 | Skyflix, ArgentinaTV, GreekTV, XtreamPro, AIOStreaming, Watchio, FreeMiumTV, EireGBTV |
| Regional | 12 | NoTorrent, LatinMovies, RicosStremio, FTVStremio, FigaroCorso, Einthusan, VStremio, Dubbindo, Mainelocalnews, FenixFlix, MicoLeaoDublado, Frenchio |
| Misc | 5 | WatchHub, YouTubePro, FShare, Consumet, SuperFlix |
| Debrid | 3 | DMM Cast, Premiumize, Peario |

**11 URL configurers**: TorrentioAddonConfigurer, CometAddonConfigurer,
HDHubAddonConfigurer, StremThruAddonConfigurer, BrazucaAddonConfigurer,
GuindexAddonConfigurer, StremioAddonConfigurer, NyaaAddonConfigurer,
YomiAddonConfigurer, IntellDebridSearchAddonConfigurer.

**Loading**: Built-ins always loaded first, then addons.txt supplement.
Deduplication by hostname — addons.txt URLs matching a built-in are
skipped, not replaced.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| ROOT_FOLDER | `~/stremio-downloads` | Base folder |
| REAL_DEBRID_API_KEY | None | Debrid service key |
| MAX_DOWNLOAD_ATTEMPTS | 5 | Retry rounds per episode |
| LIMIT_EPISODES | 0 | Max per run (0=unlimited) |
| MIN_COMPLETED_VIDEO_SIZE_MB | 100 | Min valid file size |
| DOWNLOAD_THREADS | 2 | Parallel workers |
| DOWNLOAD_STALL_TIMEOUT | 60 | Seconds without bytes → abort |
| METADATA_CACHE_HOURS | 24 | Skip refresh for recently checked |
| INTERNET_SPEED_LIMIT | 100 | Bandwidth % |
| INTERNET_MAX_SPEED_MBPS | auto-probed | Line speed |
| DRY_RUN | false | No actual downloads |
| PREFERRED_LANGUAGES | english | Language filter |
| TORRENT_PROXY_URL | None | Local proxy for info-hash streams |
| STREMIO_ADDON_URL | None | Override addon base URL |

## Testing

```bash
pytest tests/ -v                        # 388 tests
pytest --ignore=tests/test_new_servers.py  # skip network tests
pytest --cov=py_stremio --cov-report=term-missing  # coverage
```

## Error Categories

| Category | Detects |
|----------|---------|
| HTTP_4xx/5xx | httpx.HTTPStatusError |
| CONNECTION_DNS_ERROR | httpx.ConnectError |
| READ_TIMEOUT | httpx.TimeoutException |
| JSON_DECODE_ERROR | json.JSONDecodeError |
| INVALID_VIDEO_TOO_SMALL | InvalidVideoDownloadError |
| STALLED_DOWNLOAD | StreamStallError |
| UNKNOWN_ERROR | Everything else |

URL redaction: `apikey`, `api_key`, `token`, `realdebrid`, `rd`, `key`, `password`

## Current Status

- Modern Stremio addon-based download path is primary
- 64+ built-in addons + unlimited URL-based addons
- 388 tests all passing
- Diacritics-insensitive title matching
- Release-group-aware title signal detection
- Finished-release marker heuristic
- Stall detection with configurable timeout
- RealDebrid integration with capped polling
- Local torrent proxy support
- Multi-threaded concurrent downloads with fair bandwidth
- Addon discovery + validation tools
- Error reporting with deduplication and URL redaction
- Email reports via SMTP (optional)
- Legacy delegate provider path maintained but secondary

## Known Limitations

- No anime-style episode naming (uses SxxExx patterns)
- No subtitle download support
- No torrent client integration (direct HTTP or RealDebrid only)
- RealDebrid may return `451 infringing_file` for DMCA'd content
- Single-user, single-machine design
