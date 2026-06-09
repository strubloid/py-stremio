# Debug Scripts for py-stremio

This directory contains diagnostic scripts used during the investigation of addon availability for "90 Day Fiancé: Pillow Talk" S33E05 (IMDb: tt10955614).

## Scripts Overview

### 01_debug_quick.py
Quick test of Torrentio addon with RealDebrid key.
- Tests direct API call to Torrentio
- Shows number of streams returned
- **Result**: Zero streams found

### 02_debug_all_addons.py
Test all configured addon servers from download-config.json.
- Tests 8 addon URLs from the show's config
- Shows status codes and stream counts
- **Result**: 7 advisory messages, 1 external URL (not downloadable)

### 03_debug_vidfast.py
Inspect VidFast stream details to determine stream type.
- Analyzes stream object structure
- Identifies `url`, `infoHash`, `externalUrl`, `ytId` fields
- **Result**: VidFast returns `externalUrl` type (browser redirect, not downloadable)

### 04_search_all_addons.py
Test all built-in and addons.txt addons using py-stremio's addon factory.
- Loads addon manager (built-in + file)
- Tests all addons for the target episode
- Shows which addons return streams
- **Result**: Zero streams from 144 addons

### 05_quick_check_season32.py
Test Season 32 Episode 1 on major aggregators.
- Tests older season to see if torrents exist
- Uses Torrentio, MediaFusion, ThePirateBay+
- **Result**: Zero streams even for older Season 32

### 06_verify_imdb.py
Verify IMDb metadata from Cinemeta API.
- Confirms IMDb ID is correct
- Shows total episodes (556), seasons (35)
- Verifies S33E05 exists in metadata
- **Result**: Metadata is correct, episode exists

### 07_test_direct_streaming.py
Test 10 non-torrent/direct streaming addons.
- Tests direct streaming services (not torrent aggregators)
- Checks VidFast, Plexio, EasyNews+, Premiumize, etc.
- **Result**: All fail (timeouts, 404s, advisory messages)

### 08_test_new_addons.py
Test all 144+ addons after running `--discover`.
- Tests after addon discovery expanded addons.txt
- Shows progress every 10 addons
- Times the full search
- **Result**: Still zero streams after adding 29 new addons

### 09_check_loaded_addons.py
Show exactly which addons are loaded (built-in vs file).
- Lists all loaded addons by category
- Shows categorization (Torrentio Family, Comet Family, etc.)
- **Result**: 144 addons loaded correctly

### 10_test_stream_addons.py
Filter and test only stream-providing addons.
- Excludes subtitle/catalog/metadata addons
- Tests only addons that should provide video streams
- **Result**: CometNet and Jackettio return "streams"

### 11_check_two_addons.py
Inspect actual stream content from CometNet and Jackettio.
- Shows full JSON structure of returned streams
- Analyzes stream type (url/infoHash/externalUrl)
- Detects advisory keywords (configure/setup/debrid)
- **Result**: Both return advisory messages, not real video

## Running the Scripts

All scripts can be run from the project root:

```bash
# Simple HTTP tests (no imports)
python debug/01_debug_quick.py
python debug/02_debug_all_addons.py
python debug/03_debug_vidfast.py
python debug/06_verify_imdb.py
python debug/07_test_direct_streaming.py

# Tests using py-stremio imports (requires venv)
source .venv/bin/activate
python debug/04_search_all_addons.py
python debug/05_quick_check_season32.py
python debug/08_test_new_addons.py
python debug/09_check_loaded_addons.py
python debug/10_test_stream_addons.py
python debug/11_check_two_addons.py
```

## Key Findings

1. **Zero downloadable streams exist** for this show across all 173 tested addons
2. **Addon loading works correctly**: 54 built-in + 90 from file = 144 total
3. **Advisory messages** from CometNet/Jackettio are correctly filtered out
4. **VidFast** has the episode but as `externalUrl` (browser redirect, not downloadable)
5. **IMDb metadata** is correct (tt10955614, 556 episodes, 35 seasons)
6. **Even Season 32** (older) has zero torrents available

## Investigation Reports

Full investigation reports are available in the project root:
- `INVESTIGATION_REPORT.md` - Initial findings
- `90_DAY_FIANCE_INVESTIGATION.md` - Comprehensive testing summary
- `FINAL_REPORT.md` - Final exhaustive search with alternatives
- `ADDON_LOADING_ANALYSIS.md` - Addon loading behavior documentation

## Conclusion

The inability to download this episode is **not a py-stremio bug**. It's a content availability issue:
- Reality TV spin-offs don't get uploaded to public torrent sites
- TLC/Discovery DMCAs aggressively
- No scene release groups track this show
- Niche audience (spin-off of spin-off)

**Alternatives**: Usenet (with Sonarr), Discovery+ subscription, or private trackers (BTN, MoreThanTV).
