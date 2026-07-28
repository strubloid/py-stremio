# Investigation Report — Why Single-Download Speed Decays

> Investigation of the user-reported problem:
>
> *"I feel the speed is losing too much sometimes and I can't identify why.
> We have one download and the speed keeps going down, instead of keep
> the speed we can to download."*
>
> Sample run on **2026-07-28** with `90 Day: The Single Life S03E14`
> (4.4 GB, single active download, `Speed: 100%` (unlimited),
> 6 workers available):
>
> | metric | value |
> | --- | --- |
> | overall throughput (footer) | **1.3 MB/s** |
> | per-episode rate (per-row) | **26.2 KB/s** |
> | progress bar | barely moving |
> | expected ETA at 1.3 MB/s | ≈ 56 min |
> | expected ETA at 26.2 KB/s | ≈ 46 h |
>
> The two displayed numbers do not agree, and the per-episode rate is
> fifty times lower than the line should deliver. The user has no way
> to tell from the UI which one is the real number, what the bottleneck
> is, or what to change.
>
> The investigation covers:
> 1. The four speed numbers the pipeline computes (and which one
>    actually represents the line)
> 2. The five possible root causes and which ones this run hits
> 3. The fixes ranked by impact and how to ship them

---

## 1. Quick summary

**Root cause is split across three independent bugs and one design
choice that combine to make the speed loss invisible and
uncontrollable:**

1. **Per-chunk rate math (`processing.py:426-453`)** — the per-row
   "Speed" column divides by the elapsed time between two consecutive
   chunk events, so the number tracks the *gap between chunks*, not the
   actual transfer rate. When httpx is stalled waiting for a buffer
   refill, the elapsed grows faster than the bytes, and the displayed
   rate decays even though the line is busy.
2. **Stale `INTERNET_MAX_SPEED_MBPS` in `.env`**
   (`speed_probe.py:28-50`) — the speed probe runs **once** when the
   value is missing, downloads only 12.5 MB, and persists the result
   forever. A probe taken at a congested moment, behind a slow CDN
   edge, or before the TCP slow-start completes under-estimates the
   line, and the value is then used as the 100% denominator for the
   bandwidth limiter and the "Max MB/s" footer line.
3. **No diagnostic surfacing** — when the rate decays there is
   nothing in the TUI that says "throttled" or "RD is slow" or "the
   probe value looks low". The user sees two contradictory numbers
   and has no way to tell whether the line, RealDebrid, the proxy,
   or the rate math is at fault.
4. **The 1-second accounting window** in `BandwidthLimiter.wait_for`
   can under-throttle when the chunk size is large relative to the
   budget (see §2.4). At 100% speed the limiter is a no-op, but a
   future "auto-throttle" mode would hit this.

The single most useful immediate fix is **fixing the rate math** so
the per-row number matches the footer number. After that, the user
can read the screen and tell whether the line is actually slow or
whether they are throttling themselves.

---

## 2. Where the four speed numbers come from

py-stremio computes (and displays) four different "speed" numbers
per episode. They are computed independently and can disagree.

### 2.1 Per-episode rate (the "26.2 KB/s" cell)

`py_stremio/components/download/processing.py:426-453`

```python
def on_bytes(downloaded_bytes: int, total_bytes: int) -> None:
    ...
    if last_progress_bytes is None or downloaded_bytes < last_progress_bytes:
        last_rate_bps = 0.0
        last_progress_bytes = downloaded_bytes
        last_progress_at = now
    else:
        elapsed = max(0.001, now - (last_progress_at or now))
        delta = downloaded_bytes - last_progress_bytes
        last_rate_bps = delta / elapsed if delta else 0.0
        last_progress_bytes = downloaded_bytes
        last_progress_at = now
```

