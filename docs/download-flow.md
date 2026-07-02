# Download Flow Analysis — Incomplete File Root Cause

## Overview

When `90 Day Fiancé s12e08.mkv` downloaded but felt "missing parts", two bugs were identified and fixed:

1. **Content-length mismatch not detected**: the download loop blindly trusts HTTP headers and never compares actual bytes received against the promised `Content-Length` or `Content-Range` total.
2. **Final-file promotion outside try/except**: `.part` → final-file rename happened after the `try` block, so when `_validate_completed_file` raised `InvalidVideoDownloadError` (file too small), the incomplete file survived on disk while the exception propagated, causing retries to fail or write over the wrong file.

Below is the full end-to-end trace and the implemented fixes.

---

## End-to-End Download Pipeline

```
AppService.run_pipeline()
  → DownloadService.run()
    → process_season_folder()
      → _do_download_one_episode()
        → search_and_download()
          → _search_single_id()
            → _try_download_streams()
              → select_quality_streams()          # filter by title/episode/quality
              → for stream in streams:
                  → resolve_stream_download_url()   # direct URL or RD proxy or info_hash
                  → download_stream_to_file()       # HTTP download with .part resume
                    → .part written incrementally
                    → .part.replace(final_file)    # ← BUG: outside try/except
                    → _validate_completed_file()   # size check after rename
                  ← on success: return to _try_download_streams
              → on InvalidVideoDownloadError:
                  → _retry_with_real_debrid()     # try RD as fallback
                    → RD API: magnet → torrent → select files → poll
                    → download_stream_to_file()   # ← same .part bug here too
              → on StreamStallError: continue to next stream
          → on success: apply_result() → state.add_download() → save_state()
```

---

## Root Causes

### 1. `.part` → Final File Rename Is Outside the Try Block

**File**: `py_stremio/components/download/stream_download.py`, line 842

```python
def download_stream_to_file(...):
    try:
        with httpx.stream(...) as response:
            ...
            with open(partial_path, mode) as file:
                for chunk in response.iter_bytes(chunk_size=8192):
                    ...
                    file.write(chunk)
    except httpx.ReadTimeout as e:
        _delete_invalid_download(file_path, partial_path)  # only on ReadTimeout
        raise StreamStallError(...) from e
    finally:
        if registered_here and bandwidth_limiter:
            bandwidth_limiter.unregister_thread(active_thread_id)

    partial_path.replace(file_path)          # ← OUTSIDE try/except/finally
    _validate_completed_file(file_path, partial_path)
```

**Problem**: If `_validate_completed_file()` raises `InvalidVideoDownloadError` (file too small), the exception propagates to the caller. The final file has already been renamed from `.part` to the final path by line 842, **before** validation ran. The caller (`_try_download_streams`) catches `InvalidVideoDownloadError` and retries via RealDebrid — but the **incomplete file is already on disk** and the RealDebrid retry may also fail or also produce an incomplete file, leaving the final file in a corrupted state.

**Impact**: When both the direct stream and the RealDebrid fallback produce files that pass validation (or when validation is disabled via `MIN_COMPLETED_VIDEO_SIZE_MB=0`), the first incomplete file wins.

### 2. Content-Length Mismatch Not Detected

**File**: `py_stremio/components/download/stream_download.py`, lines 699–709 and 813

```python
def _total_size_from_headers(headers, existing_size) -> int:
    content_range = headers.get("content-range")
    if content_range and "/" in content_range:
        total_text = content_range.rsplit("/", 1)[-1]
        if total_text.isdigit():
            return int(total_text)

    content_length = headers.get("content-length")
    if content_length and content_length.isdigit():
        return existing_size + int(content_length)
    return 0  # ← returns 0 when headers are absent
```

And in the download loop:

```python
for chunk in response.iter_bytes(chunk_size=8192):
    ...
    file.write(chunk)
    downloaded += len(chunk)
    if progress_callback:
        progress_callback(downloaded, total_size)
```

**Problem**: `total_size` is read once from HTTP headers at download start and never compared against actual bytes received. If the server:
- Sends fewer bytes than `Content-Length` claims (premature connection close)
- Sends an error page with a spoofed `Content-Length` header
- Sends gzip/truncated content

...the download completes without error, but the file is incomplete. The progress callback shows the download reaching the header's `total_size`, but actual bytes on disk are fewer.

**Severity**: High for direct HTTP streams. Lower for RealDebrid URLs since RD serves cached content with reliable content-length.

### 3. RealDebrid File Selection May Pick the Wrong File

**File**: `py_stremio/components/debrid/real_debrid_client.py`, lines 116–124 and 138–144

```python
def _download_url_from_torrent_info(info: dict, file_idx: int | None) -> str | None | bool:
    status = info["status"]
    if status == "downloaded":
        file_ = _real_debrid_file_for_idx(info.get("files", []), file_idx)
        if not file_:
            return None
        links = file_.get("links", [])
        if links:
            return links[0]
        return None
```

