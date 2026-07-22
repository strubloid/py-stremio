# Stable Download Speed and Bandwidth Limiting Plan

## Goal

Make the configured internet percentage a predictable aggregate download cap, distribute that cap fairly between active transfers, and show stable, trustworthy speed values in the download table.

For example, if the detected connection is `60 Mbps` and the user selects `50%`:

- Aggregate limit: `30 Mbps`
- Equivalent payload rate: `3.75 MB/s` using decimal units (`30,000,000 / 8`)
- Equivalent display rate: about `3.58 MiB/s` using binary units (`30,000,000 / 8 / 1,048,576`)
- One active transfer may use the whole aggregate limit.
- Two active transfers should normally receive about half each.
- The sum of all active transfers must remain at or below the aggregate limit, except for a small, explicitly bounded startup burst.

The limiter is a ceiling, not a guaranteed target. A slow server, torrent, disk, proxy, or network path may run below the configured rate. The application cannot force a source to provide a constant speed, but it can avoid causing additional oscillation and can report the measured speed accurately.

## Current Findings

### Limiter behavior

`FairBandwidthLimiter` in `py_stremio/components/download/bandwidth_service.py` uses independent per-transfer counters in one-second fixed windows.

The current sequence is:

1. Receive an 8 KB chunk from `httpx`.
2. Add the already-received chunk to the current one-second allowance.
3. Sleep only after the transfer has exceeded its fair share.
4. Reset all counters whenever one second has elapsed.

This design has several problems:

- It permits a full-window burst before applying any delay.
- Sleeping after receipt cannot prevent bytes already buffered by the operating system or `httpx` from arriving quickly.
- Each transfer enforces its own fair share, but `_total_bytes_in_window` is recorded and never used to enforce the aggregate cap.
- The overflow delay is calculated without accounting for elapsed time in the current window.
- Fixed one-second resets create a sawtooth pattern: burst, sleep, reset, burst.
- Adding or removing transfers changes every fair share immediately while their existing window usage remains, which can produce abrupt pauses or bursts.
- Tests check individual sleep calls and calculated shares, but do not simulate elapsed wall-clock time and verify aggregate bytes over several seconds.

### Speed display behavior

Episode and movie speed values in `py_stremio/components/download/processing.py` are calculated from consecutive callbacks:

```text
rate = bytes in the latest 8 KB chunk / time since the previous callback
```

This is an instantaneous rate over a very small sample. Network and application buffering can deliver several callbacks almost immediately and then pause, so the table alternates between unrealistically high and low values.

The overall speed in `py_stremio/services/terminal_ui.py` uses a two-second sample deque, but it has additional presentation issues:

- Per-row speeds and aggregate speed use different measurement methods.
- Rows can retain an old speed while a transfer is stalled or searching.
- `_format_bytes` labels binary divisions as `KB` and `MB`, while the configured limit is decimal `Mbps`; this makes direct comparisons confusing.
- `Transfers` comes from limiter registrations while `active` includes tasks that may still be searching. These are intentionally different concepts, but the table does not explain that distinction.

The supplied output demonstrates this confusion: four active tasks, only two or three actual transfers, changing row values, and a `30 Mbps` limit that is not directly comparable to values shown as `MB/s`.

## Download Manager Model

Established download managers generally combine these concepts:

- One global bandwidth budget, rather than independent limits that can add up incorrectly.
- A token bucket or paced scheduler to allow only a small bounded burst while maintaining a stable long-term rate.
- Work-conserving sharing: an active transfer may borrow unused capacity when another transfer is slow.
- Fair scheduling so one fast source cannot permanently starve other transfers.
- Rolling or exponentially weighted speed measurements for display.
- Separate instantaneous, average, and configured-limit concepts.

The implementation should follow these principles without trying to make every row exactly equal at every moment. Exact equal rates waste bandwidth when one source cannot consume its share. The important guarantees are a strict aggregate ceiling, reasonable fairness over time, and stable measurements.

## Proposed Design

### 1. Replace fixed windows with one shared token bucket

Keep one process-wide limiter shared by every stream download.

State:

- `rate_bytes_per_second`: aggregate configured rate.
- `capacity_bytes`: maximum burst capacity.
- `tokens`: bytes currently available.
- `last_refill_at`: monotonic timestamp.
- One `Condition` protecting limiter state and waking waiting transfers.
- Active transfer IDs and lightweight fairness state.