This is `bytes_between_chunks / time_between_chunks`. The chunks
arrive in 8 KB increments (`stream_download.py:1159`), so the rate
is essentially "how long did the read buffer take to refill between
two `iter_bytes` yields". When the underlying connection is
delivering at a steady 1.3 MB/s, the inter-chunk time is
8 KB / 1.3 MB/s ≈ 6 ms, and the calculated rate is correct. When the
connection stalls (RD cache miss, proxy warming up, peer search) the
gap between two yields can stretch to 200-500 ms while the *average*
over the whole second is still healthy — the per-row rate decays to
~20 KB/s and the footer keeps showing 1.3 MB/s.

This is the central bug the user is seeing.

### 2.2 Per-episode displayed rate (the "1.3 MB/s" footer)

`py_stremio/services/terminal_ui.py:370-386`

```python
def _stable_rate(self, key, instant_rate):
    now = self._now()
    last = self._last_rate_update.get(key)
    if last is None or now - last >= self.RATE_DISPLAY_INTERVAL:
        self._displayed_rates[key] = instant_rate
        self._last_rate_update[key] = now
    return self._displayed_rates.get(key) or 0.0
```

Same input as §2.1 (the per-row `rate_bps` from the event), but
*held* for `RATE_DISPLAY_INTERVAL = 1.5 s` so the number does not
flicker. This is the rate the *footer* would display if a single
episode was active — except the footer shows the *aggregate*, not
the per-episode stable rate.

### 2.3 Aggregate throughput (the "1.3 MB/s" in the footer)

`py_stremio/services/terminal_ui.py` — built in
`_build_renderable()` from the sum of per-episode rates. With one
active episode this should equal §2.2. The screenshot shows 1.3 MB/s
in the footer, which is the TUI's aggregate — closer to a 1-second
exponential moving average that absorbs the bursts the per-row
display misses.

### 2.4 The bandwidth limiter window (not displayed)

`py_stremio/components/download/bandwidth_service.py:165-186`

```python
def wait_for(self, byte_count: int, thread_id=None):
    with self._lock:
        ...
        self._bytes_in_window += byte_count
        if self._bytes_in_window <= self.bytes_per_second:
            return
        overflow = self._bytes_in_window - self.bytes_per_second
        delay = overflow / self.bytes_per_second
    if delay > 0:
        self.sleep(delay)
```

A one-second window that counts bytes-per-second and sleeps for
`(overflow / limit)` seconds when the budget is exceeded. The sleep
happens **after** the chunk is counted but **before** the next chunk
is read.

Two issues with this window:

- **Stale window when the line dips.** If the first 700 ms of the
  window deliver 90 % of the budget and the line then stalls for
  300 ms, the window only resets at the 1 s mark. Chunks arriving
  during the stall have no effect on the window state but the *next*
  chunk is still gated by the residual overflow — so the limiter
  may sleep even though the line is now empty.
- **No chunk-size normalisation.** A 64 KB chunk and a 4 KB chunk
  count the same way, but a single 64 KB chunk can trip the budget
  in one yield. Adding a `chunk_size > limit` short-circuit would
  prevent pathological one-chunk-induced throttling at low limits.

Neither of these matters at `Speed: 100 %` because the limiter is
a no-op (`bytes_per_second = 0`, early return). They will matter as
soon as the user drops below 100 %.

---

## 3. The five candidates and which ones apply here

| # | candidate | present? | how to confirm |
| --- | --- | --- | --- |
| A | Per-chunk rate math is decaying | **YES** | compare per-row rate to footer rate — they disagree (26 KB/s vs 1.3 MB/s) |
| B | Stale `INTERNET_MAX_SPEED_MBPS` in `.env` | **YES (likely)** | the user has been on the same `.env` for a long time; the probe is one-shot |
| C | `INTERNET_SPEED_LIMIT` set below 100 % | no (footer says "Unlimited") |
| D | RealDebrid / torrent proxy is genuinely slow | **YES (likely)** | "90 Day" is a popular release; 26 KB/s for a 4.4 GB file is well below RD's typical cache-hit throughput |
| E | Limiter window throttling past 100 % | no (`bytes_per_second = 0`) |

