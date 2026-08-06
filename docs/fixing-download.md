# Fixing Corrupted/Truncated Downloads — Structural Video Validation

## Overview

When episodes download but "cannot move from one part of the video to the other" (seeking fails, playback freezes at certain points), the root cause is **undetected file truncation**. The download pipeline finishes without error on a partial file because:

1. The server sends the response **without `Content-Length`** (common for Stremio addon proxies, RealDebrid direct links, and torrent-based streams)
2. `total_size` is 0 → the existing Content-Length mismatch check is completely skipped
3. `_validate_completed_file` only checks `MIN_COMPLETED_VIDEO_SIZE_MB=100` → a 600 MB truncated file passes
4. The `.part` is renamed to `.mkv` and the pipeline reports success
5. The user opens the file: it plays the first few minutes but seeking past the truncated region fails

---

## Root Causes

### Cause 1: No Content-Length → No Truncation Detection

**File**: `py_stremio/components/download/stream_download.py`, function `download_stream_to_file`

```python
# total_size is computed from HTTP headers:
total_size = _total_size_from_headers(response.headers, downloaded)
# Returns 0 when neither Content-Length nor Content-Range is present.
```

When `total_size == 0`, the post-loop check is skipped:

```python
if total_size > 0 and downloaded < total_size:    # ← never true when total_size == 0
    ...
    raise InvalidVideoDownloadError(...)
```

The response body is terminated by **connection close** (HTTP/1.1 behaviour when no body length is declared). The client (`httpx`) reads until EOF. There is *no way* at the HTTP level to distinguish "the server finished sending all data and closed cleanly" from "the server crashed mid-transmission and closed the connection." Both look the same.

### Cause 2: Minimum Size Check Is Not Sufficient

`_validate_completed_file` checks `MIN_COMPLETED_VIDEO_SIZE_MB` (default `100 MB`):

```python
def _validate_completed_file(file_path, partial_path):
    actual_size = file_path.stat().st_size
    min_bytes = _minimum_completed_video_bytes()
    if min_bytes > 0 and actual_size < min_bytes:
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(...)
```

A typical episode is 500 MB–2 GB. A 600 MB truncated file passes this check because `600 > 100`. The file has valid headers at the start (playable for the first few minutes) but the video/audio data after the truncation point is missing.

### Cause 3: Connection-Close Responses Are Ambiguous

HTTP responses that use neither `Content-Length` nor `Transfer-Encoding: chunked` are terminated by the server closing the connection. The three scenarios:

| Scenario | httpx iter_bytes | Truncated? |
|----------|-----------------|------------|
| Server sends all data, closes cleanly | Ends normally | No |
| Server crashes mid-send, TCP RST | Raises exception | Yes (caught) |
| Server stops responding, timeout | `httpx.ReadTimeout` → `StreamStallError` | Yes (caught) |
| Server sends partial data, closes FIN | Ends normally | **YES (undetected)** |

The last row is the undetected truncation. The server sends as much data as it can (e.g. only 600 MB of a 1.5 GB file) then closes the connection with a proper TCP FIN. The client sees "all bytes received" and promotes the file.

---

## End-to-End Flow of a Broken Download

```
Stream URL resolved (no Content-Length in headers)
  → download_stream_to_file()
    → total_size == 0
    → httpx.stream("GET", url, ...)
    → iter_bytes reads until EOF (connection close by server)
    → no exception raised
    → total_size (0) > 0 AND downloaded (600MB) < total_size? → NO (skipped)
    → partial_path.replace(final_path)
    → _validate_completed_file(): 600MB > 100MB → PASS
    → returns success
  → pipeline marks episode as downloaded
  → user plays file: first 3 minutes work, seeking past 3 min freezes
```

---

## Fix: Structural Video Validation After Download

### Fix 1: Add `_validate_video_structure()` — ffprobe-based File Integrity Check

**File**: `py_stremio/components/download/stream_download.py`

After the file is renamed from `.part` to the final filename, run `ffprobe` to check if the file contains playable video:

