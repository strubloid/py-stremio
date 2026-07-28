# Issues With Downloading — Investigation Report

> Investigation of two failing episodes on 2026-07-27:
>
> 1. `Rick and Morty S09E10` (just dropped)
> 2. `House of the Dragon S03E06` (Cinemeta still shows TBA)
>
> Both failed inside the same `py-stremio` run with the same error:
> `Preflight found no working addons`. Stremio's own UI shows dozens of
> available streams for the same episode, so the gap is not on the
> network side.

---

## 1. Quick summary

**Root cause is a process-wide rate-limit cap, not bad addons or bad
metadata.**

The Python process spawns a singleton `RateLimiter` that hard-caps every
host at **50 requests per process lifetime**. When the cron run between
**22:54:32 and 22:56:07** processed 10 series folders in parallel
(`DOWNLOAD_THREADS=10`), the cap was exhausted on the popular addons
(torrentio, comet, cin, etc.) before it even got to Rick and Morty and
House of the Dragon. After the cap is hit, every subsequent query to
that host returns an empty stream list. The preflight phase interprets
this as "no addon has usable streams" and aborts the download for the
rest of the run.

The filter logic itself is correct: when I ran the preflight and the
per-episode search manually today, both series returned **10–11
working addons** (torrentio, comet, cinnn, torrentsdb, sooti, yastream,
filtorrent, desiflix, etc.). So Stremio is not the problem — py-stremio
shot itself in the foot.

---

## 2. Evidence

### 2.1 State file — same failure on 10 series in a 2-minute window

`grep -l "Preflight found no working addons" /mnt/d/shared/stremio-downloads/series/*/s*/.download-state.json`

| Series | Season | Episode | Timestamp |
| --- | --- | --- | --- |
| 90 Day Fiance The Other Way | s01 | ep 12 | 2026-07-27 22:54:32 |
| 90 Day Fiance The Other Way | s02 | ep 5 | 2026-07-27 22:54:34 |
| 90 Day Fiance The Other Way | s04 | ep 8 | 2026-07-27 22:54:49 |
| 90 Day Fiance The Other Way | s05 | ep 1 | 2026-07-27 22:54:51 |
| 90 Day Fiance The Other Way | s02 | ep 6 | 2026-07-27 22:55:13 |
| 90 Day The Single Life | s03 | ep 14 | 2026-07-27 22:55:14 |
| One Piece | s23 | ep 16 | 2026-07-27 22:55:37 |
| **House of the Dragon** | **s03** | **ep 6** | **2026-07-27 22:55:32** |
| **Rick and Morty** | **s09** | **ep 10** | **2026-07-27 22:55:50** |
| Temptation Island Italy | s14 | ep 1 | 2026-07-27 22:56:07 |

Ten different series failed in 95 seconds, all with the identical error
and no working-url cache, then the run stopped. This is not content
drift — it is a shared infrastructure problem.

### 2.2 Stremio itself is healthy

For `tt2861424:9:10` (Rick and Morty S09E10) the Stremio UI shows
streams from CIN, Comet, Guindex, ELiTE, TRB, MeGusta, FLUX, EZTV, AFG,
NeoNoir, Knaben, StremThru, and more. The screenshots in the task
confirm the same for House of the Dragon S03E06.

### 2.3 The preflight is fine when run in isolation

Today (2026-07-28), with a fresh process and an empty rate-limit state,
running the same code paths against the same Stremio IDs:

| Series | Preflight result |
| --- | --- |
| `Rick and Morty S09E10` (tt2861424:9:10) | **11 addons alive** — torrentio, comet, cinnn, torrentsdb, sooti, yastream, filtorrent, desiflix, … |
| `House of the Dragon S03E06` (tt11198330:3:6) | **10 addons alive** — torrentio, comet, cinnn, torrentsdb, sooti, yastream, filtorrent, hdhub, … |

The only thing that changed between the failed run and the working one
is the per-process state of the `RateLimiter` singleton.

---

## 3. Where the code goes wrong

### 3.1 The cap is hard-coded and survives forever

`py_stremio/components/addons/rate_limiter.py:36`

```python
_MAX_REQUESTS_PER_HOST = 50  # max requests per host per RateLimiter lifetime
```

