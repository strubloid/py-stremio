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
py-stremio-cron 2     # update metadata + download
py-stremio-cron 3     # update metadata
py-stremio-cron 4     # download missing episodes
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
    └── Movie Title/                  # one folder represents one movie
        ├── download-config.json
        └── .download-state.json
```

## Movie Folders

Each direct child of `movies/` is one movie request, not a series group. For example:

```text
movies/Michael/
```

During `py-stremio --metadata`, the movie path resolves a canonical title and IMDb ID from
Cinemeta's movie catalog. The downloader then makes one movie request with that ID — never a
season or episode request. If a title is ambiguous, put the intended IMDb ID in that folder's
`download-config.json` before downloading.

Movie folders do not inherit `PREFERRED_LANGUAGES`; that setting is the default only for newly
created series-season configs. Movie languages are populated from IMDb title metadata when its
public markup is available. If IMDb language metadata is unavailable, the movie remains
language-neutral rather than inheriting an unrelated global language preference.

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
| `PREFERRED_LANGUAGES` | `english` | Default language filter for new series-season configs; movie metadata supplies movie languages |
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
py-stremio --scan        # or: py-stremio 3
py-stremio --metadata    # or: py-stremio 3
py-stremio --download    # or: py-stremio 4
py-stremio --update-and-download  # or: py-stremio 2

# Full pipeline
py-stremio --run         # or: py-stremio 1
py-stremio --run 7 100   # 7 threads, 100% speed

# Validate addon URLs
py-stremio --validate    # or: py-stremio 6

# Discover new addons
py-stremio --discover    # or: py-stremio 5

# Refresh stream-capable movie/series addons from Stremio's live official collection
py-stremio --discover-official

# Cron (preset 5 threads, 80% speed, no prompts)
py-stremio-cron 2        # update metadata + download
py-stremio-cron 3        # update metadata
py-stremio-cron 4        # download missing

# Crontab example
# PATH=/home/strubloid/apps/py-stremio/venv/bin:/usr/local/bin:/usr/bin:/bin
# 0 */3 * * * cd /home/strubloid/apps/py-stremio && py-stremio-cron 3
# 0 */2 * * * cd /home/strubloid/apps/py-stremio && py-stremio-cron 4
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
- **Movie partial resume** — `.part` files + Range headers; a movie source that ignores a resume request is skipped without truncating the saved partial back to zero
- **Bandwidth limiting** — fair-share across active download threads
- **Working addon caching** — only addons that completed a download are saved to `servers`
- **Movie-specific metadata** — one folder → one IMDb-backed movie request; no season/episode tracking
- **Addon discovery** — `py-stremio --discover` scrapes sources, tests URLs, merges into `addons.txt`
- **Error reporting** — deduplicated, URL-redacted; full tracebacks only in debug mode
- **Email reports** — optional SMTP summary after each run

## Tests

```bash
pytest tests/ -v                         # 451 tests (includes live network checks)
pytest --ignore=tests/test_new_servers.py # 441 deterministic tests
pytest tests/ --cov=py_stremio           # coverage
```

## See Also

- `docs/project.md` — full technical documentation
- `docs/addons-check.md` — addon health audit
- `AGENTS.md` — AI agent context for working with this codebase

## License

MIT
