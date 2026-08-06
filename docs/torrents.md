# Torrent Site Integration for py-stremio

## The Problem

Sites like **ext.to** are torrent trackers/search engines, not Stremio addons.
They don't serve `/manifest.json` or Stremio stream endpoints. They also use
**Cloudflare JS challenge protection**, blocking curl/httpx/requests by default.

The project already gets ext.to content indirectly via **Sootio** and
**Intell-DebridSearch** addons — these scrape ext.to internally and expose
results as Stremio streams.

## Existing Tools in Project

- `cloudscraper` — bypasses Cloudflare JS challenges
- `tls_client` — Chrome 120 TLS fingerprint emulation
- `addon_get()` / `addon_get_streams()` in `cloudscraper_client.py`
- RealDebrid API for magnet → direct URL resolution
- `stream_download.py` for HTTP downloads with resume

## Approaches

### A. Stremio Addon Wrapper (preferred, already works)

Build a lightweight addon class per torrent site that:
1. Searches the site via cloudscraper or the site's API
2. Parses result pages for magnet links
3. Returns streams with `infoHash` for RealDebrid resolution

**Proof:** Sootio and Intell-DebridSearch already do this for ext.to.

**Adding more sites:** For each new torrent site, create a class in
`components/addons/types/` that implements `HttpAddon` with a
Cloudflare-aware search-and-streams endpoint.

### B. Direct Torrent Site Scraper (new component)

A standalone `TorrentSiteScraper` that bypasses Stremio entirely:

```
torrent_search(query, site="ext.to")
  → cloudscraper GET "https://ext.to/search/?q={query}"
  → parse HTML results → extract magnet links per result
  → return list of {title, magnet, seeders, size}

torrent_download(magnet, download_dir)
  → feed magnet to RealDebrid (info_hash → torrent → direct URL)
  → OR download torrent file and stream content
```

#### What a TorrentSiteScraper needs:

1. **Cloudflare bypass** — already have `cloudscraper` and `tls_client`
2. **HTML parser** — `beautifulsoup4` or `lxml` needed (not in deps yet)
3. **Result page parsing** — each site has different HTML structure
4. **Magnet/torrent extraction** — parse `<a href="magnet:?...">` or
   torrent file downloads
5. **RealDebrid feed** — use existing `RealDebridClient` to add magnet
   → poll until cached → get direct download URL
6. **Episode-to-release matching** — match scraped titles against
   expected `Show S01E12` pattern (already done in `processing.py`)

#### Proposed module structure:

```
components/torrent/
├── __init__.py
├── site_scraper.py          # Base class for torrent sites
├── sites/
│   ├── __init__.py
│   └── ext_to.py            # ext.to scraper
├── magnet_resolver.py       # Magnet → RealDebrid → direct URL
└── release_matcher.py       # Match torrent title to show/episode
```

#### Site-specific scrapers:

| Site | Challenge | Approach |
|------|-----------|----------|
| ext.to | Cloudflare managed challenge | `cloudscraper` + session cookies |
| 1337x | Cloudflare | `cloudscraper` or plain scraping via Torrentio |
| RARBG | Defunct | Already covered by Torrentio |
| TPB | Cloudflare, varies by mirror | `cloudscraper` + mirror list |

#### Risk: ext.to Cloudflare Challenge

ext.to uses **managed challenge** (not just JS challenge). This means:
- `cloudscraper` may fail (managed challenges require solving a captcha)
- `tls_client` with Chrome fingerprint may work temporarily
- Best approach: use a pool of proxy IPs + rotating User-Agents
- If managed challenge is too aggressive, fall back to Sootio/Intell-DebridSearch

## Recommendation

**Short-term:** The existing Sootio and Intell-DebridSearch addons already
cover ext.to content. Enable those in `download-config.json` per folder.

**Medium-term:** Create a `TorrentSiteScraper` component (Approach B) for
sites not covered by any existing Stremio addon. Use `cloudscraper` for
bypass and integrate with the existing download pipeline via magnet →
RealDebrid.

**Long-term:** Consider running a local proxy addon service that wraps
multiple torrent sites into a single Stremio-compatible manifest, similar
to how Comet/MediaFusion aggregate sources.