```python
with state.lock:
    # Per-session request cap — prevent runaway queries to one host
    if _MAX_REQUESTS_PER_HOST > 0 and state.request_count >= _MAX_REQUESTS_PER_HOST:
        raise RuntimeError(
            f"Rate limit cap reached: {host} — "
            f"{state.request_count} requests (max {_MAX_REQUESTS_PER_HOST})"
        )

    now = time.monotonic()
    ...
    state.request_count += 1
```

Three problems with this:

1. **The cap is 50 per host per Python process.** With 10 download
   threads (`DOWNLOAD_THREADS=10` in `.env`) and a preflight that
   queries all addons (`py_stremio/components/addons/addon_search_service.py:295-335`),
   hitting 50 requests on `torrentio.strem.fun` is realistic after 4–5
   series — well within a single run.
2. **`request_count` never decreases.** It is only incremented; it is
   never decremented or windowed. So once a host is exhausted it stays
   exhausted until the process exits.
3. **The cap is a singleton.** It lives on `RateLimiter._instance` and
   is shared across the whole process — preflight, per-episode search,
   metadata refresh, and the live retry path all share the same
   counter.

### 3.2 The exception is silently swallowed

`py_stremio/components/addons/cloudscraper_client.py:161-183`

```python
with limiter.request(url):
    try:
        resp = _session.get(url, timeout=timeout, allow_redirects=True)
        ...
    except RuntimeError as exc:
        # Per-host request cap reached
        raise CloudscraperError(str(exc)) from exc
```

`addons/addon_search_service.py:312-329`

```python
def _try_one(addon: BaseAddon) -> tuple[str, bool]:
    try:
        streams = addon.get_streams(type_, stremio_id)
        live = _preflight_streams_are_usable(...)
    except Exception:
        live = False   # ← silently treats the cap as "addon dead"
```

The cap raises `RuntimeError`, which is re-wrapped as
`CloudscraperError` by the HTTP client, which is caught and converted
to an empty list by `addons/cloudscraper_client.py:225-232`, which is
caught by `_try_one` and reduced to `live = False`. The user only sees
"Preflight found no working addons", with no hint that the process
silently ran out of per-host budget.

### 3.3 The preflight writes "no working addons" to disk

`py_stremio/components/download/processing.py:188-194`

```python
if discovered:
    servers = discovered
    ...
else:
    if not quiet_output:
        print(f"      No working addons found — skipping repeated per-episode searches")

no_working_addons = len(discovered) == 0
```

`py_stremio/components/download/processing.py:358-380`

```python
# Preflight has already searched every configured addon for this exact
# show/season/episode. With no usable result, another full search for every
# missing episode only multiplies timeouts and rate-limit cooldowns.
skip_full = task.no_working_addons
...
result = search_and_download(
    ...
    working_addons=active_servers,
    ...
    skip_full_search=skip_full,
    ...
)
```

When the preflight returns empty (because the rate limit was exhausted
by an earlier series), `no_working_addons=True` and the per-episode
search is **skipped entirely**. This is the design's "do not multiply
timeouts" optimization, but it backfires: the next time the user runs
py-stremio, the preflight already cached an empty result and is
prevented from ever re-querying.

### 3.4 The state file is poisoned

`/mnt/d/shared/stremio-downloads/series/Rick and Morty/s09/.download-state.json`

```json
"failed_items": {
  "episode_10": {
    "error": "Preflight found no working addons",
    "attempt": 1,
    "timestamp": "2026-07-27T22:55:50.968394"
  }
}
```

`download-config.json` has `servers: []` and `working_addons: []`, so
even on the next run the setup loop sees no cached addons, calls
`preflight_discover_working_addons` again, and trusts its result. With
a fresh process the preflight does work and we get back to a working
state — but if the same cron-style run is repeated, the same 50-request
cap will burn out the same hosts in the same order and the same
failures will recur.

---

## 4. Why House of the Dragon is special (TBA)

The "S3E6 TBA" line in the Stremio screenshot is a Cinemeta metadata
quirk, not a download problem:

`py_stremio/components/stremio/stremio_metadata.py:133-158`

```python
def _is_placeholder_episode(video: dict) -> bool:
    ...
    placeholder_name = name == placeholder_name and not has_external_episode_id
    tba_name = name in {"tba", "tbd"}
    ...
    # For TBA/TBD rows, a release date in the past means the episode has
    # aired even if Cinemeta hasn't updated the name/description/rating yet.
    release_date = _video_release_datetime(video)
    if release_date is not None and release_date <= _current_datetime():
        return False
    return tba_name and not has_description and rating in ("", "0", "0.0")
```