Behavior:

1. Refill tokens according to exact elapsed monotonic time.
2. Before writing or requesting permission for a chunk, wait until enough tokens are available.
3. Deduct tokens atomically under the shared lock.
4. Never maintain independent token pools whose sum can exceed the global rate.
5. Notify waiters when the rate changes or a transfer unregisters.

Use a small burst capacity, initially `100-250 ms` of the configured rate, rather than a full second. At `3.75 MB/s`, a `200 ms` bucket allows at most about `750 KB` of burst. This absorbs normal scheduling jitter without producing multi-megabyte spikes.

### 2. Add fair, work-conserving scheduling

A global token bucket enforces the cap but does not by itself guarantee fairness. Add round-robin or deficit-round-robin admission between registered transfers.

Requirements:

- Every transfer that is ready to consume data gets regular access to the global bucket.
- Use a small quantum, such as `32-128 KB`, to avoid one transfer consuming the complete bucket repeatedly.
- A slow or stalled transfer does not reserve unused bandwidth.
- One active transfer can consume the full aggregate cap.
- When a second transfer starts, allocation converges smoothly rather than instantly imposing a long penalty on the first transfer.
- When a transfer finishes, its unused capacity becomes available immediately.

Do not enforce a rigid `global rate / active count` per-transfer ceiling. That would leave bandwidth unused whenever one source is slow. Fairness should be measured over a rolling interval while the aggregate token bucket remains authoritative.

### 3. Pace reads more effectively

The current code calls the limiter after `response.iter_bytes()` has yielded a chunk. Move admission as close as practical to consuming the next network chunk.

Options to evaluate during implementation:

1. Keep `iter_bytes()` and acquire budget immediately before writing each yielded chunk. This limits application/disk throughput and long-term socket consumption but still allows some receive buffering.
2. Use a controlled raw iterator/read size so each read consumes only the granted quantum. This gives tighter pacing and should be preferred if `httpx` supports it cleanly without breaking streaming, cancellation, stalls, or resume behavior.

The implementation does not need to control lower-level TCP packet arrival exactly. It must control sustained application consumption and keep observed aggregate throughput within the documented tolerance.

### 4. Use rolling speed measurements

Introduce a thread-safe speed meter shared by the UI or add one meter per task plus one aggregate meter.

Recommended display behavior:

- Per-transfer current speed: rolling average over the last `3-5 seconds`.
- Aggregate current speed: sum actual byte deltas over the same window, not a sum of stale row labels.
- Optional session average: total bytes divided by active download time.
- Collect byte samples continuously, but update visible speed text only once per second. Progress bars may refresh more frequently without changing the speed label.
- Apply an exponentially weighted value to the rolling measurement before display, initially `70%` previous displayed rate and `30%` new measured rate.
- Add display hysteresis: keep the previous label unless the smoothed value changes by at least `0.1 MiB/s` or `5%`, whichever is greater.
- Round MiB/s to one decimal place only after smoothing and hysteresis. Do not repeatedly expose raw callback values such as `3.4, 3.3, 3.4, 3.2`.
- Permit immediate changes for important state transitions: transfer starts, transfer completes, speed reaches zero after a stall, or the user changes the configured limit.
- Remove or decay old samples during stalls so a stopped transfer reaches `0 B/s` instead of retaining an old value.
- Do not calculate display speed from one 8 KB callback.

An exponentially weighted moving average is also acceptable, but a time-based rolling window is easier to test and explain. Keep raw byte accounting separate from display smoothing.

### 5. Clarify units and table data

Update the Rich table to make the configured cap and measured rate directly understandable.

Show the calculated maximum immediately when downloads start, before addon searches or transfers begin:

```text
⬇ Downloads
  Starting with 10 threads at 50% speed
  Connection 60 Mbps  |  Limit 30 Mbps  |  One-download max 3.58 MiB/s
```

`One-download max` means the maximum available to one download when it is the only transfer consuming bandwidth. It is not a per-thread allowance. When several transfers are active, they share the same `3.58 MiB/s` aggregate maximum dynamically. For example, two equally fast transfers may each settle near `1.79 MiB/s`, while one slow transfer allows another to use the unused capacity.

Suggested layout:

