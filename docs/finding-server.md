# Finding and updating Stremio servers

This is the repeatable procedure for adding current Stremio addon servers to py-stremio. Use it when a series has no usable sources or when the shared addon list needs refreshing.

For the verified Italian-content configuration, see [Italian content servers](italian-servers.md).

## What is updated

- `addons.txt` is the global candidate list. Every managed folder can query these addons.
- Each folder's `download-config.json` `servers` list is a separate verified cache. py-stremio adds an addon there only after it successfully downloads an episode or movie. Do not copy every discovered URL into every folder config.

## Primary source: Stremio's live collection

The live collection is:

`https://api.strem.io/addonscollection.json`

At the time this recipe was verified, it returned 95 addon records. Each record has a `transportUrl` and an embedded `manifest`. Only HTTP addons whose manifest declares both:

- a `stream` resource; and
- `movie` or `series` in `types`

can help py-stremio find downloadable video streams. Catalog, metadata, subtitle, and utility addons are intentionally excluded.

## Standard recipe

Run these commands from the repository root:

```bash
# 1. Refresh from the official Stremio collection only.
#    It downloads the live collection, filters stream-capable movie/series
#    addons, checks each /manifest.json endpoint, and atomically merges only
#    reachable URLs into addons.txt.
py-stremio --discover-official

# 2. Re-check the full active file. Failed URLs are commented out, never
#    deleted, so the historical list remains recoverable.
py-stremio --validate

# 3. Refresh folder metadata, then download missing media. Successful addon
#    downloads become that folder's verified `servers` cache automatically.
py-stremio --metadata
py-stremio --download
```

The focused official command is preferred for ordinary refreshes because it is bounded by Stremio's current collection. `py-stremio --discover` also includes community pages and generated/known hosting URLs; use it only when the official refresh did not produce enough candidates.

## How py-stremio keeps the list safe

1. Discovery strips `/manifest.json` and stores a normalized addon base URL.
2. Each candidate is fetched live at `<addon>/manifest.json` before it can be added.
3. Existing URLs are deduplicated; the merge is atomic.
4. The validator comments out unreachable active URLs instead of deleting them.
5. A live manifest alone is not proof that an addon can deliver an episode. A URL enters a folder's `servers` cache only after a real completed download.

## When a particular series is still missing servers

1. Run the standard recipe above.
2. Confirm the season's `download-config.json` has a correct `imdb_id` and expected episode metadata; run `py-stremio --metadata` again if necessary.
3. Run `py-stremio --download` for a real missing episode. The preflight search queries the global addon list and writes only successful providers to that folder's verified `servers` list.
4. If the folder still finds nothing, inspect the grouped error summary. Do not add API keys, debrid tokens, or copied personalized Stremio configuration URLs to `addons.txt`.

## Agent procedure

When asked to “add new servers”, “refresh Stremio servers”, or “find missing addon servers”, an agent must follow this document:

1. Read this file and inspect the current `addons.txt` plus git status.
2. Run the focused official discovery path first (`py-stremio --discover-official`).
3. Report how many candidates were collected, reachable, and newly merged, based on command output.
4. Run the focused collection tests and validate the changed `addons.txt`.
5. Never claim a folder's `servers` cache is repaired until an actual download has succeeded; discovery only updates global candidates.

## Verification

```bash
pytest tests/test_collect_sources.py tests/test_addon_validator.py -v
python - <<'PY'
from urllib.request import urlopen

with urlopen('https://api.strem.io/addonscollection.json', timeout=15) as response:
    records = response.read()
print(f'Official collection response: {len(records)} bytes')
PY
```

Use Stremio addons only for content you are authorized to access. Availability, stream support, and legality vary by addon and jurisdiction.
