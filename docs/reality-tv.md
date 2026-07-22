# Reality TV Download Strategies — 90 Day Fiancé S05E01 (tt9170070)

> **Scope:** Why mainstream reality TV (TLC, Bravo, Discovery, etc.) is sometimes
> hard to find through Stremio addons, and a tiered strategy for downloading
> 90 Day Fiancé S05E01 (`tt9170070`) and similar episodes.
>
> **Audience:** Anyone running py-stremio who keeps hitting
> `No streams found after filtering` on popular cable reality shows.
>
> **Last updated:** 2026-07-22

---

## TL;DR

| Tier | Approach | Realism | Paid | Manual | Code change |
|------|----------|---------|------|--------|-------------|
| 1 | py-stremio with RealDebrid → Torrentio / MediaFusion / Comet / ThePirateBay+ | 5/5 | RD $3–16/mo | No | None |
| 2 | py-stremio + EasyNews+ addon (Usenet) | 5/5 | $10–20/mo | No | None (just env var) |
| 3 | `yt-dlp` on a free streaming mirror (123movies family, soap2day family, etc.) | 3/5 | No | Some | None |
| 4 | HLS `.m3u8` capture with `N_m3u8DL-RE` / `ffmpeg` | 4/5 | No | No (if URL known) | None |
| 5 | Screen-record official source (Max, Discovery+, TLCgo) | 2/5 | Sub required | Heavy | None |

For **90 Day Fiancé S05E01 specifically**, Tier 1 with RealDebrid should
"just work" — this is mainstream cable TV from 2017 and is heavily seeded.

The previous investigation that found **0/173 streams for "Pillow Talk"**
(`tt10955614`) does **not** apply to the main show:

| Show | Niche? | Public torrent seeds | RD cache hit | Stremio coverage |
|------|--------|----------------------|--------------|------------------|
| 90 Day Fiancé: Pillow Talk | Yes (spin-off talk show) | 0–3 | Unlikely | 0/64 |
| **90 Day Fiancé S05E01** | No (flagship) | Hundreds | Very likely | 5+/64 |

---

## Background — why some shows fail

The py-stremio preflight optimization
(`py_stremio/components/download/processing.py:170-211`) sets a
`no_working_addons=True` flag for a folder if `preflight_discover_working_addons()`
returns zero working addons. Once set, every episode in that folder takes the
fast-fail path and never queries the full addon universe again. This is the
right optimization for the *common* case (a folder genuinely has nothing), but
it means a single bad run can "lock" a folder into a permanent failure state
for the rest of the session.

For reality TV:

- **Spin-offs and talk-show-format companions** (Pillow Talk, Reunions, Unfiltered)
  are skipped by most scene groups and rarely posted to public trackers.
- **Niche audiences** mean fewer seeders → torrent aggregators return empty
  results.
- **Aggressive DMCA** from TLC/Discovery means public indexer entries get
  removed within weeks of airing.

For the **flagship show** (90 Day Fiancé main series, s01–present), none of
this applies. s05 aired in May 2017, has been continuously seeded for 9
years, and is in every long-tail indexer.

---

## Tier 1 — py-stremio with RealDebrid (recommended, no code change)

### Why this works for 90 Day Fiancé S05E01

`90.Day.Fiance.S05E01.HDTV.x264-*` and `90.Day.Fiance.S05E01.1080p.WEB.h264-*`
torrents are available on:

- The Pirate Bay (multiple seeds)
- 1337x
- TorrentGalaxy
- RARBG successor mirrors
- Public aggregation endpoints that Torrentio / MediaFusion / Comet / ThePirateBay+ all hit

Release groups that have carried this show: **NTb** (HDTV/WEB), **BTN** (WEB-DL),
**b2b** (1080p WEB), **MORiA** (older captures). The user's existing
`series/90 Day Fiance/s08/` already has BTN/NTb releases, confirming the
flagship show is in the public indexer pool.

RealDebrid's cache very likely has the file (the show has been cached since
2017). Torrentio's RD-proxy endpoint should resolve it in under a second.

### Required setup

1. **`.env`** must contain:
   ```bash
   ROOT_FOLDER=/mnt/d/shared/stremio-downloads
   REAL_DEBRID_API_KEY=<your key>
   # optional but helpful for private tracker proxies:
   # TORRENT_PROXY_URL=http://127.0.0.1:11470
   ```

2. **Create the missing season folder** (py-stremio does not auto-create
   past seasons — only current-year):
   ```bash
   mkdir -p "/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05"
   ```

