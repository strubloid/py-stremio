# Streaming library platform layouts

Research and implementation record for the six persisted library layouts. The platform
names describe interaction and composition references; the app keeps its own STREMIO
identity and uses only artwork and metadata already present in the local library.

| Platform | Implemented | Artwork | Mobile | Interactions |
|---|---|---|---|---|
| Stremio | Yes | Yes | Yes | Yes |
| Netflix | Yes | Yes | Yes | Yes |
| Apple TV | Yes | Yes | Yes | Yes |
| Plex | Yes | Yes | Yes | Yes |
| Disney+ | Yes | Yes | Yes | Yes |
| Prime Video | Yes | Yes | Yes | Yes |

## Verification record

- Desktop and 390×844 mobile screenshots were captured for each platform in
  `/tmp/opencode/platform-layout-captures/` during browser QA; series and film category
  screenshots were captured on desktop.
- Browser QA selected all six menu entries, opened the Series and Films views, checked
  that each view rendered cards, and reloaded after a saved layout change.
- Mouse dragging, touch swiping, keyboard arrow scrolling, featured-title pagination,
  card hover previews, and opening series/movie details were exercised. Plex grid/list
  switching was also exercised.
- The test catalog used real poster and backdrop URLs copied from existing library
  metadata into a temporary database. All 126 artwork requests returned HTTP 200, and
  the browser loaded the images without page errors.
- `npm run build`, `npm run lint`, and focused artwork/settings tests pass. Lint retains
  four existing Fast Refresh warnings in shadcn component files.
- The already-running API on port 8765 was an older process during diagnosis: it returned
  404 for `/api/spotlight`, 409 for inactive controls, and 502 for artwork. The updated
  development launcher now prioritizes this checkout on `PYTHONPATH`; restart the existing
  `npm run dev` process to load the same current API in that browser session. The fresh
  launcher/API stack used for the checks above returned HTTP 200 for the calendar-backed
  spotlight and artwork requests.

## Shared artwork and interaction implementation

- `src/library/layouts/shared.tsx` supplies poster/backdrop-aware artwork, load skeletons,
  explicit unavailable-artwork fallbacks, progress, media cards, featured titles, and
  horizontal rails.
- Rail controls use shadcn `Button`; each rail keeps native overflow scrolling and snap,
  adds mouse drag without swallowing ordinary clicks, and responds to arrow keys when its
  region is focused. Touch and touchpad scrolling remain native. Vertical page scrolling is
  not intercepted.
- The existing Cinemeta/IMDb metadata flow stores portrait posters and landscape
  backdrops independently. UI artwork continues through the local `/api/artwork` proxy,
  whose cache allows the persisted Metahub, TMDB, and Amazon image hosts and validates
  redirects and image MIME types.
- No platform logos or proprietary platform artwork are used. We omit genre/franchise
  rows when the local catalog does not contain that metadata, and actions open the app's
  existing detail/download flows rather than pretending it has streaming playback.

## Stremio

- **Reference:** [Stremio Tech Update #90](https://blog.stremio.com/stremio-tech-update-90-stremio-desktop-and-stremio-web-update/)
  (November 16, 2026), including Board Spotlight, large detail heroes, and phone layout
  improvements.
- **Implemented:** compact Board Spotlight, continue-watching rail, poster-led catalog
  grid, visible episode progress, and quick entry into series/movie details.
- **Components:** `src/library/layouts/StremioLayout.tsx` plus the shared cards, hero, and
  rail in `shared.tsx`.
- **Difference:** the original Board Spotlight can aggregate user-selected catalogs;
  this local manager features only recent releases already present in its catalog.
- **Remaining:** none identified in the browser QA run.

## Netflix

- **Reference:** [Netflix Help: How to search and browse](https://help.netflix.com/en/node/47765),
  describing homepage rows, top-level Shows/Movies shortcuts, and New & Popular/Latest
  sections.
- **Implemented:** dominant full-width cinematic hero, two explicit title actions, continue
  watching, recently added, series, and film rails; hover/focus reveals card actions.
- **Components:** `src/library/layouts/NetflixLayout.tsx`, `FeaturedHero`, `MediaRail`, and
  media cards in `shared.tsx`.
- **Difference:** no genres or recommendation claims are invented; the rails use local
  downloads and calendar-backed recent releases.
- **Remaining:** none identified in the browser QA run.

## Apple TV

- **Reference:** [Apple TV app](https://www.apple.com/apple-tv-app/), emphasizing curated
  recommendations, large cinematic artwork, and content discovery across a single
  destination.
- **Implemented:** a spacious, centered landscape hero, minimal controls, and wide
  `Up Next`, series, and film shelves.
- **Components:** `src/library/layouts/AppleTVLayout.tsx` and shared landscape rails/cards.
- **Difference:** Apple TV's cross-service catalog and human editorial picks are not
  available here; shelves use only this library's titles and downloaded episode state.
- **Remaining:** none identified in the browser QA run.

## Plex

- **Reference:** [Plex Library support](https://support.plex.tv/articles/200289526-library/),
  including personal-library organization, scanning, and Continue Watching controls.
- **Implemented:** compact personal-library grids, Continue Watching, title/missing sorting,
  and a switchable grid/list density. Media rows include episode counts, download state,
  missing count, and progress.
- **Components:** `src/library/layouts/PlexLayout.tsx` and shared media cards/rails.
- **Difference:** Plex server scanning, playback thresholds, collections, and other server
  metadata are outside this app's local catalog and are not simulated.
- **Remaining:** none identified in the browser QA run.

## Disney+

- **Reference:** [Disney+](https://www.disneyplus.com/), with cinematic featured artwork and
  curated playlists/collections in its current home experience.
- **Implemented:** blue-toned immersive hero, large landscape collections, Continue Watching,
  Recently Added, and a full-width collection gallery.
- **Components:** `src/library/layouts/DisneyPlusLayout.tsx` and shared feature/rail/card
  components.
- **Difference:** no Disney, Pixar, Marvel, Star Wars, or other franchise hubs are fabricated;
  the collections are strictly the user's series, films, and recent calendar entries.
- **Remaining:** none identified in the browser QA run.

## Prime Video

- **Reference:** [Prime Video](https://www.primevideo.com/), whose current homepage pairs a
  featured banner with differentiated rows such as recently added, trending, and content
  categories.
- **Implemented:** featured banner beside a compact recently released list, followed by
  Continue Watching, Recently Released, Your Series, and Your Films rails.
- **Components:** `src/library/layouts/PrimeVideoLayout.tsx` and shared cards/rails.
- **Difference:** rankings, subscriptions, genres, and storefront availability are not in the
  local data, so the quick list and shelves are based on actual library and release data.
- **Remaining:** none identified in the browser QA run.
