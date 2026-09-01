# Download priority list

The "priority list" is a per-folder, per-item memory of the last time a
download **actually started** for an episode or movie. Items in this list
are retried *before* never-attempted items on the next run because, by
definition, they had live seeds the last time we connected.

## Why this exists

The pipeline has two related signals but neither captures what the user
actually feels:

1. **Resume candidates** (`state.in_progress` + `<title>_sNNeNN.mkv.part`
   on disk) — bytes are already on disk; resume is cheap. The
   `setup_season_folder` "resume-first ordering" puts these at the head of
   the queue.
2. **Failure history** (`state.failed_items`) — episodes that exhausted
   `MAX_DOWNLOAD_ATTEMPTS` are skipped.

The gap: an episode that **started** downloading but produced a `.part`
smaller than the validation threshold (e.g. `MIN_COMPLETED_VIDEO_SIZE_MB`)
gets its `.part` deleted and the episode falls back into the missing list
on the next run. The preflight finds nothing, the per-episode search runs
all 54 addons, and we wait 30 seconds before discovering that the same
streams we just had yesterday are still alive — the only thing that
changed is our pipeline asking the wrong question first.

The priority list captures the **third** signal: "we successfully opened
a stream and started receiving bytes for this item". The seeds that
served us yesterday are still the seeds serving us today, and a torrent
that was alive five minutes ago is far more likely to be alive right now
than one we have never queried.

## Rules

### Rule 1 — Mark an item as started only when real bytes flow

The first time `on_bytes(downloaded_bytes, total_bytes)` is invoked with
`downloaded_bytes > 0` for an episode or movie, call
`state.mark_started(item_key, server=...)`. This happens inside
`_do_download_one_episode` / `process_movie_folder` once per item, before
any "real" download state could already be cleared.

What this **does not** count as "started":

- The preflight scan returning addon URLs (the addon may be alive, but
  every individual torrent behind it may be dead).
- `search_and_download` selecting a stream (the stream URL may resolve,
  but the connection may be rejected or stall at zero bytes).
- The HTTP `Range` request being accepted (the server may agree to resume
  bytes it never had).
- `mark_in_progress` being set (this is set *before* the network request
  so a crashed run can be detected — it is not evidence of a live seed).

What this **does** count:

- At least one byte has been written to the `.part` file by
  `download_stream_to_file` for an HTTP stream.
- At least one segment has been downloaded by `HlsDownloader` or
  `HlsFfmpegDownloader`.

### Rule 2 — Persistence shape

Add a top-level `started` field to `.download-state.json`, mirroring the
shape of `in_progress`:

```json
{
  "started": {
    "episode_3": {
      "started_at": "2026-09-01T10:30:00+00:00",
      "server": "https://torrentio.strem.fun/manifest.json",
      "bytes_at_first_arrival": 12345
    },
    "movie_<folder>.mkv": {
      "started_at": "2026-09-01T10:30:00+00:00",
      "server": "...",
      "bytes_at_first_arrival": 12345
    }
  }
}
```

- The series key shape is `episode_N` (no extension), matching
  `in_progress`, `failed_items`, and `preflight_indeterminate`.
- The movie key shape is the `` form, matching the
  `_movie_partial_path(folder_path, config).name` already used for
  movie `in_progress` markers.
- `server` is the addon URL that produced the stream (best effort —
  `None` if we don't know yet, but at minimum `working_urls[0]` from the
  first stream that started).
- `bytes_at_first_arrival` is informational only; the priority logic
  does not depend on it.

### Rule 3 — TTL and pruning

`STARTED_MAX_AGE_SECONDS = 7 * 24 * 60 * 60` (seven days, same window
as `IN_PROGRESS_MAX_AGE_SECONDS` and `FAILED_ITEM_AUTO_RESET_DAYS`).

A `started` entry is pruned by `DownloadState.prune_stale_started()` in
the following situations:

1. Older than the TTL — seeds almost certainly changed.
2. The episode has been removed from `config.available_episodes` — the
   user no longer considers it part of the season.
3. The corresponding final `.mkv` exists on disk — the download
   succeeded at some point and the marker is misleading.

`prune_stale_started()` is called from `setup_season_folder` and
`process_movie_folder` after the `available_episodes` list and disk
state are known.

### Rule 4 — Ordering at queue build time

`setup_season_folder` partitions the missing list into three buckets, in
this order, before preflight runs:

```
[ resume_first ] → [ priority_first ] → [ fresh ]
```

- **`resume_first`** — episodes with a `.part` file on disk. Bytes are
  already on disk, this is the cheapest path. (Existing behaviour, kept
  intact.)
- **`priority_first`** — episodes that are in `state.started` but are
  **not** resume candidates (the `.part` is gone, e.g. validation
  deleted it). These were live seeds recently.