```text
Downloads  3 transfers / 4 tasks  Total 3.54 MiB/s  Limit 30 Mbps (50%) [max 3.58 MiB/s]
 Title                         Item      Stage          Progress          Speed       Share
 90 Day Fiance...             S05E23    downloading    42%               1.20 MiB/s   34%
 Michael                      movie     downloading    18%               1.17 MiB/s   33%
 90 Day Fiance...             S05E17    downloading    67%               1.17 MiB/s   33%
 90 Day Fiance...             S05E01    searching      --                --           --
```

Rules:

- Use `MiB/s` and `KiB/s` when dividing by powers of 1024.
- Print `Connection`, `Limit`, and `One-download max` on the startup banner so the user can verify the calculation before downloading starts.
- Describe the value as `One-download max`, not `Max per thread`, because all active transfers share one aggregate cap.
- Always show the theoretical maximum download rate beside the limit: `Limit 30 Mbps (50%) [max 3.58 MiB/s]`.
- Calculate the displayed maximum from the effective limiter value, not independently from UI inputs, so the label verifies the cap that is actually applied.
- If decimal file-rate units are preferred, show `[max 3.75 MB/s]`; never label the binary value `3.58` as `MB/s`.
- Do not show `[max 4.5 MB/s]` for `30 Mbps`: `30 / 8 = 3.75 MB/s`, and `3.75 MB/s / 1.048576 = 3.58 MiB/s`.
- Name searching/downloading counts accurately: a task is not a transfer until it starts receiving a stream body.
- Show `Share` as observed rolling throughput percentage, not as a promised fixed allocation.
- Show `--` for searching, resolving, waiting, and unavailable speed.
- Keep a single stable Rich Live table; addon-search messages should be routed through the UI so they do not corrupt or interleave with the table.

### 6. Validate configured connection speed

The percentage is only meaningful if `INTERNET_MAX_SPEED_MBPS` is correct.

- Display the detected/configured maximum at startup.
- Clearly distinguish `Connection: 60 Mbps`, `Selected: 50%`, and `Limit: 30 Mbps (50%) [max 3.58 MiB/s]`.
- Allow the user to override an inaccurate automatic probe.
- Do not continuously adjust the cap from live download speed; slow third-party servers are not a reliable connection-speed test.
- Document that ISP speed tests use decimal Mbps while file-transfer displays commonly use binary MiB/s.

## Implementation Phases

### Phase 1: Reproduce and measure

- Add a deterministic fake clock and fake sleeper test harness.
- Simulate one, two, and four concurrent consumers for at least ten virtual seconds.
- Add instrumentation for granted bytes, actual written bytes, active transfers, and configured aggregate rate.
- Confirm the current implementation can exceed or oscillate around the intended cap.
- Capture a baseline from a local HTTP server so third-party source variability does not affect results.

### Phase 2: Implement the aggregate token bucket

- Replace `FairBandwidthLimiter` fixed-window counters with elapsed-time token refill.
- Preserve the public integration points only where they remain useful: `register_thread`, `unregister_thread`, `wait_for`, `update_total_limit`, and active transfer count.
- Use a condition wait rather than sleeping outside limiter coordination.
- Handle unlimited mode explicitly without division by zero.
- Ensure cancellation can interrupt limiter waits promptly.
- Apply runtime percentage changes without resetting to a large burst.

### Phase 3: Add fairness

- Introduce round-robin or deficit-round-robin grants for active transfer IDs.
- Make the quantum configurable internally and choose a default through tests.
- Verify work-conserving behavior with one slow and one fast simulated consumer.
- Verify registration and unregistration do not produce a large transient overshoot.

### Phase 4: Correct speed accounting

- Move speed measurement into reusable time-window meters.
- Feed meters from actual downloaded-byte deltas.
- Use one aggregate meter and one meter per active item.
- Remove the callback-to-callback `delta / elapsed` calculations from series and movie processing.
- Define how resumed bytes are excluded from current-session speed.
- Reset a meter when a source attempt restarts from zero, but preserve correct task identity in the UI.

### Phase 5: Improve the table

- Render tasks and active transfers as separate counts.
- Show the aggregate rolling speed beside the equivalent `MiB/s` limit.
- Add observed share for active transfers.
- Correct binary unit labels.
- Route search status through the Rich Live owner to stop terminal interleaving.
- Keep equivalent concise fields in plain/cron output.

### Phase 6: Integration and soak testing

