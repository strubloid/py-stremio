# Plan: Fix Search Returning Wrong Shows

## Problem

When downloading episodes, the search can return streams from completely different shows
(South Park, a cop show, etc.) instead of the requested show (e.g. One Piece S31).

Observed symptoms:
1. Deleting the last downloaded file and re-running downloads the *wrong* show's episode
2. The wrong content gets written to disk, overwriting the expected file
3. Some addons return results that don't match the requested IMDB ID or show title

## Root Cause Analysis

### Trace A — Stremio ID Flow

```
processing.py: setup_season_folder()
  → load_config() → gets config.title + config.imdb_id
  → SeasonFolderTask(title=config.title, config=config)

processing.py: _do_download_one_episode()
  → search_and_download(
        title=task.title,
        imdb_id=task.config.imdb_id,
        season=task.season,
        episode=episode_num,
        ...
    )

stremio_client.py: search_and_download()
  → _resolve_imdb_id(title, imdb_id, season)
    → If imdb_id is provided and non-None, use it directly
    → If imdb_id is None:
      → For series: get_series_imdb_id(title, season) — Cinemeta search
      → For movies: get_imdb_id(title) — Cinemeta metadata search
  → build_stremio_id(imdb_id, title, season, episode)
    → If imdb_id: f"{imdb_id}:{season}:{episode}"
    → If NO imdb_id: "{title.lower().replace(' ', '.')}:s{season:02d}e{episode:02d}"

addon_search_service.py: query_addon_for_streams()
  → GET {addon_url}/stream/{type_}/{id_}.json
  → The addon interprets id_ however it wants
```

### Root Cause: Title-Based Stremio ID is Unreliable

When `imdb_id` is **None** (e.g. for a new season not indexed by Cinemeta),
the Stremio ID becomes `"one.piece:s31e01"`. Different addons interpret
this differently:

| Addon Type | Behavior |
|------------|----------|
| Torrentio family | Queries by IMDB ID portion; falls back to title search |
| Comet family | Uses title-based heuristic; returns whatever matches |
| Aggregators (MediaFusion, etc.) | May search by title loosely |
| Non-stream addons | Return empty or advisory messages |

Some addons fall back to a title search and return the first result,
which can be a DIFFERENT SHOW entirely.

Even when `imdb_id` IS provided, some addons (especially aggregators)
ignore it and return content based on their own logic.

### Root Cause: No Cross-Validation After Streams Returned

Nowhere in the pipeline do we validate that:
1. The stream's `title` field contains the expected show name
2. The stream's `imdb_id` (if available from addon metadata) matches the target
3. The stream's `filename`/`behaviorHints.filename` matches the show naming pattern

### Root Cause: Server Blacklisting is Reactive, Not Proactive

The `_update_disabled_servers()` mechanism only disables a server AFTER
the user has manually deleted a wrong file AND re-run. This means at least
one wrong download per bad server.

## Investigation Steps

### Step 1: Log Actual Stremio IDs Being Used

Add debug logging in `search_and_download()` to show:
- The effective imdb_id (resolved or from config)
- The Stremio ID being built
- How many streams each addon returns

### Step 2: Identify Which Addons Return Cross-Show Results

Run a controlled test for a show known to have cross-contamination:
- Set up a test for One Piece S31 (or any show)
- Log every addon that returns streams
- Check if any returned stream has a `title` or `filename` that doesn't match One Piece

### Step 3: Examine Server Cache Flow

When a wrong episode is downloaded and the user deletes it:
1. Does `_update_disabled_servers()` fire correctly?
2. Does the miss-verification in `_missing_episodes()` catch it?
3. Is the `bad_servers` path in `_do_download_one_episode` (lines 310-328) working?

### Step 4: Test IMDB ID Resolution for Problem Shows

Specifically test `get_series_imdb_id()` for:
- "One Piece" with season 31
- "One Piece" with season 22
- Compare the returned IMDB ID with the known correct ID (`tt0388629`)

## Planned Fixes

### Fix 1: Validate Streams Against Expected Show Title

**Already partially done** — `_filter_streams_by_target_episode()` now checks
that the stream's combined text contains the title. But this only applies
to streams that PASS the episode-number filter. If the episode numbers
don't match, the stream is rejected anyway.

