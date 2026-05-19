# AGENTS.md - Context for Future AI Agents

## Project Overview

**py-stremio** is a terminal-based video download manager for legal content from a local folder structure. It monitors series/movie folders, detects missing content, and downloads with quality fallback.

## Key Technologies

- Python 3.10+
- python-dotenv for settings
- httpx for HTTP requests
- pytest for testing

## Project Structure

```
py-stremio/
├── pyproject.toml              # Package config with hatch
├── .env.example                # Environment template
├── README.md                   # User documentation
├── project.md                  # Technical documentation
├── AGENTS.md                   # This file - agent context
├── py_stremio/                 # Package (root level)
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── settings.py             # Environment configuration
│   ├── utils.py                # Helper functions
│   ├── scanner.py              # Folder discovery
│   ├── config_file.py          # Config management
│   ├── state.py                # State tracking
│   ├── provider.py             # Download providers
│   ├── downloader.py          # Download orchestration
│   ├── series.py               # Series processing
│   ├── movies.py               # Movie processing
│   └── report.py              # Report generation
└── tests/
    ├── test_scanner.py
    ├── test_config_file.py
    ├── test_series.py
    ├── test_movies.py
    ├── test_state.py
    └── test_quality_fallback.py
```

## Important Patterns

### Config vs State Files

- **download-config.json**: User preferences (what they want)
- **.download-state.json**: App tracking (what was done)

### Folder Detection

- Series folders: `series/{show_name}/s{number}/`
- Movies folders: `movies/{group_name}/`
- Season number extracted from folder name (`s01`, `S02`, etc.)

### Episode Number Detection

Uses regex patterns in `utils.parse_episode_number()`:
- `episode 01.mkv` → 1
- `E05.mkv` → 5
- `Show_S01E12.mp4` → 12

### Quality Fallback Order

1. Preferred quality
2. Fallback qualities in list order
3. Skip if MAX_DOWNLOAD_ATTEMPTS reached

### Provider Selection

```
IF REAL_DEBRID_API_KEY exists AND valid
  → Use RealDebridProvider
ELIF DRY_RUN=true
  → Use MockProvider
ELSE
  → Use FallbackProvider (no-op)
```

## Settings Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| ROOT_FOLDER | `/home/strubloid/stremio-downloads` | Base folder |
| SERIES_FOLDER | `{ROOT}/series` | Series root |
| MOVIES_FOLDER | `{ROOT}/movies` | Movies root |
| REAL_DEBRID_API_KEY | None | Debrid service |
| MAX_DOWNLOAD_ATTEMPTS | 2 | Retry limit |
| DRY_RUN | true | Test mode |
| SMTP_* | None | Email config |

## Run Commands

```bash
# Install
pip install -e .

# Run
python -m py_stremio.main

# Test
pytest tests/ -v

# Type check (if mypy installed)
mypy src/py-stremio/
```

## Current Status

- MVP implementation complete
- Core features working
- Basic tests in place
- Mock provider for testing
- RealDebrid integration placeholder

## Potential Improvements

1. Actual RealDebrid API integration for torrent downloads
2. Support for more naming conventions
3. Better error handling and recovery
4. Progress tracking for active downloads
5. Webhook/notification support
6. Configuration CLI tool
7. More granular quality matching
8. Support for multi-season series
9. Batch operations for large libraries

## Important Files for Changes

- Add new quality levels → `utils.py` and `config_file.py`
- Change folder structure → `scanner.py`
- Add new provider → `provider.py`
- Change state format → `state.py`
- Modify report format → `report.py`
- Change episode detection → `utils.py`
- Add new settings → `settings.py`

## Testing Notes

- Tests use pytest fixtures for temporary directories
- Mock all external services in tests
- State tests handle file I/O with cleanup
- Config tests verify default creation and loading