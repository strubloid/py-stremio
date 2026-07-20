# Py-Stremio

Terminal-based video download manager that monitors local series/movie folders, detects
missing content, and downloads via Stremio addons (Torrentio, MediaFusion, CIN, Comet,
Guindex, etc.) with RealDebrid support, quality fallback, and concurrent multi-threaded
downloads.

## Quick Start

```bash
# Install
pip install -e .

# Run interactive menu
py-stremio

# Full pipeline (non-interactive)
py-stremio --run

# Or for cron (preset 5 threads, 80% speed)
py-stremio-cron 2     # update metadata
py-stremio-cron 3     # download missing episodes
```

## Folder Structure

```
~/stremio-downloads/
├── series/
│   └── Show Name/
│       ├── s01/
│       │   ├── download-config.json
│       │   └── .download-state.json
│       └── s02/
└── movies/
    └── Movie Group/
        ├── download-config.json
        └── .download-state.json
```

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `ROOT_FOLDER` | `~/stremio-downloads` | Base download folder |
| `REAL_DEBRID_API_KEY` | — | Debrid service API key |
| `MAX_DOWNLOAD_ATTEMPTS` | `5` | Retry rounds per episode |
| `DOWNLOAD_THREADS` | `2` | Parallel download workers |
| `DOWNLOAD_STALL_TIMEOUT` | `60` | Seconds without bytes before aborting a stalled download |
| `INTERNET_SPEED_LIMIT` | `100` | Bandwidth cap (%) |
| `INTERNET_MAX_SPEED_MBPS` | auto-probed | Line speed for bandwidth calc |
| `PREFERRED_LANGUAGES` | `english` | Comma-separated language filter |
| `DRY_RUN` | `false` | Test mode — no actual downloads |
| `TORRENT_PROXY_URL` | — | Local torrent proxy (e.g. `http://127.0.0.1:11470`) |
| `METADATA_CACHE_HOURS` | `24` | Skip Cinemeta refresh for recently-checked folders |
| `STREMIO_ADDON_URL` | — | Override addon base URL |
| `LIMIT_EPISODES` | `0` | Max episodes per run (0=unlimited) |
| `MIN_COMPLETED_VIDEO_SIZE_MB` | `100` | Min file size for a valid completed download |
| `SMTP_HOST` / `SMTP_USER` / etc. | — | Email report settings |

## CLI Usage

```bash
# Interactive menu
py-stremio

# Individual pipeline steps
py-stremio --scan        # or: py-stremio 1
py-stremio --metadata    # or: py-stremio 2
py-stremio --download    # or: py-stremio 3

# Full pipeline
py-stremio --run         # or: py-stremio 4
py-stremio --run 7 100   # 7 threads, 100% speed

# Validate addon URLs
py-stremio --validate    # or: py-stremio 5

# Discover new addons
py-stremio --discover

# Refresh stream-capable movie/series addons from Stremio's live official collection
py-stremio --discover-official

# Cron (preset 5 threads, 80% speed, no prompts)
py-stremio-cron 2        # update metadata
py-stremio-cron 3        # download missing

# Crontab example
# PATH=/home/strubloid/apps/py-stremio/venv/bin:/usr/local/bin:/usr/bin:/bin
# 0 */3 * * * cd /home/strubloid/apps/py-stremio && py-stremio-cron 2
# 0 */2 * * * cd /home/strubloid/apps/py-stremio && py-stremio-cron 3
```

## Architecture

The primary pipeline (used by `py-stremio` and `py-stremio-cron`):

```
AppService.run_pipeline()
  → ScanService.run()              # scan folders, detect missing episodes
    → MetadataService.run()         # fetch Cinemeta/IMDb metadata
  → DownloadService.run()           # download via concurrent addon search
    → Stremio addons queried       # 64+ built-in + custom addons from addons.txt
      → Filter by title + episode  # IMDB cross-validation, diacritics-insensitive,
                                    # release-group-aware, finished-release detection
      → resolve_stream_download()  # local proxy → RealDebrid API → direct URL
      → download_stream_to_file()  # HTTP stream with resume, bandwidth limit, stall abort
```

The filter pipeline (`select_quality_streams`) is the gate before any download:

- **Advisory stream rejection** — config/login/error messages are filtered out
- **IMDB ID validation** — streams whose metadata IMDB disagrees with the target are rejected
- **Title matching** — matches the show title in the combined text (title + name + filename);
  diacritics-insensitive (Fiancé ↔ Fiance), whitespace-tolerant (double spaces)
- **Episode matching** — S##E## tokens, "no S/E token + no finished-release markers" passes
  through (info-hash addons like CIN)
- **Language filtering** — Russian/Cyrillic streams kept (may carry English audio)
- **Quality sort** — 4K > 1080p > 720p > 480p; direct URLs preferred over info-hash

## Key Features

- **64+ built-in Stremio addons** across 8 categories (Torrentio, Comet, aggregators,
  anime, IPTV, regional, misc, debrid) + unlimited URL-based addons via `addons.txt`
- **Concurrent addon search** — 10 at a time via ThreadPoolExecutor (≈12s for all)
- **RealDebrid support** — magnet → torrent → direct URL with short capped polling
- **Local torrent proxy** — info-hash streams resolved through a local Stremio-compatible proxy
- **Stall detection** — downloads that stop receiving bytes for 60+s are aborted via httpx
  read timeout; configurable via `DOWNLOAD_STALL_TIMEOUT`
- **Partial resume** — .part files + Range headers
- **Bandwidth limiting** — fair-share across active download threads
- **Working addon caching** — only addons that completed a download are saved to `servers`
- **Addon discovery** — `py-stremio --discover` scrapes sources, tests URLs, merges into `addons.txt`
- **Error reporting** — deduplicated, URL-redacted; full tracebacks only in debug mode
- **Email reports** — optional SMTP summary after each run

## Tests

```bash
pytest tests/ -v                         # 388 tests
pytest tests/ --cov=py_stremio           # coverage
```

## See Also

- `docs/project.md` — full technical documentation
- `docs/addons-check.md` — addon health audit
- `AGENTS.md` — AI agent context for working with this codebase

## License

MIT