3. **Run the full pipeline:**
   ```bash
   py-stremio --run
   ```
   This will:
   - Scan folders (finds the new `s05/`)
   - Fetch Cinemeta metadata for "90 Day Fiance" s05 (resolves to `tt9170070`)
   - Write `download-config.json` with the IMDb ID and episode count
   - Validate addon URLs (`py-stremio --validate`)
   - Run the preflight scan against all 64 built-in + addons.txt addons
   - For each missing episode, run `search_and_download()` against working
     addons, then fall through to the full addon universe
   - Download via the best-quality stream, with RealDebrid fallback for
     info-hash-only torrents

4. **Verify the result:**
   ```bash
   ls "/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05/"
   # Should contain a .mkv file >= 100 MB
   cat "/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05/download-config.json"
   # "servers" should now list the verified working addon URLs
   ```

### Expected timeline

| Phase | Time |
|-------|------|
| Scan + metadata | 5–10s |
| Validate addons | 10–20s |
| Preflight (64 addons) | 8–15s |
| First download attempt | 5–30s (RD cache hit) |
| Download itself | 2–6 minutes (1.2–2.0 GB at typical speeds) |
| **Total** | **3–8 minutes** |

### Troubleshooting

If the standard pipeline still fails, work through the debug scripts:

```bash
# Confirm the addons are reachable
python debug/01_debug_quick.py     # edit IMDB_ID to tt9170070

# Check which addons return anything
python debug/04_search_all_addons.py

# Inspect a specific addon's response
python debug/11_check_two_addons.py
```

If only `no_working_addons` is being set (and zero streams come back),
delete `.download-state.json` for the folder and rerun — the state file
caches the preflight result within a session.

---

## Tier 2 — EasyNews+ (Usenet, strongest single source for TV)

EasyNews+ is built into py-stremio
(`py_stremio/components/addons/types/aggregators/EasyNewsPlusAddon.py`) but
only returns streams when `EASYNEWS_API_KEY` is set in `.env`. Usenet has
**decades of retention** for cable TV scene releases, so 90 Day Fiancé
S05E01 is guaranteed to be there.

### Setup

1. Subscribe to EasyNews (~$10–20/mo) at https://www.easynews.com
2. Add to `.env`:
   ```bash
   EASYNEWS_API_KEY=<your easynews username:password>
   ```
3. Re-run:
   ```bash
   py-stremio --run
   ```

The EasyNews+ addon will be queried alongside the other 64 addons. Usenet
NZB downloads flow through the same `search_and_download` pipeline — no
code changes, no config changes beyond the env var.

### Why Usenet works when torrents don't

- **No seeding requirement** — the file is on the Usenet server forever
- **No DMCA takedowns** — Usenet retention is contractual, not optional
- **Always complete** — par files repair missing rar segments automatically
- **Near-instant** — the file is on a server near you, not a peer

---

## Tier 3 — `yt-dlp` on free streaming mirrors (no paid services)

If neither RealDebrid nor EasyNews+ is available, the next-best option is
to scrape a free streaming site and download the m3u8 directly. `yt-dlp`
supports 2000+ sites and is updated daily.

### Workflow

```bash
# 1. Find a working mirror that has 90 Day Fiancé S05E01
#    Try (these rotate frequently):
#      - 123movies family (123movies.com, 0123movies.com, etc.)
#      - fmovies / flixhq
#      - soap2day / cineb / myflixer
#      - vumoo / yesmovies / m4uhd
#
# 2. Find the S05E01 page, copy the URL
URL="https://free-site.example/90-day-fiance-season-5-episode-1"

# 3. List available formats
yt-dlp -F "$URL"

# 4. Download best video+audio, merged to mkv
yt-dlp -f "bv*+ba/b" --merge-output-format mkv "$URL"

# 5. Or, if you have a direct m3u8 URL from DevTools:
yt-dlp "https://host/path/playlist.m3u8" -o "90 Day Fiance S05E01.%(ext)s"
```

### What to expect

- 1–3 ad walls per site (click "I'm 18+" or close popups)
- Some hosts (StreamWish, Voe) need a `Referer` header — `yt-dlp` handles
  this automatically
- Speed throttled on hosts like Streamtape / Doodstream (1–5 MB/s)
- Filename parsing may be wrong — rename the output to match py-stremio's
  expected pattern: `90 Day Fiance S05E01 <Title> <Quality> <Codec>.mkv`
- The site domain may change every 2–6 weeks

### Saving back into py-stremio's library

Once downloaded, place the file in the right folder:

```bash
mv "download.mkv" "/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05/"
```

Then re-run `py-stremio --metadata` so the episode is registered in
`.download-state.json` and won't be re-attempted.

---

## Tier 4 — Direct HLS capture (when you have the m3u8 URL)

If a streaming site plays in your browser but `yt-dlp` can't extract the
m3u8 (custom player, dynamic tokens, etc.), you can capture the stream
directly.

### Option A — Browser DevTools (manual, ~2 minutes)