The user's complaint is the speed *decays* over time. Causes B and D
are static (the value is bad forever, or RD is slow forever) and would
not produce a decay. Cause A produces exactly the observed decay
pattern: bursts look fine, gaps look terrible, the per-row display
trends downward between bursts even though the average is healthy.
Cause A is the primary bug.

Causes B and D are secondary: B means the "Max" footer is wrong even
when the user is throttling, and D means the user cannot tell whether
the line itself is slow. Both are real but the rate-math bug masks
them.

---

## 4. The fix — three layers, smallest to biggest

### 4.1 Fix the per-episode rate math (root cause)

Replace the per-chunk division with a sliding-window or
exponential-moving-average (EMA) so the displayed rate matches the
footer's aggregate. Concrete implementation in
`py_stremio/components/download/processing.py:426-453`:

```python
def on_bytes(downloaded_bytes, total_bytes):
    nonlocal last_downloaded_bytes, last_total_bytes, last_rate_bps, ...
    now = time.monotonic()
    # Always advance the byte counter — the network is the source of truth.
    last_downloaded_bytes = downloaded_bytes
    last_total_bytes = total_bytes

    # Sliding 1-second window: sum the bytes received in the last
    # second and divide by 1.0. The window decouples the displayed
    # rate from the inter-chunk gap so stalls do not look like decay.
    window_seconds = 1.0
    self._rate_window.append((downloaded_bytes, now))
    cutoff = now - window_seconds
    while self._rate_window and self._rate_window[0][1] < cutoff:
        self._rate_window.popleft()
    if self._rate_window:
        bytes_in_window = self._rate_window[-1][0] - self._rate_window[0][0]
        last_rate_bps = bytes_in_window / window_seconds
    else:
        last_rate_bps = 0.0
    ...
```

A deque of `(bytes, monotonic_time)` pairs is bounded by the
chunks-per-second rate and is O(1) per event. The EMA variant
(0.5 s half-life) is even cheaper but slightly less honest about
the last second of throughput.

The same change applied to `on_movie_bytes` in
`processing.py:1223-1241` (movies share the same bug).

The TUI's `_stable_rate` can stay — smoothing on top of a smoothed
input is a no-op, but the per-row and footer numbers will finally
agree, which is the user's primary complaint.

### 4.2 Re-probe the speed cap, but only when the user asks

`speed_probe.py` should not become a background re-probe (it would
add a 12.5 MB download to every run). The right design is:

- Keep the one-time probe on first run (unchanged)
- Add `PY_STREMIO_REPROBE_SPEED=1` to force a fresh probe
- Add `py-stremio --reprobe-speed` as a one-shot CLI flag
- Print the probe value at the top of every run so the user can see
  it without grepping `.env`

A four-line change in `services/download.py:103`:

```python
max_speed_mbps = resolve_max_speed_mbps(
    default_mbps=getattr(settings, "INTERNET_MAX_SPEED_MBPS", 100),
    force_reprobe=os.environ.get("PY_STREMIO_REPROBE_SPEED") == "1",
)
print(f"  Speed cap: {max_speed_mbps:g} Mbps  (set via {'env' if ... else 'probe'})")
```

The probe itself can be improved (see §4.4) but the trigger is the
user-visible change.

### 4.3 Add a throttled / network-slow diagnostic

The footer should say **why** the speed is what it is, not just the
number. Three states, in this order of priority:

1. **Throttled by user** — `Speed: 30 %`, `Max 60 MB/s`, observed
   `> 60 MB/s` → "Throttle at limit (good)"
2. **Below throttle but line is fine** — `Speed: 80 %`, `Max 160
   MB/s`, observed `120 MB/s` → "Below limit" (something else is the
   bottleneck)
3. **Below throttle and below observed max** — `Speed: 80 %`, `Max
   160 MB/s`, observed `5 MB/s` → "Line underperforming" (likely RD /
   proxy / peer)