**Problem**: `file_idx` is the Stremio zero-based file index. However, Stremio addons may return `fileIdx` for the wrong episode in multi-episode torrents (e.g., a season pack where the Stremio index doesn't map 1:1 to the RD file list). When `_real_debrid_file_for_idx` returns `None` or the wrong file, `links[0]` is `None` or points to the wrong episode's link. The download proceeds with the wrong content.

**Mitigating factor**: The title/episode filter in `select_quality_streams()` should catch this before the download attempt. However, if the wrong file happens to pass the filter (e.g., same show, same season, no episode number in filename), it downloads silently.

---

## State of Incomplete Downloads After the Run

When an episode download completes successfully (according to state), the file should be valid. The state machine:

```
download_stream_to_file() → writes .part → .part.replace(final)
  → _validate_completed_file() → raises → propagates to _try_download_streams
    → _retry_with_real_debrid() → second download
      → succeeds → _success_result() → apply_result() → state.add_download()
```

The final file should be valid **if**:
1. `_validate_completed_file` passes (file ≥ `MIN_COMPLETED_VIDEO_SIZE_MB`)
2. The stream was a valid video, not an error page

If the user sees an incomplete file in their folder after a run, one of these happened:
- The file passed `MIN_COMPLETED_VIDEO_SIZE_MB` but is still truncated (header claimed more bytes than delivered)
- The file passed through `_validate_response_before_download` as non-text (e.g., a video wrapper page) and was large enough
- A second run found the file already in state and skipped it without re-validating

**Key safeguard that should have caught this**: `_validate_completed_file` at line 843 deletes the file and raises if it's below `MIN_COMPLETED_VIDEO_SIZE_MB` (default 100 MB). If `90 Day Fiancé s12e08` was downloaded as an incomplete file larger than 100 MB, this safeguard was bypassed — pointing to **root cause #2** (content-length mismatch).

---

## Proposed Fixes

### Fix 1: Wrap Final-File Promotion in Try/Except (Critical)

Move `.part.replace()` inside a try block so that if `_validate_completed_file` raises, the final file is deleted before propagating:

```python
# Inside download_stream_to_file(), replace lines 842–843:
    try:
        partial_path.replace(file_path)
        _validate_completed_file(file_path, partial_path)
    except InvalidVideoDownloadError:
        # File is too small — delete it and re-raise so caller can retry
        _delete_invalid_download(file_path, partial_path)
        raise
```

This ensures the incomplete file never survives a validation failure.

### Fix 2: Detect Content-Length Mismatch After Download (Critical)

After the download loop, compare actual bytes received against the declared size:

```python
if total_size > 0 and downloaded < total_size:
    _delete_invalid_download(file_path, partial_path)
    raise InvalidVideoDownloadError(
        f"Server promised {total_size} bytes but sent only {downloaded}"
    )
```

This catches premature connection closes and spoofed headers. The check should go **after** the loop and **before** the rename, so the `.part` file is still present for retry.

### Fix 3: Robust RealDebrid File Selection (Medium)

When RD file selection fails or returns no links, fall back to downloading all files and matching by size/title:

```python
def _download_url_from_torrent_info(info: dict, file_idx: int | None) -> str | None | bool:
    # ... existing logic ...
    if status == "downloaded":
        file_ = _real_debrid_file_for_idx(info.get("files", []), file_idx)
        if file_ and file_.get("links"):
            return file_["links"][0]
        # Fallback: scan all files for a video link
        for f in info.get("files", []):
            links = f.get("links", [])
            if links and _looks_like_video_link(links[0]):
                return links[0]
        return None
```

Where `_looks_like_video_link` checks for common video extensions in the URL.

### Fix 4: Add Byte-Count Final Validation to RealDebrid Path

The RealDebrid retry path in `_retry_with_real_debrid` calls `download_stream_to_file`, which will benefit from Fix 1 and Fix 2. No additional changes needed there.

### Fix 5: Validate Existing Files on Re-Run (Defensive)

In `_do_download_one_episode`, the existence check at line 230 only verifies the file exists, not that it's valid:

```python
if (task.folder_path / generated_filename).exists():
    if not task.state.is_downloaded(generated_filename):
        task.state.add_download(...)
    return {"episode": episode_num, "result": {"success": False, "skipped": True, ...}}
```

Add a quick size check:

```python
if (task.folder_path / generated_filename).exists():
    existing = (task.folder_path / generated_filename).stat().st_size
    min_bytes = _minimum_completed_video_bytes()
    if min_bytes > 0 and existing < min_bytes:
        # File exists but is too small — re-download
        (task.folder_path / generated_filename).unlink(missing_ok=True)
    else:
        if not task.state.is_downloaded(generated_filename):
            task.state.add_download(...)
        return {"episode": episode_num, "result": {"success": False, "skipped": True, ...}}
```

---

## Recommended Implementation Order

1. **Fix 2** (content-length mismatch) — prevents truncated downloads from passing silently
2. **Fix 1** (try/except around rename) — ensures incomplete files are deleted on validation failure
3. **Fix 5** (re-run validation) — catches already-present truncated files before skipping
4. **Fix 3** (RD file selection robustness) — lower priority since title/episode filter should catch mismatches

---

## Verification

After implementing fixes, test with a stream that:
- Responds with `Content-Length: 500MB` but closes after 200MB
- Returns a 150MB error page instead of a video
- Has a multi-file torrent where `fileIdx` points to the wrong episode
