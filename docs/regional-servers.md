# Regional stream servers

This inventory records clean, public Stremio addon endpoints for broader
movie/series searches. Availability changes frequently. A live manifest is not
proof that an addon has a requested title, and an addon is added to a folder's
`servers` cache only after a completed download.

## Verified broad fallbacks

Live probe on 2026-07-22 using movie IMDb ID `tt11378946`:

| Addon | Endpoint | Coverage | Probe result | RealDebrid path |
|---|---|---|---:|---|
| TorrentsDB | `https://torrentsdb.com` | Broad international indexes, including Italian and French sources | 47 info-hash streams | py-stremio sends selected info hashes through its RD resolver |
| Peerflix | `https://peerflix.mov` | Spanish and English torrents | 11 info-hash streams | py-stremio sends selected info hashes through its RD resolver |
| NoTorrent | `https://addon.notorrent2.workers.dev` | General direct streams | 7 rows, some downloadable URLs | Direct HTTP; not an RD index |

TorrentsDB and Peerflix are active in `addons/experimental.txt`. NoTorrent is
already covered by the normal built-in/global inventory, so it is not duplicated
in the experimental tier.

## Regional endpoints

These public endpoints had live manifests on 2026-07-22 but returned no streams
for the `tt11378946` probe. They remain normal built-in/global candidates where
applicable; zero results for one title does not prove they are dead.

| Region | Addon | Endpoint | Scope |
|---|---|---|---|
| Brazil/Portuguese | Brazuca Torrents | `https://94c8cb9f702d-brazuca-torrents.baby-beamup.club` | Torrent movie/series/anime |
| Brazil/Portuguese | Mico-Leao Dublado | `https://27a5b2bfe3c0-stremio-brazilian-addon.baby-beamup.club` | Dubbed direct movie streams |
| Latin America/Spanish | Latin Movies | `https://latinmovies.vercel.app` | Direct movie/series streams |
| Latin America/Spanish | Latin Movies 2 | `https://latinmovies2.vercel.app` | Direct movie/series streams |
| Italy/Italian | Ita TV | `https://6ef53e8aac88-itatv.baby-beamup.club` | TV/program scope, not a broad movie index |

No credible live Germany/German-specific public movie/series endpoint was
verified. Broad torrent indexes may still contain German releases. Do not label
an endpoint as German-specific without a real stream probe demonstrating that
coverage.

## Not ready-to-use servers

- Frenchio's clean endpoint returns a configuration prompt and requires a personalized setup.
- CometNet returned an advisory row for the probe, not downloadable media.
- Jackettio and AIOStreams are configuration frontends; their clean roots are not preconfigured stream sources.
- IPTV, catalog, metadata, ratings, and subtitle addons cannot supply downloadable movie files.
- Personalized addon URLs containing RD tokens must never be stored in `addons/addons.txt`, experimental lists, logs, or documentation.

## RealDebrid model

RealDebrid is a resolver, not a worldwide search engine. Search coverage comes
from addon indexes. When an addon returns an `infoHash`, py-stremio can submit
that torrent to RealDebrid and request the selected file. Direct-stream regional
addons bypass RD. Therefore, adding many catalog-only endpoints does not improve
download coverage; adding independent torrent indexes can.

Use only sources and content you are authorized to access.