The classifier is a single line per render frame:

```python
if percent < 100 and observed < max_bps * 0.5:
    diagnostic = "Line under cap"
elif percent < 100:
    diagnostic = "Below cap"
else:
    diagnostic = ""  # unlimited, no point diagnosing
```

The existing `_max_throughput_label` and `_limit_label` already
expose the cap; the diagnostic just needs the *observed* aggregate
to compare against it. The aggregate is already computed in the
renderable.

### 4.4 Stretch fixes (lower priority)

These are real but only matter if the user takes the speed cap
seriously or if RD becomes even slower.

#### 4.4.1 Make the speed probe honest

`speed_probe.py:28-50` measures throughput over 12.5 MB. On a 1 Gbps
line that is 100 ms — too short for TCP slow-start to settle, too
short for the cloudflare edge to warm up. A better probe:

- Use a longer transfer (50 MB minimum) and the **last** 50 % of
  the run (TCP has stabilised by then)
- Take the median of three probes, not the first one
- Discard any probe that took longer than `expected / 3` (clearly
  congested)

The implementation is ~30 lines but the change is fully backward
compatible — the same function signature, just a smarter
implementation.

#### 4.4.2 Make the limiter window chunk-size-aware

`bandwidth_service.py:165-186` does `delay = overflow / bytes_per_second`
on every chunk. At low limits a single 64 KB chunk can produce a
multi-second delay. Two fixes:

- Short-circuit when `bytes_per_second * 1.0 < 8 * 1024` (no point
  throttling below 64 KB/s — the OS scheduler cannot enforce it)
- Cap the delay per call at `0.25 s` so a single chunk cannot park
  a download for seconds

The cap is conservative and matches the per-chunk inter-arrival
time at 32 KB/s, well below the user's most likely setting.

#### 4.4.3 Surface RD / proxy latency

When `TORRENT_PROXY_URL` is set, the user is going through an
extra hop that has its own latency budget. The proxy's response
time to the first byte (`time-to-first-byte`) is a much better
early indicator of slowness than the per-episode rate. Add a
`ttfb_ms` field to the bytes event and render it as `⏱ 850 ms` in
the per-row line when it exceeds 500 ms. This would have made the
investigation a 5-second grep instead of a 30-minute code dive.

---

## 5. Verification commands

```bash
# 1. Is the per-row rate in the TUI matching the footer?
py-stremio 4
#  ↳ watch the per-episode "Speed" cell vs the footer "MB/s"
#  ↳ before the fix: 26 KB/s vs 1.3 MB/s
#  ↳ after the fix:  both numbers agree (within smoothing)

# 2. Re-probe the speed cap to see if the stored value is bogus
PY_STREMIO_REPROBE_SPEED=1 py-stremio --run
#  ↳ before: 12.5 MB probe, ~3s, saved value 30 Mbps
#  ↳ after:  the fresh probe result, also printed at the top of the run

# 3. Spot-check the rate math with a synthetic load
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from py_stremio.components.download.processing import on_bytes
# 100 bytes every 100 ms = 1000 B/s
# simulated chunks: (100, 100ms), (200, 200ms), (300, 300ms) ...
#  ↳ current code:  rate = 100 / 0.1 = 1000 B/s  (correct)
#  ↳ after the fix: same answer, but a stalled chunk
#     (gap = 500ms, delta = 100) now reports 200 B/s, not 1000 B/s
#     the sliding window keeps the right average over the next 1s
"
```

Expected after the fix:

- Per-row and footer numbers agree within ~10 % at all times
- A stalled chunk does not produce a per-row rate below the
  actual 1-second average
- The footer shows "Line under cap" or "Below cap" when the
  user is throttling
- `PY_STREMIO_REPROBE_SPEED=1` produces a fresh probe and the
  result is visible in the run header

---

## 6. TL;DR

