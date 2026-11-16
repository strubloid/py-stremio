# Cinematic library browsing

This document records the Netflix-inspired interaction patterns used by the local
dashboard. It describes information architecture and browsing behavior, not a copy of
Netflix branding, assets, or proprietary interface details.

## Research notes

- Netflix's [search and browse guide](https://help.netflix.com/en/node/47765) describes
  a home page organized into title rows and shortcuts that narrow the catalog to shows
  or movies. The dashboard adapts that pattern into shelves for continue watching,
  series, and films, with a title search and explicit Series/Films navigation.
- Netflix's [getting started guide](https://help.netflix.com/en/node/102377) distinguishes
  discovery from playback and account management. The dashboard similarly separates
  library browsing from operational tools such as jobs, add-on health, and download
  controls.
- Nielsen Norman Group's [infinite-scrolling guidance](https://www.nngroup.com/articles/infinite-scrolling/)
  cautions against endless lists for goal-oriented finding. The library therefore uses
  searchable, titled shelves and a clear hierarchy rather than a single unbounded list.

## Information hierarchy

1. **Home** gives one featured series and a few purposeful shelves. Each title appears
   once, regardless of how many season folders it has.
2. **Series** opens a title detail view with its season folders grouped together.
3. **Season** opens an episode list with download state, watched state, file name, size,
   completion time, and the verified source when available.
4. **Films** keeps the existing one-folder-per-movie model and offers the same file,
   watched, and re-download controls.
5. **Activity** retains jobs, add-on health, live progress, and session controls without
   crowding the discovery surface.
6. **Calendar** follows the Stremio calendar reference supplied for this feature: a
   month grid for scanning dates and a selected-day agenda for episode details. Release
   dates come from Cinemeta episode metadata and can be refreshed.
7. **Settings** centralizes downloader preferences and service-key status. Secret values
   are masked, stored in the owner-only local catalog, and never returned to the client.

Artwork is keyed by the existing IMDb ID. Metadata refresh prefers IMDb's public
`og:image` poster URL and falls back to the matching Cinemeta poster; season tiles use
the first available season episode thumbnail when Cinemeta provides one. The API fetches
images from allowlisted IMDb/Cinemeta image hosts into a private local cache on first
display and serves them from the same origin, so browser hotlinking or CORS failures do
not leave blank covers. Typographic cover treatments remain the fallback when artwork
is missing or unavailable.

## State and actions

- Download status and watched status are independent. A downloaded episode can remain
  unwatched; marking an episode watched never modifies its media file or download state.
- Watched state is local to the SQLite catalog and can be changed per episode or for an
  entire season. A movie uses one watched-state entry.
- Re-download preserves the existing completed file in a same-folder backup while the
  downloader attempts a replacement. Success removes the backup; failure restores the
  previous file.
- Episode details show the source recorded by the completed download, not an unverified
  search result.
- Every action is a real button with an accessible label; season selection, search, and
  top-level navigation work without hover.

## Sources

- Netflix Help Center, “How to search and browse Netflix”: <https://help.netflix.com/en/node/47765>
- Netflix Help Center, “Getting started with Netflix”: <https://help.netflix.com/en/node/102377>
- IMDb title pages (poster source via public Open Graph metadata): <https://www.imdb.com/title/tt0111161/>
- Nielsen Norman Group, “Infinite Scrolling Is Not for Every Website”: <https://www.nngroup.com/articles/infinite-scrolling/>
