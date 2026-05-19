# Project Documentation

## Overview

Py-Stremio is a terminal-based video download manager designed for legal content from a local folder structure. It monitors folders for missing episodes/movies and tracks download progress.

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
   mkdir -p /home/strubloid/stremio-downloads/series
   mkdir -p /home/strubloid/stremio-downloads/movies
   ```

4. Run the application:
   ```bash
   python -m py_stremio.main
   ```

## Architecture

### Core Components

1. **Settings** (`settings.py`)
   - Loads configuration from environment variables
   - Provides default values for all settings
   - Checks SMTP configuration status

2. **Scanner** (`scanner.py`)
   - Recursively scans series/movies folders
   - Creates folder structure if missing
   - Identifies folder types (series/movies)

3. **Config File** (`config_file.py`)
   - Manages `download-config.json` files
   - Auto-creates default configs for new folders
   - Parses quality settings

4. **State** (`state.py`)
   - Tracks downloaded items in `.download-state.json`
   - Records failed download attempts
   - Prevents duplicate downloads

5. **Provider** (`provider.py`)
   - Abstract base provider interface
   - RealDebrid provider (when API key provided)
   - Mock provider for dry-run/testing
   - Fallback provider for unavailable services

6. **Downloader** (`downloader.py`)
   - Orchestrates downloads with quality fallback
   - Manages retry attempts
   - Updates state on success/failure

7. **Series** (`series.py`)
   - Detects existing episodes by filename parsing
   - Plans missing episodes based on `episode_count`
   - Downloads with quality fallback

8. **Movies** (`movies.py`)
   - Detects existing movies in folder
   - Downloads movie if not already present
   - Respects `download_all_related` setting

9. **Report** (`report.py`)
   - Formats terminal output
   - Generates email reports
   - Handles SMTP sending with error handling

## Data Flow

```
main.py
  ├── Scanner.ensure_folders()  → Creates directories
  ├── Scanner.scan()            → Finds all folders
  │
  ├── For each folder:
  │   ├── load_config()         → Reads/creates config
  │   ├── Skip if enabled=false
  │   │
  │   ├── Series folder:
  │   │   ├── detect_existing_episodes()
  │   │   ├── plan_missing_episodes()
  │   │   └── Downloader.download_with_fallback()
  │   │
  │   └── Movies folder:
  │       ├── detect_existing_movies()
  │       └── Downloader.download_with_fallback()
  │
  └── Report.print_and_send_report()
```

## Quality Fallback Logic

1. Start with preferred quality from config
2. Try fallback qualities in order
3. Skip if attempt count >= MAX_DOWNLOAD_ATTEMPTS
4. Return first successful result or final failure

## Provider Priority

1. RealDebrid (if API key valid)
2. Mock (if DRY_RUN=true)
3. Fallback (no-op, returns error)

## State Files

### download-config.json
Source of truth for user preferences. Defines what the user wants.

### .download-state.json
Track what the app has done. Prevents re-downloading and tracks failures.

## Testing

Run all tests:
```bash
pytest tests/ -v
```

Run specific test file:
```bash
pytest tests/test_series.py -v
```

Run with coverage:
```bash
pytest tests/ --cov=src/py-stremio --cov-report=term-missing
```

## Dry Run Mode

Enabled by default (`DRY_RUN=true`). In dry-run mode:
- No actual downloads occur
- Mock provider is used
- All operations are logged but not executed
- Safe for testing configuration

To enable live mode:
```bash
export DRY_RUN=false
```

## Email Reports

Email reports are only sent when all SMTP settings are configured:
- SMTP_HOST
- SMTP_USER
- SMTP_PASSWORD
- SMTP_FROM
- SMTP_TO

Set `DRY_RUN=false` in `.env` for production use.

## Known Limitations

- MVP uses placeholder/mock download logic
- RealDebrid integration is basic (no actual torrent handling)
- Episode detection relies on filename patterns (episode N, E##)
- No support for anime-style naming conventions