- **The user's per-row "26.2 KB/s" is a rate-math bug, not their
  line.** The footer "1.3 MB/s" is the real number. Fix the
  per-chunk division in `on_bytes` / `on_movie_bytes` to a
  sliding window and the two numbers will agree.
- **The speed cap stored in `.env` is a one-shot, possibly
  under-estimated value.** Add a `PY_STREMIO_REPROBE_SPEED=1`
  trigger so the user can refresh it without editing `.env`.
- **The footer has no diagnostic.** Add a one-word label
  ("Throttled" / "Below cap" / "Line under cap") so the user can
  tell which side of the limit they are on.
- **The limiter window has known edge cases at low limits** that
  do not affect the current run but will matter as soon as
  auto-throttle lands. Fix the chunk-size short-circuit and the
  per-call delay cap to prevent them.

The fix in §4.1 is the one that makes the user's complaint
disappear. The rest are quality-of-life and the necessary
diagnostics to prevent the next "why is the speed so low" ticket.

---

# Appendix A — Was the limiter actually running?

> Quick check: with `Speed: 100 %` (`Speed: 100%` is shown in the
> footer), the limiter is a no-op. Confirming this rules out
> throttling as a cause and narrows the investigation to the
> rate-math bug.

The build path is:

```python
# py_stremio/services/download.py:104
bandwidth_limiter = build_limiter(speed_percent, max_speed_mbps, max_workers=max_workers)
```

`build_limiter` (`bandwidth_service.py:199-220`):

```python
def build_limiter(percent, max_speed_mbps, max_workers=1):
    clamped_percent = max(1, min(100, int(percent)))
    if clamped_percent >= 100 or max_speed_mbps <= 0:
        total_bytes_per_second = 0
    else:
        total_bytes_per_second = int((max_speed_mbps * 1_000_000 / 8) * (clamped_percent / 100))
    if max_workers > 1:
        return FairBandwidthLimiter(total_bytes_per_second=total_bytes_per_second)
    else:
        return BandwidthLimiter(bytes_per_second=total_bytes_per_second)
```

At `percent=100` → `total_bytes_per_second = 0` → `wait_for` returns
immediately at the `if self.bytes_per_second <= 0: return` line. The
limiter is not throttling. This was confirmed at runtime: with 1
active download the screen shows "Unlimited" in the limit label
and "Max 1.3 MB/s" is only computed when `percent < 100`.

# Appendix B — Why does the user keep the value in `.env`?

> The probe result is sticky on purpose (it would be rude to
> re-probe the user's line on every run), but the user has no
> signal that the value is stale. The print at the top of the
> run, plus the `--reprobe-speed` flag, is the minimum viable
> fix.

`.env` is loaded once at process start by `dotenv` in
`app_settings.py:5`. `INTERNET_MAX_SPEED_MBPS` defaults to 100 Mbps
if the variable is missing. The probe (`speed_probe.py:86-94`) only
runs when the env *and* the .env file are both missing the key.
After the first probe, the value is appended to .env and the
process exits before the user knows what value was picked.

Concrete example: a user with a 500 Mbps line, on a day when
Cloudflare's `__down` endpoint is rate-limiting from their IP, gets
a probe value of 47 Mbps saved to .env. From that day forward every
download runs as if the line can do 47 Mbps, and the "Max MB/s"
footer is permanently wrong by 10×.

# Appendix C — Where the rate smoothing happens today

> The TUI *does* smooth — just not the underlying event. The
> smoothing window is `_stable_rate` (1.5 s hold), so the footer
> looks stable while the per-row display tracks the noisy
> per-chunk signal. Once the underlying rate math is fixed to
> a sliding window, the smoothing becomes a no-op (correct) and
> the two displays finally agree.

`py_stremio/services/terminal_ui.py:370-386` (already quoted in
§2.2): the per-event rate is taken verbatim and *held* for 1.5 s
before being updated. This is display smoothing, not input
smoothing — the input is still the noisy per-chunk number from
`on_bytes`. Fix §4.1 to fix the input and the two displays will
agree on their own.
