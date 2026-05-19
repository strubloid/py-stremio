# Py-Stremio

Terminal-based video download manager for legal content from local folder structure.

## Features

- Scan and process series/movie download folders
- Quality fallback (preferred -> fallbacks)
- Download state tracking to avoid duplicates
- Dry-run mode by default
- Email reports via SMTP
- Mock provider for testing without API keys

## Installation

```bash
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROOT_FOLDER` | `/home/strubloid/stremio-downloads` | Root download folder |
| `REAL_DEBRID_API_KEY` | - | Real-Debrid API key (optional) |
| `MAX_DOWNLOAD_ATTEMPTS` | `2` | Max retries per item |
| `DRY_RUN` | `true` | Enable dry-run mode |
| `SMTP_HOST` | - | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | - | SMTP username |
| `SMTP_PASSWORD` | - | SMTP password |
| `SMTP_FROM` | - | From email address |
| `SMTP_TO` | - | To email address |
| `SMTP_USE_TLS` | `true` | Use TLS for SMTP |

## Folder Structure

```
/home/strubloid/stremio-downloads/
├── series/
│   └── Show Name/
│       └── s01/
│           └── download-config.json
└── movies/
    └── Movie Group/
        └── download-config.json
```

## Usage

```bash
python -m py_stremio.main
```

Or with the installed package:

```bash
py-stremio
```

## Config Files

### Series (`download-config.json`)

```json
{
  "type": "series",
  "title": "Show Name",
  "season": 1,
  "episode_count": 12,
  "quality": {
    "preferred": "1080p",
    "fallbacks": ["720p", "480p"],
    "allow_higher": false,
    "allow_lower": true
  },
  "language": "any",
  "subtitles": "any",
  "provider": "auto",
  "enabled": true
}
```

### Movies (`download-config.json`)

```json
{
  "type": "movies",
  "search_group": "Movie Group Name",
  "quality": {
    "preferred": "1080p",
    "fallbacks": ["720p", "480p"],
    "allow_higher": false,
    "allow_lower": true
  },
  "language": "any",
  "provider": "auto",
  "enabled": true,
  "download_all_related": true
}
```

## Running Tests

```bash
pytest tests/ -v
```

## License

MIT