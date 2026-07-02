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

### 1. Content-Length Mismatch Not Detected

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

The download loop reads `total_size` from HTTP headers once at start and never compares actual bytes received. If the server sends fewer bytes than claimed (premature close, truncated response, spoofed headers), the download completes without error but the file is incomplete.

**Impact**: When `MIN_COMPLETED_VIDEO_SIZE_MB=100` (default), a 200 MB server that sends 150 MB still passes the size validation. The progress shows "complete" at the header's byte count but the file is truncated.

### 2. Final-File Promotion Outside Try/Except

**File**: `py_stremio/components/download/stream_download.py`, line 842

```python
    except httpx.ReadTimeout as e:
        _delete_invalid_download(file_path, partial_path)
        raise StreamStallError(...) from e
    finally:
        if registered_here and bandwidth_limiter:
            bandwidth_limiter.unregister_thread(active_thread_id)

    partial_path.replace(file_path)           # ← OUTSIDE try/except/finally
    _validate_completed_file(file_path, partial_path)
```

The `.part` → final rename ran **after** the try/finally block. If `_validate_completed_file` raised `InvalidVideoDownloadError` (file below `MIN_COMPLETED_VIDEO_SIZE_MB`), the incomplete file was already renamed and persisted, while the exception propagated to the caller. The caller (`_try_download_streams`) would retry — potentially overwriting or failing — with the incomplete file already on disk.

**Impact**: When both direct stream and RealDebrid fallback produce files that pass validation (e.g., 150 MB for a 200 MB show), the first incomplete file survives. On subsequent runs, Fix 3 (below) prevents it from being skipped silently.

### 3. RealDebrid File Selection May Pick Wrong Episode

**File**: `py_stremio/components/debrid/real_debrid_client.py`, lines 116–124

Stremio addons return `fileIdx` as a zero-based index into the torrent file list. In multi-episode season packs, this index may not map 1:1 to the RD file list, especially for multi-file torrents where RD returns a different file ordering. If `_real_debrid_file_for_idx` returns the wrong file, the download proceeds with wrong content.

**Severity**: Lower — the title/episode filter in `select_quality_streams()` catches mismatches, but wrong files that happen to pass the filter (same show, same season, no episode number in filename) download silently.

---

## Implemented Fixes

### Fix 1: Content-Length Mismatch Detection ✅ (stream_download.py)

```python
    # After the download loop, before renaming:
    if total_size > 0 and downloaded < total_size:
        _delete_invalid_download(file_path, partial_path)
        raise InvalidVideoDownloadError(
            f"Server promised {total_size} bytes but sent only {downloaded} "
            f"for {file_path.name}"
        )
```

Catches premature connection closes and spoofed headers before the file is promoted. The `.part` file is still present for retry.

### Fix 2: Try/Except Around Final-File Promotion ✅ (stream_download.py)

```python
    try:
        partial_path.replace(file_path)
        _validate_completed_file(file_path, partial_path)
    except InvalidVideoDownloadError:
        # Delete incomplete file before re-raising so caller can retry cleanly
        _delete_invalid_download(file_path, partial_path)
        raise
```

Ensures an invalid file is never left on disk after a validation failure.

### Fix 3: Re-Download Truncated Existing Files ✅ (processing.py)

In `_do_download_one_episode`, the existence check now validates file size before skipping:

```python
    if (task.folder_path / generated_filename).exists():
        existing_path = task.folder_path / generated_filename
        existing_size = existing_path.stat().st_size
        min_bytes = _minimum_completed_video_bytes()
        if min_bytes > 0 and existing_size < min_bytes:
            print(f"    S{season:02d}E{episode:02d}: existing file "
                  f"is only {existing_size / 1024 / 1024:.1f} MB "
                  f"(min {min_bytes / 1024 / 1024:.0f} MB) — re-downloading")
            existing_path.unlink(missing_ok=True)
        else:
            # ... skip
```

Prevents truncated files from previous failed runs from being silently skipped on re-run.

---

## Proposed Fixes (Not Yet Implemented)

### Fix 4: Robust RealDebrid File Selection

When RD file selection fails or returns no links, scan all available files for a video link:

```python
def _download_url_from_torrent_info(info: dict, file_idx: int | None) -> str | None | bool:
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

---

## What Happens to `90 Day Fiancé s12e08` Now

Before these fixes:
- Direct stream: `Content-Length: 500MB`, server sends 200MB → progress shows complete → file is 200MB → passes `MIN_COMPLETED_VIDEO_SIZE_MB=100` → file is corrupt but accepted
- On re-run: file exists, skipped silently

After these fixes:
- Direct stream: same scenario → `downloaded (200MB) < total_size (500MB)` → `InvalidVideoDownloadError` → `.part` deleted → caller retries via RealDebrid
- RealDebrid fallback: if it also produces a too-small file, same detection applies
- On re-run: file exists but is only 200MB < 100MB threshold → re-downloaded

---

## Verification

After implementing additional fixes, test with streams that:
- Respond with `Content-Length: 500MB` but close after 200MB (premature TCP close)
- Return a 150MB error page as a video (spoofed `Content-Length`)
- Have a multi-file torrent where `fileIdx` points to the wrong episode