When Cinemeta has not been refreshed, the row for S03E06 is named
`"TBA"` with no overview and no rating. `_is_placeholder_episode` then
returns `True`, `_is_available_episode` returns `False`, and
`available_episodes` ends up as `[1, 2, 3, 4, 5]`.

The user (or the last manual refresh on `2026-07-27T19:25:27`) had
already set:

```json
"episode_count": 6,
"available_episodes": [1, 2, 3, 4, 5, 6],
"current_episode_download": 6
```

so the system *does* know the episode is wanted. The Cinemeta TBA flag
does not block the download by itself — but it also means
`get_series_metadata()` will keep returning `episode_count: 5` on the
next metadata refresh, which will then push `available_episodes` back
to `[1..5]` and remove S03E06 from the "missing" list the moment
anything overwrites the user-edited config.

The "TBA" angle is not why the download failed, but it is a second,
independent bug to fix while we are here.

---

## 5. What is actually wrong in the code

| # | File | Lines | What is wrong |
| --- | --- | --- | --- |
| 1 | `py_stremio/components/addons/rate_limiter.py` | 36, 108–112 | Hard cap of 50 requests per host per process. Once hit, every query to that host raises `RuntimeError` for the rest of the process. There is no windowing, no reset, no per-run budget. |
| 2 | `py_stremio/components/addons/cloudscraper_client.py` | 161–183 | Re-raises the cap as `CloudscraperError` and `addons/cloudscraper_client.py:225-232` returns `[]` on any error. The preflight cannot distinguish "addon is dead" from "we ran out of budget". |
| 3 | `py_stremio/components/addons/addon_search_service.py` | 312–329 | `_try_one` swallows all exceptions and returns `live=False`, so the cap is hidden. |
| 4 | `py_stremio/components/download/processing.py` | 188–194, 358–380 | When preflight returns 0 working addons it sets `no_working_addons=True` and the per-episode search is fully skipped — even if a later run had free budget. |
| 5 | `py_stremio/components/stremio/stremio_metadata.py` | 133–158, 280–297 | Cinemeta "TBA" rows are filtered out unconditionally, so `available_episodes` shrinks back to `[1..5]` on the next metadata refresh and overwrites the user's manual `episode_count: 6`. |
| 6 | `py_stremio/components/download/processing.py` | 543–603 | `_missing_episodes` trusts `config.available_episodes` over the on-disk `current_episode_download`. If the next metadata run shrinks the list, S03E06 silently disappears from the queue. |

---

## 6. Suggested fixes (ordered by impact)

### 6.1 Make the per-host cap windowed, not lifetime

`py_stremio/components/addons/rate_limiter.py`

Replace the permanent counter with a windowed or per-run budget, e.g.
"50 requests per host per 5 minutes". This is what every other Stremio
client does and is the root cause of the bug. Concretely:

- Store the list of request timestamps per host, not just a counter.
- Trim entries older than the window before each check.
- When the cap is hit, sleep until the oldest entry leaves the window
  instead of raising — the caller is already in a download context and
  a 1–2 second wait is preferable to failing the entire season.

### 6.2 Do not hard-fail the preflight on a quiet rate limit

`py_stremio/components/addons/addon_search_service.py:312-329`

When the underlying exception is `CloudscraperError("Rate limit cap
reached: …")`, surface it to the caller as "indeterminate" instead of
"dead". Either:

- Return a 3-state result `(live, indeterminate, dead)` and only treat
  `dead` as "skip the addon for this season", or
- Re-raise the rate-limit error and let `preflight_discover_working_addons`
  retry those addons in a slower second pass.

### 6.3 Cap, do not skip, when preflight is empty

`py_stremio/components/download/processing.py:188-211` and
`py_stremio/components/download/processing.py:358-380`

The current logic flips a single boolean. If the preflight returns 0
working addons, do not commit to `no_working_addons=True` for the rest
of the run. Instead:

- Retry the preflight once after a 3-second backoff.
- If the second pass is still empty, set a per-folder cooldown (e.g.
  30 minutes) and try again on the next run.
- Never carry the empty result over to a *new* process. The
  `download-state.json` should record `attempt: N` and `timestamp`,
  not a permanent "do not try again" flag.

