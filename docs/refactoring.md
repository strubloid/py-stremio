# Refactoring Plan — Make Downloads Actually Work

## Problem Analysis

The current strategy in `docs/world.md` is overengineered. Looking at the actual state:

- The `addons.txt` has **1588 lines** of URLs (with many dead/duplicate)
- The user **cannot download** even episodes that are missing
- The menu has **9 options with nested submenus** — overwhelming
- The "AI discovery" was added but **doesn't actually find new working addons** because pattern-based prediction hits the same 60-70 known hosts
- The preflight optimization **skips per-episode search when preflight finds nothing**, but preflight is what fails

### Root Causes of Download Failures

1. **Preflight can mark ALL addons as "dead"** if they return 0 streams for the test ID. Then per-episode search is skipped. This is the #1 reason downloads fail.
2. **Too many URLs in addons.txt** (1588!) — most are dead, slow validation eats time
3. **The preflight's "indeterminate" state for rate-limit saturation** doesn't always propagate correctly
4. **Per-folder `servers` cache** can be stale (e.g., `filtorrent.baby-beamup.club` is the only cached server but might be dead)
5. **Quality filter may reject valid streams** if release-group names trigger title matching incorrectly
6. **The user has Torrentio working but it gets filtered out** for certain IMDB/title mismatches

### What the User Actually Needs

1. A **simple, focused menu** (4-5 options max)
2. **Downloads that actually work** — when a series is missing episodes, find them
3. **Discover addons as part of "Run"**, not as a separate step
4. **One "AI find" button** for when nothing else works
5. **Visibility** — show what's happening during search/download

---

## Refactored Menu (target)

```
  ╭──────────────────────────────────╮
  │  Py-Stremio Download Manager    │
  ╰──────────────────────────────────╯

  1  ⬇   Download missing episodes/movies
  2  🔍  Update library (scan + metadata)
  3  📦  Addons (validate, find more, save)
  4  ⚙   Settings (debrid, threads, speed)
  5  🚪  Exit
```

**Why this is better:**
- One button does the whole download pipeline (scan → metadata → download)
- "Addons" is one button that internally does validate + find more
- "AI find" lives INSIDE the Addons submenu, behind a single "Find more addons" option
- No nested submenus deeper than 1 level

---

## Refactored Internal Flow (target)

When user presses `1` (Download), this happens in order:

```
1. SCAN folders (1-2 seconds)
2. UPDATE metadata for folders missing it (5-10s)
3. DISCOVER new addons (incremental, O(1) check via index — adds new URLs only)
4. TEST only NEW addons (manifest check, fast, parallel 10x)
5. SAVE discovered working addons to addons.txt
6. DOWNLOAD missing episodes using ALL working addons (not just preflight cache)
7. REPORT results
```

When user presses `3` (Addons), this happens:

```
1. LOAD current addon index
2. TEST untested addons (parallel 10x, fast)
3. SHOW count: working / failed / untested
4. OFFER: "Find more addons" (AI discovery — predicts known patterns)
5. SAVE index
```

---

## What Needs to Change (Steps)

### Step 1: Fix the Preflight Skipping Issue (CRITICAL)

**Problem:** `preflight_discover_working_addons()` returns `PreflightResult(alive=[], dead=[...])` when no addon returns a stream for the test ID. Then `process_season_folder()` sets `no_working_addons=True` and **skips per-episode search**.

**Fix:** Even if preflight returns 0 alive, ALWAYS run per-episode search. The per-episode search uses the actual target IMDb ID + season + episode, which is what matters. Test ID is a smoke test, not a real probe.

**File:** `py_stremio/components/download/processing.py` — `setup_season_folder()` or `process_season_folder()`

**Change:** Remove or relax the `no_working_addons` early-skip. Let the per-episode search always run if preflight is empty.

### Step 2: Reduce the Menu

**File:** `py_stremio/app.py` — `_run_menu()` and `_menu()`

**Change:** Replace 9 options with 4. Remove submenus. The "Addons" button opens a single submenu with at most 4 items (status, validate, find more, back).

### Step 3: Auto-Discovery on Run

**Problem:** Discovery is a separate step the user must remember to run.

**Fix:** When user presses `1` (Download), if the addon file was last validated > 7 days ago OR has > 20% dead URLs, run incremental discovery first.

**File:** `py_stremio/app.py` — `run_pipeline()` and `_run_menu()`

### Step 4: Simpler AI Discovery

**Problem:** Current AI discovery is too broad — predicts 1000+ URLs that mostly don't exist.

**Fix:** AI discovery only checks the **already-known working base hosts** (ElfHosted, baby-beamup.club, vercel.app, onrender.com, koyeb.app, etc.) and only **known addon names** (comet, mediafusion, torrentio, etc.) that we already know work. Don't predict random combinations.

**File:** `py_stremio/components/collect/ai_discovery.py` — `AIDiscovery.predict_all()`

### Step 5: Smart Folder Config Repair

**Problem:** Some folders have stale `servers` cache that points to dead addons.

**Fix:** When starting a download for a folder, verify the cached `servers` URLs are still alive. If dead, remove from cache and re-search.

**File:** `py_stremio/components/download/processing.py` — `setup_season_folder()`

### Step 6: Make the per-episode Search Always Run

**Problem:** When preflight returns 0 working, the per-episode search is skipped, so we never look for actual streams.

**Fix:** Always run `search_all_addons_for_streams()` for each missing episode. The preflight is an optimization for finding which addons to prioritize, not a gate.

**File:** `py_stremio/components/download/processing.py` — `search_and_download()` flow

### Step 7: Visible Progress

**Problem:** User can't tell what's happening — search phase, validation phase, download phase are all opaque.

**Fix:** Print clear phase markers: "Searching 80 addons...", "Found 12 streams for S12E14", "Downloading S12E14 (45MB)...".

**File:** `py_stremio/components/download/processing.py` and `services/progress.py`

---

## Implementation Order

1. **Step 1** (preflight fix) — highest impact, unblocks downloads
2. **Step 6** (per-episode search always) — completes the unblock
3. **Step 2** (reduce menu) — usability
4. **Step 3** (auto-discovery) — convenience
5. **Step 5** (config repair) — robustness
6. **Step 7** (visible progress) — UX
7. **Step 4** (simpler AI) — last, since the current AI does very little

---

## Acceptance Criteria

- [ ] Pressing `1` in the menu downloads missing episodes without any other action
- [ ] If no addons work, the system tries all 80+ built-in addons for each episode
- [ ] Menu has 4 main options, not 9
- [ ] "Find more addons" is one button, not a complex flow
- [ ] User can see "Searching addons...", "Found N streams", "Downloading SxxExx..." in the terminal
- [ ] When `90 Day The Single Life/s02` runs, it finds streams and downloads the 5 missing episodes
- [ ] When `90 day fiance happily ever after/s08` runs, it finds the 1 missing episode

---

## Out of Scope (for this refactor)

- Multi-debrid (Premiumize, AllDebrid) — user only has RD, keep simple
- WebTorrent — not needed with RD
- Custom torrent proxy chains — single proxy is enough
- Health monitoring — nice but not blocking
- AI discovery beyond known host patterns — overengineered, doesn't help

---

*Document version: 1.0*
*Last updated: 2026-08-06*