- **`fresh`** — every other missing episode, in their natural order
  (by episode number, or by `available_episodes` ordering).

When concatenating, the missing-list input order is preserved within
each bucket. Resume > Priority > Fresh.

Movie folders have a single target, so the partition reduces to:
resume (`.part` exists) → priority (in `state.started`) → fresh (the
default path).

### Rule 5 — Interaction with the retry budget

`MAX_DOWNLOAD_ATTEMPTS` is the cross-run budget tracked by
`state.failed_items[episode_N].attempt`. A priority entry does **not**
reset or override this counter. If the episode has already exhausted
its budget, it stays out of the missing list regardless of priority.

In other words: priority controls **order**, not **eligibility**.

### Rule 6 — Interaction with `PY_STREMIO_RETRY_FAILED`

When `--retry-failed` (or `PY_STREMIO_RETRY_FAILED=true`) is set, every
episode is treated as fresh — the budget is bypassed. Priority still
applies: previously-started items run first, then never-attempted
items, then everything else.

### Rule 7 — Cleared on success

`apply_result` (success branch) clears both the `in_progress` marker
and the `started` marker for the item. The item is no longer missing,
so a stale priority entry would just be noise.

### Rule 8 — Cleared on episode removal from metadata

`MetadataService._update_folder_metadata` may shrink
`config.available_episodes` (e.g. an episode is removed from the
season's IMDb listing). The next `setup_season_folder` call prunes
`started` entries whose key no longer corresponds to a known episode.

### Rule 9 — Per-folder scope, not cross-folder

The priority list is **per-folder**. Cross-folder ordering is not
attempted because:

- Each folder's preflight is per-folder (different IMDb, different
  season, different language preferences).
- The cost of a "fresh" episode in folder B is independent of what
  happened in folder A.
- The current parallel folder executor already runs everything
  concurrently; reordering folders would not save real wall time.

### Rule 10 — Server hint (best-effort, not enforced)

`state.started[item_key]["server"]` is recorded for diagnostics and for
the *initial* ordering of the per-episode addon query when the cached
servers list is empty. The download path does **not** skip the addon
search based on this hint — the seed may have rotated since the last
attempt and we still need to verify.

## Data flow summary

```
                     ┌───────────────────────────┐
                     │  Episode network stream   │
                     │  produces first byte      │
                     └─────────────┬─────────────┘
                                   │
                                   │ on_bytes(downloaded>0)
                                   ▼
                     ┌───────────────────────────┐
                     │  DownloadState.mark_started│
                     │  (saves to .download-     │
                     │   state.json)             │
                     └─────────────┬─────────────┘
                                   │
                                   │ next run
                                   ▼
                     ┌───────────────────────────┐
                     │  setup_season_folder      │
                     │  reads state.started      │
                     │  partitions missing into  │
                     │  resume > priority > fresh│
                     └───────────────────────────┘
```

## State schema change

| File | Field | Type | Lifetime |
|------|-------|------|----------|
| `.download-state.json` | `started` | `dict[str, dict]` | 7 days TTL, cleared on success / removal |

`load_state` and `save_state` in `py_stremio/components/state/app_state.py`
gain one extra field each. The new field defaults to `{}` for state files
written by older versions, so the change is fully backward-compatible.

## New helpers

| Helper | Location | Purpose |
|--------|----------|---------|
| `DownloadState.mark_started(item_key, server=None, bytes_at_first_arrival=0)` | `app_state.py` | Record that bytes started flowing. One-shot per item per run. |
| `DownloadState.is_started(item_key) -> bool` | `app_state.py` | Test membership. Honours TTL. |
| `DownloadState.clear_started(item_key)` | `app_state.py` | Drop a marker (success / metadata removal). |
| `DownloadState.prune_stale_started(keep_keys=None, folder_path=None, config=None) -> list[str]` | `app_state.py` | TTL + on-disk + metadata-revoked pruning. |
| `_partition_missing_by_priority(missing, priority_episodes)` | `processing.py` | Mirror of `_partition_missing_by_in_progress`. |
| `_record_started_first_byte(task, episode_num, server=None, bytes_count=0)` | `processing.py` | Idempotent guard around `mark_started` + `save_state`. |

## Backward compatibility

- Old state files (without `started`) load with `started={}`. No items
  get priority on the first run after upgrade; subsequent runs build the
  list naturally as items start downloading.
- The new ordering is strictly stronger than the old "resume-first"
  ordering: resume candidates stay at the head, but every previously
  started item that no longer has a `.part` is now hoisted above the
  fresh bucket. No episode that used to run will stop running; episodes
  only run **earlier**.
- The `started` field is read-only from outside the pipeline; the
  settings module does not need a new user-facing knob.
