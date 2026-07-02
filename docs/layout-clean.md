# Terminal Layout Cleanup Plan

## Current Problems

### 1. The series overview table is too wide and noisy

`_series_completion_overviews()` prints every season of every show as a separate row
in a box-drawing table. For a user with 30+ shows × 10+ seasons, this produces 300+
rows of near-identical "· up to date" text — with every row wrapped in `│ ... │`.

```text
│ South Park                │ s27 │ 0    │ · up to date │ series │
│ South Park                │ s22 │ 0    │ · up to date │ series │
│ South Park                │ s23 │ 0    │ · up to date │ series │
│ South Park                │ s28 │ 0    │ · up to date │ series │
├───────────────────────────────────┼────────┼──────┼──────────────┼────────┤
│ Survivor                  │ s42 │ 0    │ · up to date │ series │
```

The problem: the user has ~30 shows, most complete, and sees ONLY "· up to date"
rows with "0" episode counts — zero useful information per row, infinite noise.

### 2. Two separate inventories printed

The system prints two different summaries:
- A `build_table()` box-drawing table at the start of `download_service.run()`
- A text-based bullet list after the downloads finish (from `report.py`)

Both list the same data. The text list is actually more readable.

### 3. Menu output interleaves with table data

The table rendering doesn't clear the screen first, so menu text and table rows
visually overlap.

### 4. `0` episode counts for completed seasons

Every complete season shows `0` in the episode column. A user reading "South Park s27
0 · up to date" wastes mental energy parsing a number that means nothing.

### 5. The table header columns are ambiguous

`Series │ s## │ 0 │ · up to date │ series │` — is the third column episodes? failures?
The headers scroll off-screen immediately.

---

## Proposed Design

### Replace the per-season table with a compact series-summary view

**Instead of** one row per season:

```
│ South Park                       │ s27 │ 0    │ · up to date │ series │
│ South Park                       │ s22 │ 0    │ · up to date │ series │
│ South Park                       │ s28 │ 0    │ · up to date │ series │
│ Survivor                         │ s42 │ 0    │ · up to date │ series │
│ Survivor                         │ s43 │ 0    │ · up to date │ series │
│ Survivor                         │ s44 │ 0    │ · up to date │ series │
```

**Use one line per series, with a season progress bar:**

```
  ✓ South Park                 │  16 seasons   │   all downloaded
  ✓ Survivor                   │  11 seasons   │   all downloaded
  ✓ Taskmaster                 │   4 seasons   │   all downloaded
  ✓ The Neighborhood            │   8 seasons   │   all downloaded
  ⚠ 90 Day Fiance              │   5 seasons   │   s12: 1 failed
  ⬡ How I met your mother     │   1 season    │   disabled
```

This reduces the output from 50-300 lines to ~30 lines (one per unique show).

### Implementation approach

**Option A — Use `_series_completion_overviews()` output as the one-and-only summary**

Already aggregates by series. The `build_table()` format is the problem — replace it
with a simple line-per-show format.  Remove the text summary from `report.py` when
the library overview is visible.

**Option B — Conditional per-season view**

- If 80%+ of seasons are complete: show series summary only
- If < 80% complete (e.g. actively downloading a show): show per-season breakdown
  for that show only, hidden behind a collapsible header

### Specific improvements

| Current | Proposed | Why |
|---------|----------|-----|
| Box-drawing chars (`╭─┬─╮`, `│`, `├─┼─┤`, `╰─┴─╯`) | Plain text with minimal borders | Box-drawing is the main source of visual noise. Plain text is easier to scan. |
| Every season as a row | One row per series | Users manage shows, not seasons. Collapsing hides noise. |
| `0` for complete episodes | `all` or `✓` or empty | Zero is meaningless noise for complete seasons. |
| `series` type column | Remove entirely | It's always "series" — redundant. |
| `s##` column | Show count: `16 seasons` | Users know what show they're looking at. Total season count is useful context. |
| Both table + text summary printed | Print only the table/summary once | Duplicate data wastes lines. |
| Table printed immediately before download | Print nothing before download unless there are actionable items | The user already decided to download. They don't need to see the full library again. |
| Separator lines between show groups | Remove | They duplicate what white space does. |

