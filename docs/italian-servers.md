# Italian content servers

## Configured source

`Torrentio-IT` is a built-in py-stremio addon. It queries:

`https://torrentio.strem.fun/language=italian/`

When RealDebrid is configured, py-stremio injects the runtime key into the addon URL and does not write the key to `addons.txt` or source control.

Live verification on 2026-07-20:

- The Italian Torrentio manifest returned HTTP 200.
- Its `Game of Thrones` S01E01 stream query returned 58 Italian or Italian-compatible stream records, including `ITA` and `ITA/ENG` releases.

The local `.env` preference is now `PREFERRED_LANGUAGES=italian`, so the final stream selector prioritizes Italian-marked releases. Restart a running py-stremio process before the setting is read again.

## Existing Italian addons

- `FigaroCorso` is already a built-in regional addon at `https://www.figarocorso.info/stremio`. Its manifest is live, but the generic Game of Thrones check returned no streams, so it remains a supplemental source rather than a verified series source.
- The existing `ItaTV` entry (`6ef53e8aac88-itatv.baby-beamup.club`) also has a live manifest but returned no streams for the same series test. It appears useful only for its own catalog/live-TV scope.

## Not added as a shared server

MammaMia is actively maintained and advertises Italian movies, series, anime, and live TV, but its README requires a user-hosted deployment and a TMDB key. It is not a stable public manifest URL, so it was deliberately not added to `addons.txt`. A self-hosted installation can be added later as a custom addon URL after it is deployed and its manifest plus a real stream request both pass validation.

## Use

```bash
# New built-in addons and .env settings load in a new process.
py-stremio --metadata
py-stremio --download
```

A folder's `download-config.json` `servers` cache is updated only after a completed download. The presence of `Torrentio-IT` makes it available for preflight/search; it does not claim a particular series has been verified until that download succeeds.

## Live probe: Temptation Island (IT) S14E04

Use this as the Italian-content regression probe, without downloading media:

```text
Stremio / IMDb ID: tt37449227:14:4
Title: Temptation Island (IT) — S14E04
Release date in Cinemeta: 2025-07-31
```

On 2026-07-20, `Torrentio-IT` returned no streams for this exact episode. A full preflight found one response from HDHub, but its three generic `Castle` entries were rejected by py-stremio's IMDb/title/episode validation. This is the correct result: do not treat a generic addon response as a working server for the requested episode.

Availability is live and can change, so this is an operational probe rather than a deterministic unit test. A successful probe must return at least one stream that survives target validation before it can be considered a verified server.

Use only sources and content you are authorized to access.