**Improvement needed**: Move the title check BEFORE the episode check,
and make it a hard requirement when we know the show title.

**File**: `stream_download.py` — `_filter_streams_by_target_episode()`

### Fix 2: IMDB ID Cross-Validation on Streams That Have It

Add a new filter that checks each stream's metadata for an IMDB ID.
The Stremio stream format includes optional fields like `imdb_id` in
the stream object or behaviorHints. Any stream whose `imdb_id` does
not match the expected target ID should be rejected.

**File**: `stream_download.py` — new `_filter_streams_by_imdb_id()`

### Fix 3: Add IMDB ID to StreamInfo Model

The `StreamInfo` dataclass does not currently have an `imdb_id` field.
Add it and populate it from the raw addon response `imdb_id` key.

**File**: `components/addons/models.py`

### Fix 4: Improve Addon Query to Send Both ID Formats

When an IMDB ID is available, the Stremio ID built from it is
`tt0388629:31:1`. Some addons don't understand this format and
return nothing. Instead, try multiple ID formats when the first
fails: first IMDB-based, then title-based as fallback.

**File**: `stremio_client.py` — `_search_single_id()`

### Fix 5: Proactive Server Blacklisting

When a downloaded file is found to be from the wrong show (detected
by filename mismatch, or disk miss-match validation), immediately
blacklist the server that served it instead of waiting for the next
run's `_update_disabled_servers()`.

**File**: `processing.py` — `_do_download_one_episode()` and `apply_result()`

### Fix 6: Failsafe Filename Check After Download

After a download completes, verify that the actual file content matches
the expected show. If the filename doesn't contain the show title, delete
the file and blacklist the server.

**File**: `stream_download.py` — `download_stream_to_file()`

## Tests Required

### Unit Tests

| Test | What It Validates |
|------|-------------------|
| `test_filter_streams_rejects_wrong_imdb_id` | Streams with mismatched IMDB ID are rejected |
| `test_filter_streams_keeps_matching_imdb_id` | Streams with matching IMDB ID pass |
| `test_filter_streams_keeps_stream_without_imdb_id` | Streams without IMDB ID pass (don't block) |
| `test_search_single_id_falls_back_to_title_when_imdb_fails` | When IMDB-based search returns nothing, tries title-based |
| `test_imdb_id_resolution_for_known_show` | `get_series_imdb_id("One Piece", 22)` returns `tt0388629` |
| `test_build_stremio_id_with_imdb` | `build_stremio_id("tt0388629", "One Piece", 31, 1)` → `"tt0388629:31:1"` |
| `test_build_stremio_id_without_imdb` | `build_stremio_id(None, "One Piece", 31, 1)` → `"one.piece:s31e01"` |

### Integration Tests

| Test | What It Validates |
|------|-------------------|
| `test_preflight_discovers_working_addons` | Real addon search for a known IMDB ID returns streams with correct show title |
| `test_episode_download_rejects_wrong_show_stream` | When addons return wrong show's streams, they are filtered out |
| `test_disabled_server_persists_after_wrong_download` | After a wrong download and manual file delete, the server is disabled |
| `test_search_returns_correct_show_for_title_based_id` | Title-based Stremio ID only returns streams containing the show name |

## Implementation Order

1. **Add `imdb_id` field to `StreamInfo`** — low risk, enables all downstream fixes
2. **Add IMDB ID cross-validation** — filters out streams with wrong IMDB ID
3. **Improve title validation** — make title matching a hard requirement when title is known
4. **Add ID format fallback** — when IMDB-based fails, try title-based
5. **Proactive server blacklisting** — catch and disable bad servers early
6. **Post-download filename validation** — last line of defense

## Acceptance Criteria

- [ ] Searching for One Piece S31 no longer returns South Park streams
- [ ] Searching for One Piece S31 no longer returns cop show streams  
- [ ] All streams returned contain either the correct IMDB ID or the show title
- [ ] Servers that consistently return wrong shows are automatically disabled
- [ ] When IMDB ID is available, it's used as the primary search ID
- [ ] When IMDB ID is unavailable, title-based search still works but cross-validates results
- [ ] All existing 350+ tests pass
- [ ] New tests verify cross-show stream rejection