- Run local-server tests with deterministic payloads and multiple concurrent downloads.
- Test sources with fast, slow, bursty, and stalled responses.
- Test dynamic transitions: one to four transfers, four to one, `50%` to `25%`, and limited to unlimited.
- Test resume, cancellation, invalid-video handling, and retry paths.
- Run the deterministic project test suite after focused bandwidth and UI tests.
- Perform a real download soak test, recording aggregate bytes every second for at least five minutes.

## Acceptance Criteria

At a configured `30 Mbps` (`3,750,000 B/s`) aggregate limit:

- After startup warm-up, total bytes written over any rolling 10-second interval do not exceed the configured budget by more than the documented bucket capacity and `2%` scheduling tolerance.
- No one-second interval exceeds the rate by more than the configured burst capacity plus one read quantum.
- One fast transfer reaches at least `95%` of the configured cap when disk and source are fast enough.
- Two equally fast transfers each average between `45%` and `55%` of aggregate throughput over a 10-second interval.
- Four equally fast transfers each average between `20%` and `30%` over a 20-second interval.
- If one of two sources can consume only `10%` of the cap, the other may use the remaining capacity; aggregate utilization remains at least `95%` when possible.
- Starting or finishing a transfer does not create a multi-second stop or an unbounded burst.
- Displayed aggregate speed uses the same byte events as limiter verification and settles near `3.58 MiB/s`, not `6 MB/s`, for a saturated `30 Mbps` limit.
- The table always displays the effective theoretical maximum derived from the limiter, for example `Limit 30 Mbps (50%) [max 3.58 MiB/s]`.
- Before any search begins, the startup banner shows `One-download max 3.58 MiB/s` for a `30 Mbps` aggregate cap.
- Per-row speed does not jump based on individual 8 KB callback timing and decays to zero during a stall.
- During a steady local-server transfer, each visible speed label changes at most once per second and does not alternate across a rounding boundary unless the change exceeds the display hysteresis threshold.
- `Transfers` equals the number of streams currently consuming download data, while searching tasks are shown separately.
- Existing download resume, cancellation, minimum-size validation, and RealDebrid fallback behavior remain intact.

## Test Matrix

| Scenario | Expected result |
|---|---|
| One fast local stream at 50% | Uses nearly the complete aggregate cap |
| Two fast local streams | Aggregate stays capped; shares converge near equal |
| Four fast local streams | Aggregate stays capped; no starvation |
| One fast and one slow stream | Fast stream borrows unused capacity |
| Transfer starts mid-window | No full-window burst or long pause |
| Transfer finishes mid-window | Remaining transfers receive capacity promptly |
| Runtime limit decreases | New lower rate applies smoothly without reset burst |
| Runtime limit increases | Throughput rises promptly without corrupting accounting |
| Unlimited mode | Limiter adds no intentional delay |
| Resumed `.part` file | Existing bytes do not inflate current speed |
| Source retry starts at zero | Meter resets cleanly and does not report a negative delta |
| Source stalls | Row speed decays to zero and cancellation remains responsive |
| Non-TTY output | Stable periodic aggregate and per-item values without flooding |

## Files Expected to Change

- `py_stremio/components/download/bandwidth_service.py`: aggregate token bucket and fair scheduling.
- `py_stremio/components/download/stream_download.py`: paced consumption and cancellation-aware waits.
- `py_stremio/components/download/processing.py`: replace instantaneous per-callback speed calculations.
- `py_stremio/services/terminal_ui.py`: rolling meters, unit labels, and clearer table.
- `tests/test_bandwidth.py`: deterministic sustained-rate, burst, fairness, and dynamic-limit tests.
- Terminal UI and download processing tests: rolling speed, stale-rate decay, resume, and count semantics.

## Risks and Constraints

- Python thread scheduling and operating-system socket buffers prevent packet-level precision. Acceptance should measure sustained application bytes with a small bounded tolerance.
- Very small chunks increase lock and wake-up overhead; very large chunks increase burst size. The scheduling quantum must balance both.
- Strict equal per-transfer caps can reduce total throughput when sources differ. The scheduler must remain work-conserving.
- UI smoothing introduces a short delay before displayed speed changes. A `3-5 second` window is intentionally stable but should still decay promptly during stalls.
- Third-party Stremio and RealDebrid sources are unsuitable for deterministic limiter tests. Use a local controlled HTTP server for correctness tests and real sources only for soak validation.