### 6.4 Keep TBA rows out of `available_episodes` only when stale

`py_stremio/components/stremio/stremio_metadata.py:133-158`

The current rule is "TBA row with no description/rating → not
available". That is correct for "the episode has not aired yet" but
incorrect for "Cinemeta has not been updated yet" (the case for S03E06
in the screenshot). Two changes:

- If the user-supplied config has `episode_count: N`, never let
  Cinemeta's `available_episodes` shrink the list below `N`.
- Write the user-confirmed `episode_count` back to the config after the
  metadata refresh so that a later TBA refresh does not overwrite it.

### 6.5 Save preflight results, not the absence of them

`py_stremio/components/download/processing.py:170-194`

Right now an empty preflight result is recorded as a generic failure in
`.download-state.json`. Add a separate state slot, e.g.
`preflight_indeterminate`, that:

- does not count toward `MAX_DOWNLOAD_ATTEMPTS` (currently 5 by
  default), so a transient rate-limit does not consume retry budget;
- expires after a few hours so a fresh run is allowed to retry.

### 6.6 Add an `--no-rate-limit` escape hatch

`py_stremio/components/addons/rate_limiter.py:39`

The `PY_STREMIO_RATE_LIMIT=0` env var already disables the *delay*
between requests. Add a second one (e.g. `PY_STREMIO_RATE_LIMIT_CAP=0`)
that disables the hard cap, and document it in the README. When the
user is debugging "Stremio has streams, py-stremio does not", the first
thing they should be able to try is to bypass the cap.

---

## 7. Quick verification commands

```bash
# 1. Confirm the cap is the actual cause:
cd /home/strubloid/apps/py-stremio
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from py_stremio.components.addons.rate_limiter import get_rate_limiter
lim = get_rate_limiter()
for host, state in lim._hosts.items():
    if state.request_count > 0:
        print(f'{host:40s} requests={state.request_count} cooldown_until={state.cooldown_until:.1f}')
"

# 2. Re-run the preflight with the cap disabled to prove the
#    addons themselves are fine:
PY_STREMIO_RATE_LIMIT=0 PY_STREMIO_RATE_LIMIT_CAP=0 \
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from py_stremio.components.addons.addon_search_service import preflight_discover_working_addons
for label, sid, title, season, episode, imdb in [
    ('Rick and Morty S09E10', 'tt2861424:9:10', 'Rick and Morty', 9, 10, 'tt2861424'),
    ('House of the Dragon S03E06', 'tt11198330:3:6', 'House of the Dragon', 3, 6, 'tt11198330'),
]:
    alive = preflight_discover_working_addons('series', sid,
        title=title, season=season, episode=episode, imdb_id=imdb)
    print(f'{label}: {len(alive)} addons alive')
"

# 3. Look at how many series failed in a single run:
grep -l "Preflight found no working addons" \
    /mnt/d/shared/stremio-downloads/series/*/s*/.download-state.json | wc -l
```

Expected: command (1) shows the hosts with high request counts after a
cron run, command (2) returns 10+ addons per series, command (3)
returns the number of series poisoned by a single bad run.

---

## 8. TL;DR

- **Stremio and the addons are fine.** The screenshots prove it.
- **py-stremio's per-host cap (50) is a singleton that persists for the
  whole process and never resets.** With `DOWNLOAD_THREADS=10` and a
  preflight that queries every addon, that cap is consumed in a single
  run, then every subsequent query silently returns empty.
- **The "Preflight found no working addons" error is a generic catch-all
  for "no addon returned a stream".** It hides the real reason (rate
  limit exhausted) and is persisted in `.download-state.json`, so the
  user can re-run the same day and see the same failure.
- **The TBA flag for House of the Dragon S03E06 is a separate, smaller
  bug** where Cinemeta's stale metadata shrinks `available_episodes`
  back to 5 on every refresh and overwrites the user-set `episode_count:
  6`. It does not cause the download to fail by itself, but it makes
  the next metadata refresh a landmine.
- **Suggested primary fix:** turn the per-host cap into a windowed
  rate budget and never let a preflight empty result mark an episode as
  permanently failed.

---

# Appendix A — `Bleach: Thousand-Year Blood War` (the colon in the title)

