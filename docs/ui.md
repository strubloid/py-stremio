# Terminal UI Audit and Direction

Status: core implementation completed; optional full TUI remains future work  
Reviewed: 2026-07-20

## Implementation Status

The core direction in this document is now implemented:

- Rich owns the interactive live download display.
- A plain append-only renderer handles cron, pipes, files, and CI.
- The production download path no longer starts the competing bottom-row control panel.
- Plain quiet output strips ANSI sequences.
- Movie and episode progress share terminal lifecycle events.
- Final downloaded, failed, and cancelled receipts are durable.
- Aggregate UI throughput is based on shared byte deltas over a rolling window.
- Running stream downloads cooperatively check Ctrl+C between chunks and preserve partial files.
- Zero percent is clamped to a 1% limit until a real pause mechanism exists.
- Worker capacity, active attempts, and active transfers use distinct labels.

The optional Textual frontend, true pause/resume, and a single global resizable executor are intentionally not part of this implementation.

## Executive Summary

The downloader has useful progress data, but the terminal presentation is not controlled by one renderer. The progress block, bottom control panel, regular `print()` calls, stderr messages, and exit cleanup all write independently. That is why completed or interrupted runs can leave old rows, duplicate-looking output, cursor movement codes, and status text mixed with download rows.

The recommended next step is to use [Rich](https://rich.readthedocs.io/) for interactive terminal rendering while retaining a small append-only renderer for cron jobs, redirected output, and CI. Rich fits the current callback-driven architecture and can provide concurrent task rows, transfer rates, tables, logs above the live area, terminal-width handling, and reliable display cleanup without converting the application into a full-screen event-loop framework.

[Textual](https://textual.textualize.io/) is not recommended for the first migration. It is a good future option if py-stremio becomes a persistent, full-screen download manager with selectable jobs, configuration screens, searchable logs, and pause/cancel controls. It would be excessive for fixing the current progress display and would still require a separate cron renderer.

Before improving appearance, several metric and lifecycle issues should be corrected so the new UI does not present inaccurate information more attractively:

1. Guarantee a final event for success, failure, and cancellation.
2. Measure aggregate throughput centrally instead of summing stale per-item samples.
3. Distinguish configured worker capacity, active episode attempts, and active HTTP transfers.
4. Define whether 0% speed means paused or unlimited. It currently appears paused in the UI but acts as unlimited in the limiter.
5. Make active downloads cooperatively observe shutdown so Ctrl+C does more than cancel queued work.

## Goals

- Keep the active display compact and readable throughout a run.
- Never allow progress rows, logs, reports, and controls to overwrite each other.
- Leave a short, durable completion summary after a successful run.
- Restore the terminal cleanly after Ctrl+C, errors, and normal completion.
- Show metrics that describe what the program is actually doing.
- Preserve readable plain-text output for `py-stremio-cron`, pipes, files, and CI.
- Keep rendering concerns out of download and addon logic.
- Preserve `.part` files and clearly report interrupted downloads.

## Non-Goals

- A browser UI or remote API.
- Rewriting the downloader around asyncio.
- A full-screen media manager in the first iteration.
- Showing every addon request in the main display.
- Making thread cancellation forceful; Python cannot safely kill a running worker thread.

## Current UI Architecture

The modern download path is:

```text
main.py
  -> AppService
  -> DownloadService
  -> process_season_folder / process_movie_folder
  -> progress callback events
```

Terminal output is spread across several components:

| Concern | Current owner | Behavior |
|---|---|---|
| Per-item progress | `services/progress.py` | Rewrites an ANSI block on TTYs; appends sampled lines elsewhere |
| Bottom controls | `components/download/control_panel.py` | Reserves the last row and moves the cursor with ANSI sequences |
| Worker output | `components/reports/output_writer.py` | Suppresses stdout for selected worker thread IDs |
| Folder results | `services/download.py` | Prints to stderr while progress uses stdout |
| Reports and errors | report/error components | Print independently from the live renderers |
| Exit cleanup | `control_panel.py` | Writes terminal reset and clear sequences from an `atexit` handler |

There is no single owner of cursor position or terminal writes. Local locks protect individual components, but no lock or event queue protects the terminal as a whole.

## Findings

### 1. Two Renderers Compete for the Cursor

`make_progress_printer()` in `services/progress.py` assumes the cursor is directly below its own active rows. It moves upward by the count of previously rendered rows and redraws them.

At the same time, `StatusBar` in `components/download/control_panel.py` moves to the physical bottom line, draws controls, then moves to the row above it. The status bar and progress renderer use different locks. A worker update can therefore reposition the cursor while another component is midway through a redraw.

This can cause:

- Stale rows that were not cleared.
- Rows written at the wrong terminal position.
- Duplicate-looking progress blocks.
- Results or errors appearing inside the active area.
- A confusing final screen after completion or Ctrl+C.

### 2. Terminal Control Runs Outside a Terminal

`create_control_panel()` starts the status bar unconditionally. Its setup, redraw, stop, and global `atexit` cleanup emit cursor and scroll-region sequences without first requiring a TTY.

Consequences include escape codes in cron logs and redirected files. The progress renderer itself checks `isatty()`, but color helpers in progress tables, stage labels, application banners, and reports are not consistently governed by the same capability decision.

Interactive mode should require appropriate input and output terminals. Non-interactive mode must never emit cursor movement codes.

### 3. Completion Is Not Durable

On an `episode_done` event, the TTY renderer removes the row. The append-only renderer also removes internal state but prints no final line. In either mode, the most useful final state may be absent:

- A completed TTY row simply disappears.
- A cron log may end with `waiting for download` even if the episode later succeeded.
- A fast task may finish before the next one-second append interval.
- An exception before `episode_done` can leave a row and active count behind.

Every logical item needs one forced terminal outcome: downloaded, skipped, failed, or cancelled.

### 4. Ctrl+C Cleans the Scheduler Better Than the Download

The cancellation utilities set a global event, cancel queued futures, and call executor shutdown with `wait=False`. This prevents queued work from starting, but a running HTTP/file worker is not forcibly stopped and does not currently check the shutdown event in its chunk loop.

As a result:

- A download may continue writing its `.part` file after the main flow begins exiting.
- Non-daemon executor threads may keep the process alive.
- Addon requests, RealDebrid polling, limiter sleeps, and condition waits may delay shutdown.
- Lifecycle cleanup may not receive a final cancellation event.

The UI library can restore the screen, but it cannot solve worker cancellation. Cooperative checks must be added to long-running operations.

### 5. Displayed Speed Is Approximate and Can Become Stale

Episode progress calculates a real per-item application-level rate from bytes received over the interval between callbacks. This is useful, but noisy and affected by callback timing.

`DownloadService` computes the displayed overall speed by summing the latest rate stored for each item. These samples were measured at different times. A previous positive rate is not replaced when a later event reports zero, and it is removed only by `episode_done`.

The displayed total can therefore overstate current throughput or remain nonzero after a stalled or abnormally terminated transfer.

A better aggregate is:

```text
aggregate bytes received since previous UI sample
-------------------------------------------------
elapsed time since previous UI sample
```

Use a rolling window of roughly 1-3 seconds for stability. Count bytes where stream chunks are actually accepted, not from resumed bytes already present in a `.part` file.

### 6. The Speed Percentage Is a Target, Not Utilization

The status bar shows a percentage of `INTERNET_MAX_SPEED_MBPS`. That maximum may come from configuration, a one-time Cloudflare probe, or a fallback value. The UI does not say which.

At 100%, the limiter uses zero bytes per second to mean no limit. The display `100% of 300 Mbps` can be read as a 300 Mbps cap, but the transfer is actually unrestricted.

There is also a correctness problem at 0%: the controls render it as a red stopped value, but a zero limiter value causes `wait_for()` to return immediately, which means unlimited traffic.

Recommended semantics:

- `Unlimited` for no throttle.
- `Limit: 150 Mbps (50% of measured 300 Mbps)` for an active cap.
- Do not offer 0% until a real pause mechanism exists, or explicitly implement 0% as pause.
- Label the maximum source as measured, configured, or fallback in diagnostics, not necessarily on every row.

### 7. Thread Controls Do Not Fully Resize Running Executors

The UI's thread value updates `workers_ref`, and `DynamicLimit` reads it while admitting future tasks. However:

- The outer executor is created with the initial `max_workers`.
- Each season executor captures a worker count when that season starts.
- Increasing the value cannot add capacity beyond an executor's original maximum.
- Decreasing the value does not stop work already running.
- Addon-search workers are separate from episode workers.
- The bandwidth limiter counts only workers inside actual stream downloads.

The current `Threads` label suggests a stronger live resizing guarantee than the implementation provides. Until scheduling is simplified, label it `Worker limit` and show separately:

- Active episode attempts.
- Active transfers.
- Configured/admission worker limit.

A future scheduler should use one global download executor or another concurrency primitive whose capacity maps directly to the control.

### 8. Movie Progress Has a Different, Incomplete Lifecycle

The movie byte callback uses `total_size`, while the renderer expects `bytes_total`. Movie downloads therefore remain in an indeterminate sizing state even when a total is known. They do not calculate `rate_bps` and do not emit a matching completion event, which can leave the active count and row behind.

Movies and episodes should use the same event contract and lifecycle.

### 9. Output Suppression Hides Messages Instead of Organizing Them

`ThreadFilteringStdout` discards stdout from marked worker threads. It does not cover stderr, logging handlers, subprocesses, or helper-created threads. Valid diagnostics can be lost while other messages still leak into the display.

The long-term fix is structured output routing: workers publish events or log records, and the renderer decides whether to show, group, or retain them. Output should not be silently discarded just to protect cursor layout.

## Library Research

### Comparison

| Library | Multi-download display | Logs with live display | Non-TTY behavior | Integration cost | Assessment |
|---|---|---|---|---|---|
| [Rich](https://rich.readthedocs.io/en/stable/progress.html) | First-class dynamic tasks and custom columns | `Progress.console.print()` and `Live.console.print()` coordinate output | Detects terminal capabilities; a dedicated plain backend can preserve current cron detail | Low to medium | Recommended |
| [Textual](https://textual.textualize.io/) | Excellent widget-based full-screen UI | RichLog/Log widgets | Needs a separate non-TUI path | High | Future full application only |
| [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/progress_bars.html) | Parallel progress supported | `patch_stdout()` | Primarily interactive | Medium to high | Better for advanced prompts than this task |
| [tqdm](https://tqdm.github.io/) | Multiple fixed-position bars | `tqdm.write()` and logging helpers | Mature disable/fallback behavior | Low to medium | Reliable but less flexible than Rich |
| [alive-progress](https://github.com/rsalmei/alive-progress) | Best around one logical animated bar | Hooks print and logging | Good final receipts | Medium | Awkward for many independent episode rows |
| [Enlighten](https://python-enlighten.readthedocs.io/) | Designed for multiple bars | Strong coexistence with stdout/stderr | Disables manager when not a TTY | Low to medium | Credible runner-up |
| [Blessed](https://blessed.readthedocs.io/) | Low-level primitives only | Application-managed | Pipe-aware | Medium | Would retain most custom rendering complexity |

### Why Rich

Rich directly addresses the current weaknesses without requiring a new application architecture:

- A single `Live` owner can render task rows, summary statistics, and controls.
- `Progress` supports dynamic concurrent tasks, known and unknown totals, byte sizes, elapsed time, and transfer speed.
- Custom `ProgressColumn` classes can represent search/resolution stages without putting all state into a hand-built line.
- Messages printed through the same `Console` appear above the live area instead of corrupting it.
- Context-manager or `try/finally` ownership gives one place to stop rendering and restore streams.
- Terminal dimensions, Unicode cell width, color systems, `NO_COLOR`, and non-interactive output are handled more consistently than the current custom ANSI implementation.
- The renderer can be tested with a `Console(file=StringIO())` and fixed width.
- Existing progress callbacks can remain library-neutral.

Rich is not a cancellation system. It also should not be mixed with the existing bottom-row scroll-region renderer or stacked behind the current stdout proxy. Adoption should replace terminal ownership, not add another output layer.

Relevant primary documentation:

- [Rich progress display](https://rich.readthedocs.io/en/stable/progress.html)
- [Rich live display](https://rich.readthedocs.io/en/stable/live.html)
- [Rich console and terminal detection](https://rich.readthedocs.io/en/stable/console.html)
- [Rich concurrent downloader example](https://github.com/Textualize/rich/blob/main/examples/downloader.py)
- [Rich source repository](https://github.com/Textualize/rich)

### Why Not Textual Yet

Textual is the right tool for a different product shape. It would be justified if the application needs:

- A persistent queue with selectable rows.
- Pause, resume, reorder, cancel, and retry actions.
- Configuration forms and addon management screens.
- Searchable or filterable logs.
- Mouse support, keyboard navigation, dialogs, and multiple views.

For the current request, it introduces unnecessary complexity:

- The download pipeline must run under or alongside Textual's event loop.
- Thread events must cross through `post_message()` or `call_from_thread()`.
- Widget lifecycle and application exit must be coordinated with running HTTP threads.
- Cron, redirected output, and report capture still need a separate renderer.
- Existing service tests would need a second application-level test strategy.

Textual can remain a future frontend over the same library-neutral event model proposed below.

## Recommended Architecture

### One Event Model, Two Renderers

Download logic should publish structured events to a UI boundary. It should not call Rich, emit ANSI, or print progress directly.

```text
download/addon workers
        |
        v
    UI event queue
        |
        v
 TerminalPresenter
   |             |
   v             v
RichRenderer   PlainRenderer
(TTY)          (cron/pipe/CI)
```

The presenter is the only owner of task state and output ordering. A queue gives all workers a thread-safe, non-blocking route into the renderer. Rendering can occur on the main thread or one dedicated UI thread.

Suggested event types:

```python
RunStarted
ItemQueued
ItemStageChanged
ItemBytesAdvanced
ItemCompleted
ItemFailed
ItemCancelled
LogMessage
SchedulerStatsChanged
RunCompleted
```

Every item should have a stable task ID independent of its title and retry number. A retry updates the same logical row and increments an attempt field rather than creating an ambiguous second lifecycle.

### Interactive TTY Renderer

Use one Rich `Live` display containing:

1. A compact run header.
2. Active download rows.
3. One summary/status line.
4. A short key-help line only when controls are available.

Do not reserve a physical bottom row or use custom scroll regions. Route notices, errors, and completed-item receipts through the same Rich `Console` so they are printed above the live region safely.

Suggested wide-terminal layout:

```text
Downloads  3 active / 8 remaining                         18.4 MB/s

Title                         Item       Stage        Progress              Speed       ETA
The Example Show              S02E04     downloading  ███████████░  71%     7.8 MB/s    00:42
Another Series                S01E09     searching    18/64 addons          --          --
Example Film                  movie      resolving    stream 3/7            --          --

Limit 150 Mbps (50%)  |  Worker limit 4  |  Transfers 1  |  q cancel
```

On narrow terminals, remove columns in this order:

1. ETA.
2. Detailed addon counts.
3. Byte totals while retaining percentage.
4. Per-row speed if aggregate speed remains visible.
5. Truncate title using terminal cell width.

Avoid showing all T/L/E mini-bars on every row. Human-readable stages such as `searching`, `resolving`, `downloading`, and `validating` are easier to scan. Detailed addon counts can appear in one secondary field or debug view.

### Plain Renderer

Use when stdout is not a TTY, `TERM=dumb`, or an explicit plain mode is selected. It should never animate or emit ANSI.

Recommended policy:

- Print one run header.
- Print stage changes only when meaningful.
- Print byte progress at a controlled interval, such as every 10 seconds or every 10%.
- Always print a final outcome immediately, regardless of rate limiting.
- Print one final summary.

Example:

```text
[download] 8 items queued; workers=4; limit=150 Mbps
[searching] The Example Show S02E04: 18/64 addons
[progress] The Example Show S02E04: 71%, 812 MB/1.1 GB, 7.8 MB/s
[downloaded] The Example Show S02E04: 1.1 GB in 02:14
[cancelled] Another Series S01E09: partial file retained
[summary] downloaded=1 failed=0 cancelled=1 remaining=6
```

This output is both readable by a person and stable enough for log processing.

### Output and Logging

- Create one shared console/presenter at the application boundary.
- Replace direct UI `print()` calls with presenter methods.
- Adapt Python logging to the presenter rather than discarding worker output.
- Keep grouped expected addon failures concise; expose details in debug mode or the final error summary.
- Escape or disable Rich markup for media titles and external text.
- Respect `NO_COLOR`; consider explicit `--color auto|always|never` later.
- Keep stdout for normal output and stderr for fatal startup/argument failures only when no live renderer owns the screen.

## Metric Definitions

The UI should use explicit definitions so labels remain trustworthy.

| Label | Definition |
|---|---|
| Worker limit | Maximum episode/movie attempts admitted by the scheduler |
| Active attempts | Items currently searching, resolving, downloading, or validating |
| Active transfers | HTTP stream downloads currently registered with the bandwidth limiter |
| Throughput | Bytes accepted from active streams over one shared rolling time window |
| Speed limit | Configured throttle cap; `Unlimited` when not capped |
| Progress | Downloaded bytes divided by known response size; indeterminate when size is unknown |
| Remaining | Logical items not yet in a terminal state, not `event.total - event.current` from the last callback |

Per-file and aggregate speed should be smoothed for display only. Raw counters should remain monotonic. Resume bytes must initialize progress but must not be counted as newly transferred throughput.

## Cancellation Contract

The desired Ctrl+C behavior is:

1. First Ctrl+C requests cooperative cancellation.
2. Stop scheduling new work and cancel queued futures.
3. Wake scheduler condition waits and limiter pauses.
4. Active stream loops check cancellation between chunks and close responses.
5. Preserve `.part` files for future resume.
6. Emit one `ItemCancelled` event for every unfinished logical item.
7. Stop the renderer in `finally` and print a concise interruption summary.
8. Exit with status 130 for non-interactive CLI/cron use.

Optional later behavior: a second Ctrl+C can force a faster process exit after terminal cleanup, with a warning that running library calls may not unwind cleanly.

## Proposed Migration

### Phase 0: Correctness Before Styling

- Disable the current control panel unless both input and output support interactivity.
- Make terminal cleanup silent unless terminal mode was actually activated.
- Fix movie progress to use `bytes_total`, calculate rate, and emit a terminal event.
- Emit final item events from `finally` paths for success, failure, and cancellation.
- Clear or age stale rate samples.
- Remove 0% from controls or implement real pause semantics.
- Add shutdown checks to stream reads, addon attempts, RealDebrid polling, limiter waits, and `DynamicLimit` waits.

This phase provides immediate reliability even if the Rich migration is delayed.

### Phase 1: Establish a Stable Event Contract

- Add typed event models or dataclasses in a UI-neutral module.
- Assign stable task IDs to logical movies/episodes.
- Normalize movie and episode lifecycle events.
- Add a thread-safe event queue and central task-state store.
- Track scheduler truth and transferred-byte counters centrally.
- Adapt the existing append-only output as `PlainRenderer`.

### Phase 2: Add Rich TTY Rendering

- Add `rich` as a project dependency with an intentional supported version range.
- Implement `RichRenderer` using one `Live` owner and custom progress columns where needed.
- Route logs, folder outcomes, reports, and grouped errors through its console.
- Remove the custom progress cursor-up implementation from the active path.
- Remove the bottom-row scroll-region implementation from the active path.
- Replace the stdout suppression proxy with structured log routing.

### Phase 3: Make Controls Honest

- Relabel `Threads` as `Worker limit` unless the executor architecture changes.
- Show active attempts and active transfers separately.
- Display `Unlimited` rather than `100%` when there is no cap.
- Implement pause/resume before exposing 0%.
- Consider changing worker/speed controls through explicit commands or a small prompt instead of globally capturing every keypress.
- Persist runtime changes only if users expect them to survive future runs.

### Phase 4: Optional Full TUI

Only after the event and service boundaries are stable, evaluate a separate Textual frontend. It should consume the same events as Rich and should not replace the plain cron renderer.

## Test Plan

### Rendering

- Non-TTY runs contain no ANSI color, cursor, or scroll-region sequences.
- TTY task updates and log messages do not overwrite each other.
- Every item has exactly one durable final outcome.
- Narrow widths degrade columns without wrapping into other rows.
- Unicode titles use terminal cell width correctly.
- Terminal resize does not leave stale rows.
- Media titles containing Rich markup characters render literally.
- `NO_COLOR` is respected.

### Metrics

- Aggregate throughput uses common-window byte deltas and expires to zero when idle.
- Resume initialization does not create an artificial speed spike.
- Active attempts differ correctly from active transfers.
- Remaining count comes from logical task state.
- Speed limit labels match unlimited, capped, and paused semantics.
- Worker-limit changes match the scheduler's actual admitted concurrency.

### Lifecycle and Cancellation

- Success, failure, skipped, exception, and cancellation paths all finalize task state.
- Ctrl+C cancels queued tasks and active chunk loops observe shutdown.
- `.part` files remain resumable after interruption.
- Renderer cleanup runs for normal completion, exceptions, and Ctrl+C.
- No `atexit` terminal bytes are emitted when no interactive renderer started.
- CLI interruption returns the intended exit status.

### Integration

- Concurrent series and movies share one display safely.
- Report and error output appears above the active display.
- Cron output remains readable over a long download.
- Tests use a fixed-width `StringIO` console and do not depend on the developer's terminal.

## Acceptance Criteria

The first implementation should be considered complete when:

- Interactive runs have one renderer and no competing cursor manipulation.
- Ctrl+C restores the terminal and leaves one concise interruption summary.
- Normal completion leaves only durable outcomes and a final report, not old active rows.
- Redirected and cron output contain no ANSI control sequences.
- Movie and episode progress follow the same lifecycle.
- Aggregate throughput falls to zero when transfers stop and is based on shared byte deltas.
- Worker and transfer labels accurately describe different concurrency layers.
- Existing download behavior, resume support, reporting, and error grouping continue to work.

## Decision

Adopt Rich for the interactive terminal frontend, preserve a dedicated plain renderer for automation, and keep both behind a library-neutral event interface. Do not adopt Textual for the initial cleanup. First correct lifecycle, cancellation, speed accounting, movie progress, and worker-label semantics; then replace the competing custom ANSI renderers with one Rich-owned live display.