```python
def _validate_video_structure(file_path: Path) -> bool:
    """Check if the downloaded video file is structurally valid.
    
    Uses ffprobe to demux the file header and detect truncation or
    corruption. Fails fast when:
      - The file cannot be opened by ffprobe (truncated header)
      - ffprobe reports structural errors (corrupted data)
      - Duration is 0 or N/A (no playable content)
    
    When ffprobe is not available, falls back to a basic container
    header check and logs a warning — files are still accepted but
    the user is advised to install ffprobe for thorough validation.
    """
```

ffprobe's `-v error -xerror -show_entries format=duration`:
- Reads container-level metadata (header, tracks, duration)
- For MKV: reads EBML header, Segment Info (duration), SeekHead, Tracks
- For MP4: reads ftyp box, moov atom (duration), trak atoms
- Exits with non-zero code + error message if the file is truncated or corrupted

**Performance**: ffprobe reads only the file headers, not the full decoded content. Even for multi-GB files, this completes in < 1 second for MKV and fast-start MP4, and ~2-3 seconds for non-fast-start MP4 (moov at end, requires seeking to the end of the file which is O(1) anyway).

**Availability**: `/usr/bin/ffprobe` is available on the user's system (part of the `ffmpeg` package). If not present, the fix gracefully degrades to the existing behaviour.

### Fix 2: Track HTTP Response Termination Type

In `download_stream_to_file`, capture whether the response body completeness could be verified through HTTP protocol means:

```python
# After the httpx.stream() block:
response_body_verified = (
    total_size > 0       # Content-Length or Content-Range was present → size known
    or "chunked" in transfer_encoding  # Chunked → 0-length terminator received
)
```

Then pass `not response_body_verified` as `check_structure` to `_validate_completed_file`.

### Fix 3: Pass `check_structure` to Validation

```python
def _validate_completed_file(file_path, partial_path, check_structure=False):
    # Existing min-size check...
    ...
    # New structural validation:
    if check_structure and not _validate_video_structure(file_path):
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Downloaded file failed structural validation — "
            f"likely truncated or corrupted"
        )
```

---

## What Changes After the Fix

**Before**: A 600 MB truncated file passes all checks, renamed to .mkv, user can't seek.

**After**: ffprobe detects the file is truncated (missing data after byte X million), raises `InvalidVideoDownloadError`. The caller (`_try_download_streams`) falls through to the next stream in the quality-sorted queue. Instead of a broken file, the user gets a complete download from a different stream (or RealDebrid fallback).

**On re-run**: The .part file is preserved (structural validation doesn't delete it on failure), so the next attempt resumes from the existing bytes via HTTP Range headers — no bandwidth is wasted.

---

## Verification

### Test: Truncated download with no Content-Length raises InvalidVideoDownloadError

Simulate a server that sends a valid-looking MKV header but no Content-Length and closes the connection early. The download should fail with `InvalidVideoDownloadError` mentioning "structural validation".

### Test: Clean download with no Content-Length passes validation

Simulate a server that sends a complete, valid MKV file as a connection-close response (no Content-Length, not chunked). The download should succeed because ffprobe confirms the file is structurally sound.

### Test: ffprobe not available → graceful degradation

When `ffprobe` is not on PATH, structural validation is skipped and the file passes through to the existing min-size check (current behaviour). A warning is logged.

---

## Edge Cases

1. **Very large files**: ffprobe reads headers only, so 10 GB+ files are validated in < 2 seconds. A 30-second timeout protects against slow filesystem.

2. **Live streaming sources**: Some addons return HLS/DASH playlists disguised as video URLs. ffprobe will fail on these (they're not valid video files). The download will be rejected. This is correct behaviour — those aren't downloadable videos.

3. **Encrypted/DRM files**: ffprobe will report errors for DRM-encrypted files. These files are not playable without the DRM key, so rejecting them is correct.

4. **ffprobe false positives**: Very old or obscure codecs might confuse ffprobe. If this causes too many false rejections, the `VALIDATE_DOWNLOAD_STRUCTURE` setting can be set to `false` in `.env`.

---

## New Setting

| Variable | Default | Purpose |
|----------|---------|---------|
| `VALIDATE_DOWNLOAD_STRUCTURE` | `true` | When false, skip ffprobe structural validation and accept files based on `MIN_COMPLETED_VIDEO_SIZE_MB` alone |