> Second investigation: the `:` between "Bleach" and "Thousand-Year Blood
> War" in the season folder for `Bleach: Thousand-Year Blood War/s04/`
> and how it interacts with the rest of the pipeline.

## A.1 What the user is seeing

`/mnt/d/shared/stremio-downloads/series/Bleach Thousand-Year Blood War/s04/`
now contains:

```
.download-state.json
download-config.json
test_colon:file.mkv          ← WSL allows `:` in filenames
New folder/                  ← the user moved the real file here
    Bleach: Thousand-Year Blood War_s04e01.mkv
```

The downloaded file is no longer in the season folder — it was moved
into a `New folder/` subdirectory. py-stremio's scanner uses
`folder.iterdir()`, which is **non-recursive**, so the file is now
invisible to the downloader. That, not the colon, is the reason the
s04 row is currently being treated as "no file, but state says
downloaded".

## A.2 The colon itself: is it a real problem?

### A.2.1 py-stremio handles the colon correctly inside the pipeline

The colon in the show title does **not** break:

- The IMDB lookup (`build_stremio_id` falls back to `tt14986406` because
  the IMDB ID is set, so the colon is never put into the Stremio ID).
- The stream filter (`_normalized_title_text` strips `:` because
  `:` is a non-word character; the title becomes
  `"bleach thousand year blood war"` either way, regardless of whether
  the show title or the release name has a colon).
- The episode-number parser
  (`parse_episode_number('Bleach: Thousand-Year Blood War_s04e01.mkv')`
  → `1` from the `S04E01` token).
- The Stremio stream response (fil-torrent returns titles like
  `✎ Bleach: Thousand-Year Blood War (2022) · S04E01 …` with the colon
  preserved, and 11 out of 12 streams pass `select_quality_streams`).

There is even a regression test for it
(`tests/test_stream_downloads.py:1217 — test_colon_in_library_title_matches_dotted_release_name`).

### A.2.2 Where the colon is a real problem

| # | Where | What goes wrong |
| --- | --- | --- |
| 1 | `py_stremio/components/download/stream_download.py:1005-1019` (`build_media_filename`) | The title is interpolated **as-is** into the filename. No call to `sanitize_filename`. Result: `Bleach: Thousand-Year Blood War_s04e01.mkv` on disk and in the state file. |
| 2 | `py_stremio/components/library/series.py:50` (older code path) | Uses `sanitize_filename(series_title)`, which **replaces `:` with `_`**. So old-style files would be `Bleach_ Thousand-Year Blood War_S04E01_[1080p].mkv`. The two code paths disagree on the same title. |
| 3 | Windows native filesystem | `:` is illegal in NTFS filenames. WSL is permissive (we verified `touch 'test_colon:file.mkv'` works through `/mnt/d`), but if the user ever copies the file to a real Windows share the copy will fail with `ERROR_INVALID_NAME`. |
| 4 | Plex / Jellyfin / Emby / Kodi scanners | Most accept `:` in filenames, but some older versions strip everything after the last `:`. Not a py-stremio bug, but it is a real reason to keep the on-disk name clean. |
| 5 | `_series_overview_key` in `services/download.py:348-351` | `stable_id = config.imdb_id or title.casefold()`. As long as the IMDB ID is set (it is, `tt14986406`) the colon does not affect the overview aggregation. If the IMDB ID were missing, two slightly different title forms would create two separate rows in the completion table. |

### A.2.3 Concrete failure mode in this user's library

Look at the state file for s04:

```json
"items": {
  "Bleach: Thousand-Year Blood War_s04e01.mkv": { … timestamp "2026-07-27T21:43:12.992092" … }
},
"failed_items": {
  "episode_1": { "error": "No downloadable streams found after filtering", "attempt": 1, "timestamp": "2026-07-27T20:53:21.181175" }
}
```

Two problems even before the subfolder move:

1. The successful download is recorded under the **colon-bearing
   filename**. If the user later edits the title in
   `download-config.json` to remove the colon
   (`"title": "Bleach Thousand-Year Blood War"`), the new
   `_generated_episode_filename` will produce
   `Bleach Thousand-Year Blood War_s04e01.mkv` (no colon) and the next
   run will treat the existing file as "no file, redownload" because
   the path comparison is exact-string.
