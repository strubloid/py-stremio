# py-stremio dashboard

The dashboard uses Vite for development and serves the API from the same Python
environment as the CLI.

## Development

From the repository root, activate the project's virtual environment and install the
optional API dependencies if needed:

```bash
python -m pip install -e '.[api]'
cd ui/react
npm install
npm run dev
```

`npm run dev` starts `py-stremio-api` first, waits for port 8765, then starts Vite.
The API reloads when Python files change, so schema and metadata updates are picked up
without leaving the dashboard on an older backend process.
Use `PY_STREMIO_API_BIN` when the entry point is outside `PATH`, or
`PY_STREMIO_API_PORT` to select a different local port. `npm run dev:web` runs only
Vite when an API process is already running.

## Build and checks

```bash
npm run lint
npm run build
```