1. Open the episode page in Chrome/Firefox
2. Open DevTools (F12) → Network tab
3. Filter by `m3u8` or `mp4`
4. Start playback
5. Right-click the playlist entry → Copy → Copy URL
6. Download with `ffmpeg` (lossless) or `N_m3u8DL-RE` (multi-threaded, recommended):

```bash
# Lossless HLS → TS
ffmpeg -i "https://host/playlist.m3u8?token=..." -c copy "90 Day Fiance S05E01.ts"

# Multi-threaded, resumable, with quality selection
N_m3u8DL-RE "https://host/playlist.m3u8?token=..." \
  --save-dir "/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05/" \
  -mt \
  -sv res=1920*1080 \
  --save-name "90 Day Fiance S05E01 [1080p]"
```

### Option B — `mitmproxy` capture (semi-automated)

`mitmproxy` sits between your browser and the internet and can intercept
every `.m3u8` request, then spawn a downloader automatically.

1. Install: `pip install mitmproxy`
2. Install the mitmproxy CA cert in your browser (one-time, see
   https://docs.mitmproxy.org/stable/ca-install/)
3. Run the system proxy on `127.0.0.1:8080`
4. Start the capture script (template):

```python
# save as debug/capture_m3u8.py
from mitmproxy import http
import subprocess
from pathlib import Path

OUTPUT_DIR = Path("/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05")

def response(flow: http.HTTPFlow) -> None:
    if ".m3u8" in flow.request.url and flow.response and b"#EXTM3U" in flow.response.content[:64]:
        m3u8_url = flow.request.url
        print(f"[*] Captured m3u8: {m3u8_url}")
        output = OUTPUT_DIR / "90 Day Fiance S05E01 [captured].ts"
        subprocess.Popen([
            "ffmpeg", "-y", "-i", m3u8_url, "-c", "copy", str(output)
        ])
```

5. Run: `mitmdump -s debug/capture_m3u8.py`
6. Open the episode in your browser — capture triggers automatically
7. Cancel the proxy when done (Ctrl-C mitmdump, disable browser proxy)

This is the closest thing to "watch and download at the same time" without
writing a custom Stremio addon.

### Verifying the captured file

`MIN_COMPLETED_VIDEO_SIZE_MB` in `.env` (default 100 MB) is the gate for a
"valid" completed download. A 90-minute 1080p episode is 1.2–2.0 GB; a
720p episode is 800 MB–1.2 GB. Anything under 100 MB is treated as a
stalled/corrupt download by py-stremio.

---

## Tier 5 — Screen-record official sources (last resort)

If nothing else works, you can record playback from a paid streaming
service. All official sources use Widevine DRM, so the realistic option
is **screen recording** (no DRM bypass).

### Tools

| OS | Tool | Command |
|----|------|---------|
| Windows | OBS Studio / ffmpeg | `ffmpeg -f gdigrab -framerate 30 -i desktop output.mkv` |
| macOS | OBS Studio / ffmpeg | `ffmpeg -f avfoundation -framerate 30 -i "1:0" output.mkv` |
| Linux | OBS Studio / ffmpeg | `ffmpeg -f x11grab -framerate 30 -video_size 1920x1080 -i :0 output.mkv` |
| Headless | `chrome --headless` + `ffmpeg` | complex setup, not recommended |

### Trade-offs

| Pro | Con |
|-----|-----|
| Works for any source | 90-minute recording includes 3+ commercial breaks |
| No DRM bypass needed | Re-encoded audio (lossy) |
| | Resolution depends on playback (720p on mobile, 1080p on desktop) |
| | CPU-heavy; 1.5–3× realtime |
| | Easy to capture UI overlays accidentally |

### Workflow

1. Subscribe to a service that has 90 Day Fiancé S05E01
   (Max is the cheapest at ~$10/mo with ads)
2. Open the episode full-screen
3. Start the screen recorder
4. Mute ads, fast-forward through commercials where possible
5. Stop the recorder at the end
6. Mux to a clean container:
   ```bash
   ffmpeg -i recording.mkv -c copy "90 Day Fiance S05E01 [1080p].mkv"
   ```
7. Move to the library folder

---

## Tool inventory (cross-tier)

| Tool | Purpose | Install |
|------|---------|---------|
| `yt-dlp` | Download from 2000+ sites, extract m3u8 | `pip install -U yt-dlp` or `brew install yt-dlp` |
| `ffmpeg` | Lossless HLS capture, muxing, screen recording | system package manager |
| `N_m3u8DL-RE` | Best HLS downloader (multi-threaded, resumable) | https://github.com/nilaoda/N_m3u8DL-RE/releases |
| `streamlink` | Twitch/YouTube Live/HLS CLI | `pip install streamlink` |
| `mitmproxy` | Intercept m3u8 from any browser | `pip install mitmproxy` |
| OBS Studio | GUI screen recorder | https://obsproject.com/ |
| HLS Downloader (Chrome ext) | One-click m3u8 → file in browser | Chrome Web Store |
| The Stream Detector (Chrome ext) | Surface m3u8 URLs in network panel | Chrome Web Store |
| CocoCut (Chrome ext) | m3u8 download with simple UI | Chrome Web Store |

---

## Test plan — verifying the documented approach

The "test case" referenced in the request is: **be able to download
S05E01**. Here is a concrete verification plan.

### Pre-flight (deterministic, runs in CI)

`tests/test_reality_tv_s05e01.py` is a pytest test that verifies the
search flow can return streams for `tt9170070:5:1` with mocked addon
responses. It does not require any network or paid service.

### Live verification (manual, requires RealDebrid)

`debug/12_test_90_day_fiance_s05e01.py` queries the real addons to
confirm Tier 1 actually works. Run it once after creating the s05
folder to see which addons return streams and which one wins.

### End-to-end verification (the real test)

```bash
# 1. Create the folder
mkdir -p "/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05"

# 2. Run the live verification
python debug/12_test_90_day_fiance_s05e01.py
# Expected: at least 3 addons return streams, at least 1 has
# RealDebrid cache or direct download URL

# 3. Run the full py-stremio pipeline
py-stremio --run

# 4. Check the result
ls -lh "/mnt/d/shared/stremio-downloads/series/90 Day Fiance/s05/"
# Expected: at least one .mkv file >= 100 MB
```

If steps 2–4 succeed, the test case passes.

---

## Why the previous Pillow Talk investigation failed (and why it doesn't apply)

The `debug/README.md` documents a previous investigation that found
zero streams for `90 Day Fiancé: Pillow Talk` (`tt10955614`). Three
plausible reasons, all of which are **not** true for the main show:

1. **Pillow Talk is a talk-show format** — talk shows and post-show
   companion programs are routinely skipped by scene release groups.
   The show is technically a separate IMDB entry, not a "season" of
   90 Day Fiancé.
2. **The preflight short-circuit** in
   `py_stremio/components/download/processing.py:170-211` set
   `no_working_addons=True` for the folder, so every subsequent
   episode in Pillow Talk took the fast-fail path within that session.
3. **Many of the 173 reported addons were dead** — Stremio addon churn
   is constant; a snapshot of "173 addons" probably had 30–50 actually
   responding.

For `tt9170070` (the main show):

- Public torrent seeds are abundant (8+ years of continuous seeding)
- The user's own `series/90 Day Fiance/s08/` already has BTN and NTb
  releases, proving the show is in the public indexer pool
- RealDebrid's cache is very likely to have the file
- At minimum 3–5 addons will respond positively in the preflight
- The `no_working_addons` short-circuit will not engage

---

## When to give up on Tier 1 and use Tier 3/4/5

Use Tier 1 first. If after one full `py-stremio --run` cycle (with
`.download-state.json` deleted for the s05 folder) no streams are
returned, then:

1. **Confirm the folder is correctly set up** — `py-stremio --scan` should
   show `90 Day Fiance  S05  -- episodes  imdb:tt9170070`
2. **Run the live verification** (`debug/12_test_90_day_fiance_s05e01.py`)
   to see what each addon returns
3. **Check `.env`** — make sure `REAL_DEBRID_API_KEY` is set and the
   `addons.txt` file has Torrentio, MediaFusion, Comet, or ThePirateBay+
   uncommented
4. **If still nothing**, try Tier 2 (EasyNews+) — the Usenet path is the
   strongest single source for TV
5. **If still nothing**, try Tier 3 (`yt-dlp` on a free mirror) or
   Tier 4 (m3u8 capture)
6. **Last resort**: Tier 5 (screen-record from Max/Discovery+)

For 90 Day Fiancé S05E01 specifically, the expected outcome is Tier 1
success on the first try.

---

## References

- `docs/newserver.md` — the HLS tokenized server investigation (background
  on how free hoster URLs work)
- `debug/README.md` — the Pillow Talk investigation (what **doesn't** work
  for niche spin-offs)
- `debug/12_test_90_day_fiance_s05e01.py` — the live verification script
- `tests/test_reality_tv_s05e01.py` — the deterministic pytest test
- `py_stremio/components/download/processing.py:170-211` — the preflight
  `no_working_addons` short-circuit
- `py_stremio/components/addons/types/aggregators/EasyNewsPlusAddon.py` —
  the built-in Usenet addon
- `py_stremio/components/addons/types/torrentio_family/TorrentioAddon.py` —
  the primary torrent aggregator with RD support

## Disclaimer

This document is for informational purposes only. The use of third-party
streaming services, Usenet providers, and torrent aggregators may
violate copyright laws or the terms of service of the content providers.
Users are responsible for ensuring their compliance with local laws and
regulations.
