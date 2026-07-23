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
├── addons/                           # External addon inventories
│   ├── addons.txt                    # Local/discovered URLs (gitignored)
│   ├── addons.txt.example            # Custom inventory template
│   ├── stremio.txt                   # Tracked baseline manifests
│   └── experimental.txt              # Option 7 output (gitignored)
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
│   │   ├── addons/                   # Built-in addon classes + types/
│   │   ├── collect/                  # Addon discovery/collection
│   │   ├── reports/                  # Terminal + email reports
│   │   └── errors/                   # Error deduplication
│   └── utils/                        # Shared utilities
├── tests/                            # 451 tests, including live network checks
└── scripts/
    └── audit_addons.py
```

## Architecture — Two Processing Paths

### 1. Modern Path (primary)

```
AppService.run_pipeline()
  → ScanService.run() → Scanner.scan()
  → MetadataService.run() → enrich series and movie configs
  → DownloadService.run()
    → process_season_folder() / process_movie_folder()
      → search_and_download()
        → search_all_addons_for_streams()   # 10 at a time
        → select_quality_streams()           # filter + sort
        → resolve_stream_download_url()
        → download_stream_to_file()          # HTTP with resume + stall detection
```

### Movie-folder contract

Every direct child of `movies/` represents exactly one movie. `MetadataService` resolves its
title through Cinemeta's movie catalog, stores the canonical title and IMDb ID, and asks IMDb
title markup for languages. `process_movie_folder()` searches once using
`content_type="movie"` with `season=None` and `episode=None`; it does not use series episode
tracking.

`PREFERRED_LANGUAGES` applies to new series-season configs only. Movie configs stay
language-neutral until IMDb language metadata is available; they must never inherit an unrelated
global language. For ambiguous movie names, set `imdb_id` explicitly in that folder's
`download-config.json` before downloading.

### Verified addon-server cache

`download-config.json` `servers` is a per-folder cache of completed-download providers, not a
discovery result. Preflight responders may be used for the current attempt, but they are saved
only after a media transfer succeeds. If no download succeeds, do not retain a newly discovered
provider as verified.

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

## Movie Partial-Download Safety

Movie transfers write to `{movie}.mkv.part` and resume only when a source
honours the `Range` request (`206 Partial Content`). If a movie source ignores
the request and responds with a fresh full body, that source is skipped and the
existing partial is kept unchanged. The downloader tries another stream rather
than silently truncating the partial and restarting at zero. A hard shutdown
therefore leaves a real transferred partial available for a later run; sources
that do not support byte-range resume cannot complete it, but must not destroy
it. This protection is intentionally confined to the movie path; existing
series handling is unchanged.

## Addon System

**Built-in addon classes** are organized across these categories:

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
| Meteor | 1 | MeteorForTheWeebs |
| Sootio | 1 | Sootio |

**13 URL configurers**: TorrentioAddonConfigurer, CometAddonConfigurer,
HDHubAddonConfigurer, StremThruAddonConfigurer, BrazucaAddonConfigurer,
GuindexAddonConfigurer, StremioAddonConfigurer, NyaaAddonConfigurer,
YomiAddonConfigurer, IntellDebridSearchAddonConfigurer, MeteorAddonConfigurer,
SootioAddonConfigurer.

**Loading**: Built-ins always loaded first, then `addons/stremio.txt` and `addons/addons.txt` supplements.
Deduplication by hostname — file URLs matching a built-in are
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
| PREFERRED_LANGUAGES | english | Default filter for new series-season configs; movie metadata determines movie languages |
| TORRENT_PROXY_URL | None | Local proxy for info-hash streams |
| STREMIO_ADDON_URL | None | Override addon base URL |

## Testing

```bash
pytest tests/ -v                        # 451 tests, including live endpoint checks
pytest --ignore=tests/test_new_servers.py  # 441 deterministic tests
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
- Built-in addons + unlimited URL-based addons
- Movie metadata and download flow are separate from series seasons
- 441 deterministic tests passing; live-network tests depend on third-party endpoint availability
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
