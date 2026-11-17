# Streaming library layout research

Research checked on 17 November 2026. The design borrows interaction patterns, not
branding, proprietary artwork, or exact page compositions.

## References and useful patterns

### Stremio

- [Tech Update #90: Desktop and Web](https://blog.stremio.com/stremio-tech-update-90-stremio-desktop-and-stremio-web-update/)
  (16 November 2026) reports a Board Spotlight slideshow, grouped settings with search,
  a redesigned title-details hero with a season/episode picker, and floating discover
  previews. These map directly to the recent-release hero, grouped Settings page, series
  detail panel, and selection of one featured item at a time.
- [Tech Update #83: Stremio v5 and Web](https://blog.stremio.com/stremio-tech-update-83-stremio-v5-stremio-web-updated/)
  notes context-aware card navigation and episode rows that open details rather than
  unexpectedly starting playback. This project keeps selection and download actions
  explicit and separate.
- The user-provided Stremio calendar screenshot is the reference for the month grid plus
  selected-day release agenda.

### Netflix

- [How to search and browse Netflix](https://help.netflix.com/en/node/47765) describes
  title rows, category shortcuts, and a dedicated search flow. The project uses named
  shelves and explicit Home/Series/Films navigation rather than an undifferentiated list.
- [Getting started with Netflix](https://help.netflix.com/en/node/102377) separates
  finding content from account management. The dashboard similarly separates discovery,
  operations, and Settings.

### Apple TV

- [Apple TV app](https://www.apple.com/apple-tv-app/) describes curated recommendations,
  premium presentation, and discovery across a single destination. This supports a spacious
  landscape-art hero with quiet, manually controlled navigation; the library does not invent
  Apple's cross-service recommendations.

### Disney+

- [Disney+](https://www.disneyplus.com/) describes Playlists as themed collections of
  movies and episodes. This supports purposeful shelves and collections, while this
  application limits shelves to data it actually has (recent releases, continue watching,
  series, films) instead of inventing genres or recommendations.

### Plex

- [Plex Library settings](https://support.plex.tv/articles/200289526-library/) covers
  automatic and periodic scans, partial scans, preview thumbnails, and playback progress
  thresholds. For a local filesystem library these patterns reinforce mtime-based refresh,
  file-specific detail, and a clear distinction between downloaded and watched state.

### Jellyfin

- [Jellyfin clients](https://jellyfin.org/docs/general/clients/) describes a client
  ecosystem with configurable server connections and separate user-facing clients; its
  [CSS customization guide](https://jellyfin.org/docs/general/clients/css-customization/)
  notes that custom CSS is an advanced, potentially fragile override. This project keeps
  its six layouts as first-class components/styles rather than relying on user CSS hacks.

### Navigation and carousel caution

- [Nielsen Norman Group: Infinite Scrolling Is Not for Every Website](https://www.nngroup.com/articles/infinite-scrolling/)
  warns that endless scrolling can make goal-oriented finding and returning to a known
  item difficult. Horizontal shelves are therefore limited to a clear category, keep
  native touchpad/touch scrolling, and provide previous/next controls. Plex provides a
  searchable, sortable dense view for direct lookup.

## Platform-specific compositions

The Settings layout selector changes the browse composition, not the catalog data. The
separate platform-by-platform references, interactions, components, and verification
status are tracked in [platform-layouts.md](platform-layouts.md):

1. **Stremio** (default): an artwork-led catalogue with a compact Board Spotlight.
2. **Netflix**: a dominant cinematic hero followed by multiple content rails.
3. **Apple TV**: spacious landscape artwork and curated, editorial shelves.
4. **Plex**: a sortable personal library with poster and list views.
5. **Disney+**: immersive featured artwork and large, data-backed collections.
6. **Prime Video**: a featured banner paired with practical library discovery.

All use the same persisted poster/backdrop metadata, series and episode IDs, watch state,
download state, and click actions. The selected layout is persisted in the local SQLite
preferences and remains independent of media files.