### Phase-1: Remove the redundant per-season table entirely

The most impactful change: **skip the table when all seasons are complete.**

```python
def _series_completion_overviews(self, folders):
    """Return a compact overview. Skip when everything is already complete."""
    series = self._aggregate_series(folders)
    if not series:
        return ""
    rows = []
    any_actionable = False
    for item in series:
        if item["total"] == 0:
            continue  # skip disabled/empty
        if item["downloaded"] >= item["total"]:
            rows.append(f"  ✓ {item['title']:<30} │ {item['season_count']:>2} seasons │ all downloaded")
        else:
            any_actionable = True
            pct = int(round(item["downloaded"] / item["total"] * 100))
            rows.append(f"  ⚠ {item['title']:<30} │ {item['season_count']:>2} seasons │ {pct}%")
    if not rows:
        return ""
    if not any_actionable:
        # Everything is complete — show one line and move on
        return f"\n  All {len(series)} series are up to date  ✓\n"
    return "\n".join(rows)
```

### Phase-2: Hide the table when we're about to download

Before the download phase, show the table only if there are actionable items (missing
episodes). Otherwise print nothing:

```python
table = self._series_completion_overviews(folders)
if table:
    print(table)
```

And let the per-folder download output (`⬇ Downloads`) speak for itself.

### Phase-3: Clean up the menu-to-download transition

When the user picks option 1 or 3 from the menu, the current output is:

```
⬇ Downloads
  Threads: 10 · speed: 100%
  starting with 10 thread(s) at 100% speed...
⬇ Downloads
  starting with 10 thread(s) at 100% speed...up to date │ series │
```

Two problems:
1. `⬇ Downloads` prints twice (once in menu, once in download service)
2. The second line gets corrupted by leftover table characters

Fix: always clear any visible table before printing the download header.

### Phase-4: Replace `build_table()` with a simpler ASCII format

Replace the box-drawing table with a minimal two- or three-column tabular format
that uses padding, not Unicode box drawing:

```text
Series                    Episodes   Status
───────────────────────── ───────── ──────────
South Park                16/16     ✓
Survivor                  11/11     ✓
Taskmaster                4/4       ✓
90 Day Fiance             45/48     ⚠ 94%
```

No `╭──┬──╮`, no `│`, no `├──┼──┤`. Just column headers, an underline, and rows.
This is the conventional terminal table format (psql, `column -t`, `pytest --tb`).

### Phase-5: Show actionable failures only

Instead of showing "s12: 1 failed" inline in the library summary (which the user sees
even when they're not downloading), show failures in a dedicated section when there
are any:

```text
───  Action Required  ─────────────────────────────────────

  ⚠  90 Day Fiance s12     1 failed
  ⚠  Survivor s48          3 missing (ep 12, 13, 14)
```

This section appears only below the summary if there are actionable items.

---

## Files that need changes

| File | Change |
|------|--------|
| `services/download.py` — `_series_completion_overviews()` | Replace box-drawing table with compact plain-text per-series summary. Skip printing entirely when everything is complete. |
| `services/download.py` — `run()` | Show the overview before the download header only if there are items to download. |
| `services/progress.py` — `build_table()` | Deprecate or keep for backward compat but stop using it for the library overview. |
| `components/reports/report.py` — `format_terminal_report()` | Don't re-list the entire library again at the end. Just show what was downloaded/failed this run. |
| `py_stremio/api.py` — `run_menu()` | Clean up the transition between menu selection and pipeline output (clear/skip the table area). |

## Optional: collapsible show details

Instead of showing per-season or per-show data all the time, let the menu accept
a selection number to drill into a show:

```
  ⚠  90 Day Fiance              │   5 seasons    │  s12: 1 failed
  ✓  South Park                  │  16 seasons    │  all downloaded

  Press a show number (1-30) for details, or Enter to continue:
```

This is future work — not in Phase 1.