2. The `failed_items["episode_1"]` entry is **never cleared** when the
   same episode subsequently succeeds
   (`py_stremio/components/state/app_state.py:30-49` — `add_download`
   only mutates `self.items`, never `self.failed_items`). So the state
   file permanently carries a "this episode failed" record even though
   the file is on disk and the items record is up to date.

## A.3 The current "not finding things" symptom

When the user runs `py-stremio --download` on s04 today, the scanner
sees:

```
test_colon:file.mkv        (no S##E## token, parse_episode_number -> None)
```

The file is in a subfolder, so it is invisible. With
`episode_count = 1` and zero parseable episodes, the
`detect_existing_season_episodes` fallback returns
`{1}` ("there is one file, assume it is episode 1"), so s04 is
considered complete. That is consistent with the on-disk state and
should not trigger a re-download — but it also masks the fact that
the *real* file is no longer in the place the scanner looks.

## A.4 Fixes (in order of impact for the colon case)

### A.4.1 Sanitise titles in `build_media_filename`

`py_stremio/components/download/stream_download.py:1005-1019`

```python
from py_stremio.utils.media import sanitize_filename

def build_media_filename(title, season=None, episode=None, folder_path=None):
    safe_title = sanitize_filename(title or "")
    if season:
        filename = f"{safe_title}_s{season:02d}e{episode:02d}.mkv"
    else:
        filename = f"{safe_title}.mkv"
    if folder_path:
        return f"{folder_path}/{filename}"
    return filename
```

This makes the new path agree with the old `series.py` path. The
trade-off is that any existing file with a colon in the name will be
treated as a different file on the next run and will be re-downloaded.
For a one-off migration the user can manually `mv` the file to the
sanitised name, or we can add a one-time migration in
`media_file.detect_existing_season_episodes` that tries the colon
form as a fallback.

### A.4.2 Clear `failed_items` on successful download

`py_stremio/components/state/app_state.py:30-49`

```python
def add_download(self, filename, quality, provider, addon_url="", server=""):
    ...
    self.items[filename] = DownloadRecord(...)
    self.total_downloaded += 1
    # Drop any stale failure record for the same logical episode
    legacy_key = Path(filename).stem  # e.g. "Rick and Morty_s09e10"
    for key in list(self.failed_items):
        if key.startswith("episode_") and Path(filename).stem.endswith(key.split("_", 1)[-1]):
            self.failed_items.pop(key, None)
```

Or, more simply, in `processing.py:704-723` (`apply_result` after a
successful download), call `task.state.failed_items.pop("episode_<n>", None)`.

### A.4.3 Surface the "file moved into a subfolder" situation

`py_stremio/components/library/media_file.py:30-34` and
`iter_video_files` are intentionally non-recursive. If the user
*wants* a single season folder that contains subfolders per release
group (the s03 layout), they will lose all visibility. Two options:

- Document loudly: "**Move files out of any subfolder** before running
  py-stremio. Subfolders are ignored."
- Add a debug log at scan time: `if any(p.is_dir() for p in folder.iterdir()): print("  ⚠ Subfolder(s) ignored:", ...)`.

### A.4.4 Pre-flight check before generating the filename

`py_stremio/components/download/processing.py:482-483`

```python
def _generated_episode_filename(folder_path, config, season, episode):
    return Path(build_media_filename(config.title, season, episode, str(folder_path))).name
```

Compare the colon-bearing form with the sanitised form. If the
on-disk file already has the colon form (current state), do not
re-download; if only the sanitised form is on disk, use that. The
simplest way is to call `iter_video_files(folder)` once at the top of
`setup_season_folder` and pass the actual filenames into the missing-
episodes computation, instead of regenerating a filename and hoping
it matches the disk.

## A.5 TL;DR for the colon case

- The colon does **not** break downloads inside py-stremio. There is a
  passing test, the filter normalises it, and the parser handles it.
- The colon **does** leak into the on-disk filename and the state
  record, because `build_media_filename` does not call
  `sanitize_filename`. That is a latent cross-tool / Windows-share
  landmine, and a future title edit will silently orphan the file.
- The actual current "I can't see the file" symptom is that the user
  moved the file into a `New folder/` subdirectory; `iter_video_files`
  is non-recursive, so py-stremio stops seeing it. The colon is a
  co-suspect, not the cause.
- The state file also keeps a stale `failed_items["episode_1"]`
  entry even though the same episode is recorded in `items` as
  successfully downloaded. `add_download` does not clear it.
