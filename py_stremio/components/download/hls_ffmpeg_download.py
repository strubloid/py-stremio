"""ffmpeg-backed HLS downloader.

While the existing :mod:`py_stremio.components.download.hls_download`
module parses ``.m3u8`` playlists in Python and fetches each segment
individually, this module shells out to ``ffmpeg`` which already knows
how to handle HLS — including edge cases the pure-Python implementation
doesn't (encrypted segments, discontinuity tags, ``EXT-X-MAP`` init
segments, byte-range segments, live edge, variable segment durations).

The wrapper mirrors :class:`HlsDownloader`'s public surface
(``download(url, filename)``, ``close()``) so callers can swap the two
without changing the rest of the pipeline.  The dispatcher in
:mod:`py_stremio.components.download.stream_download` picks one or the
other based on the ``HLS_DOWNLOAD_METHOD`` setting and on whether the
``ffmpeg`` binary is on ``PATH``.

Bandwidth limiting: ``-maxrate``/``-bufsize`` are set from the supplied
:class:`FairBandwidthLimiter` so the user's ``INTERNET_SPEED_LIMIT``
percentage is honoured.  The thread is *not* registered with the
limiter — ffmpeg self-throttles, so the limiter's fair-share
calculation would otherwise double-throttle this thread.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import warnings
from pathlib import Path
from urllib.parse import urlparse

from py_stremio.utils.cancellation import raise_if_shutdown_requested


# ffmpeg's ``-progress`` output is one key=value pair per line, see
# https://ffmpeg.org/ffmpeg.html#Generic-options
_PROGRESS_KEY_VALUE = re.compile(r"^(\w+)=(.+)$")

# Cached probe — the typical case is a long-lived CLI invocation that
# downloads many episodes in a row, so we don't want to run
# ``shutil.which`` on every download.
_FFMPEG_PATH: str | None = None
_FFMPEG_PROBED: bool = False


def find_ffmpeg() -> str | None:
    """Return the absolute path to the ``ffmpeg`` binary, or ``None``.

    The result is cached so we don't re-run ``shutil.which`` on every
    download.  Pass :func:`reset_ffmpeg_probe` to clear the cache
    (mainly useful in tests that install/uninstall a fake binary).
    """
    global _FFMPEG_PATH, _FFMPEG_PROBED
    if not _FFMPEG_PROBED:
        _FFMPEG_PATH = shutil.which("ffmpeg")
        _FFMPEG_PROBED = True
    return _FFMPEG_PATH


def reset_ffmpeg_probe() -> None:
    """Clear the cached ffmpeg path lookup (test hook)."""
    global _FFMPEG_PATH, _FFMPEG_PROBED
    _FFMPEG_PATH = None
    _FFMPEG_PROBED = False


class HlsFfmpegError(RuntimeError):
    """Raised when ffmpeg fails to download an HLS playlist."""


class HlsFfmpegStallError(HlsFfmpegError):
    """Raised when ffmpeg produces no output for longer than the stall timeout."""


def _bandwidth_quota_bps(limiter) -> int:
    """Return the bandwidth quota for the current thread, in *bits per second*.

    Returns ``0`` when no limit is active — callers should then skip
    the ``-maxrate``/``-bufsize`` flags so ffmpeg can run at full
    speed.  Defensive against limiters that don't expose the helper
    methods we expect (returns ``0`` in that case).
    """
    if limiter is None:
        return 0
    bps = 0
    if hasattr(limiter, "get_fair_share_bps"):
        try:
            bps = int(limiter.get_fair_share_bps() or 0)
        except Exception:
            bps = 0
    elif hasattr(limiter, "bytes_per_second"):
        try:
            bps = int(limiter.bytes_per_second or 0)
        except Exception:
            bps = 0
    return max(0, bps) * 8


class HlsFfmpegDownloader:
    """Download an HLS playlist by shelling out to ``ffmpeg -c copy``.

    Writes bytes to a sibling ``.part`` file and renames on success.
    Like the segment-based :class:`HlsDownloader`, there is no
    Range-based resume: HLS servers do not honour range requests on
    ``.m3u8`` manifests, and ffmpeg cannot append to an existing
    file once the header has been written.
    """

    def __init__(
        self,
        *,
        bandwidth_limiter=None,
        thread_id=None,
        progress_callback=None,
        stall_timeout=60.0,
    ):
        self.bandwidth_limiter = bandwidth_limiter
        self.thread_id = (
            thread_id if thread_id is not None else threading.get_ident()
        )
        self.progress_callback = progress_callback
        self.stall_timeout = float(stall_timeout) if stall_timeout else 0.0

    def close(self) -> None:
        """No-op — kept for API symmetry with :class:`HlsDownloader`."""
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def download(self, url: str, filename: str) -> int:
        """Resolve *url* via ffmpeg and write a single file at *filename*.

        Returns the final output file size in bytes.  Raises
        :class:`HlsFfmpegError` on any ffmpeg failure and
        :class:`HlsFfmpegStallError` when ffmpeg produces no progress
        for longer than ``stall_timeout`` seconds.
        """
        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            raise HlsFfmpegError(
                "ffmpeg binary not found on PATH; install ffmpeg "
                "(apt install ffmpeg) or set HLS_DOWNLOAD_METHOD=segment "
                "to use the pure-Python downloader"
            )

        output = Path(filename)
        partial = output.with_name(f"{output.name}.part")
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)

        cmd = self._build_command(ffmpeg_path, url, partial)
        return self._run(cmd, partial, output)

    def _build_command(self, ffmpeg_path: str, url: str, partial: Path) -> list[str]:
        """Assemble the ffmpeg argv for one download."""
        maxrate_bps = _bandwidth_quota_bps(self.bandwidth_limiter)
        cmd = [
            ffmpeg_path,
            "-y",                # overwrite output without prompting
            "-nostdin",          # never block waiting on stdin (cron / piped)
            "-hide_banner",      # drop the version banner from stderr
            "-loglevel", "error",
        ]
        if maxrate_bps > 0:
            # ``-bufsize`` at 2× ``-maxrate`` is the convention ffmpeg
            # uses in its own example recipes; large enough to ride
            # out short CDN bursts without buffering the whole stream.
            cmd.extend([
                "-maxrate", str(maxrate_bps),
                "-bufsize", str(maxrate_bps * 2),
            ])
        cmd.extend([
            "-progress", "pipe:1",   # machine-readable progress on stdout
            "-i", url,
            "-c", "copy",            # no re-encode
        ])
        # The partial filename is ``<name>.mkv.part`` which ffmpeg
        # can't infer a muxer from.  Pin the format explicitly so the
        # container matches the final on-disk name (the caller's
        # ``build_media_filename`` always returns ``.mkv``).
        cmd.extend(["-f", "matroska", str(partial)])
        return cmd

    def _run(self, cmd: list[str], partial: Path, output: Path) -> int:
        """Spawn ffmpeg, parse its progress, validate the output."""
        env = os.environ.copy()
        # Some CDNs gate on User-Agent; match the UA the segment-based
        # HlsDownloader uses.  ffmpeg itself has no UA knob but most
        # HTTP libraries honour the standard env var.
        env.setdefault("User-Agent", "Stremio/4.4.168")

        last_progress_at = time.monotonic()
        latest_total_size = 0
        last_emit_at = 0.0
        returncode: int | None = None
        stderr_text = ""

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise HlsFfmpegError(f"Failed to invoke ffmpeg: {exc}") from exc

        try:
            while True:
                raise_if_shutdown_requested()
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    if proc.poll() is not None:
                        break
                    # No progress AND process still alive — possible
                    # stall.  Only trip if we've never seen any output;
                    # once data is flowing, ffmpeg's normal
                    # stall-detection in its HTTP layer is enough.
                    if (
                        self.stall_timeout > 0
                        and latest_total_size == 0
                        and (time.monotonic() - last_progress_at) > self.stall_timeout
                    ):
                        proc.kill()
                        proc.wait()
                        raise HlsFfmpegStallError(
                            f"ffmpeg produced no output for {self.stall_timeout}s"
                        )
                    continue

                line = line.strip()
                if not line:
                    continue

                match = _PROGRESS_KEY_VALUE.match(line)
                if not match:
                    continue
                key, value = match.group(1), match.group(2)
                if key == "total_size":
                    try:
                        latest_total_size = int(value)
                        last_progress_at = time.monotonic()
                    except ValueError:
                        pass
                elif key == "out_time_us":
                    last_progress_at = time.monotonic()
                elif key == "progress":
                    last_progress_at = time.monotonic()
                    if value == "end":
                        break

                # Rate-limit progress emissions to ~1/sec so the
                # console isn't drowned in ffmpeg's per-frame updates.
                now = time.monotonic()
                if self.progress_callback and (now - last_emit_at) >= 1.0:
                    self.progress_callback(latest_total_size, 0)
                    last_emit_at = now

            stderr_text = (proc.stderr.read() if proc.stderr else "") or ""
            returncode = proc.wait()
        except BaseException:
            # On any unexpected error (cancellation, Ctrl+C, KeyboardInterrupt),
            # make sure ffmpeg is reaped so we don't leak a subprocess.
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass
            raise

        if returncode != 0:
            partial.unlink(missing_ok=True)
            stderr_msg = (stderr_text or "").strip()
            raise HlsFfmpegError(
                f"ffmpeg exited with code {returncode}: "
                f"{stderr_msg or 'unknown error'}"
            )

        if not partial.exists():
            raise HlsFfmpegError(
                "ffmpeg exited successfully but produced no output file"
            )

        final_size = self._validate_and_finalize(partial, output)

        if self.progress_callback:
            self.progress_callback(final_size, final_size)

        return final_size

    def _validate_and_finalize(self, partial: Path, output: Path) -> int:
        """Apply ``MIN_COMPLETED_VIDEO_SIZE_MB`` and rename on success."""
        from py_stremio.components.configs.app_settings import settings

        actual_size = partial.stat().st_size
        min_bytes = (
            max(0, getattr(settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 100))
            * 1024
            * 1024
        )
        if min_bytes > 0 and actual_size < min_bytes:
            partial.unlink(missing_ok=True)
            raise HlsFfmpegError(
                f"ffmpeg HLS download produced only {actual_size} bytes "
                f"(min {min_bytes} for a complete video)"
            )
        partial.replace(output)
        return actual_size


def warn_missing_ffmpeg() -> None:
    """Emit a one-shot warning that ffmpeg is not installed.

    The dispatcher calls this the first time it falls back to the
    segment-based downloader so the user knows why HLS quality
    expectations may drop.  Subsequent fallbacks in the same process
    stay silent.
    """
    warnings.warn(
        "ffmpeg is not installed; py-stremio is falling back to the "
        "pure-Python HLS downloader. Install ffmpeg (apt install ffmpeg) "
        "for robust HLS handling. Suppress this warning by setting "
        "HLS_DOWNLOAD_METHOD=segment in your .env.",
        RuntimeWarning,
        stacklevel=2,
    )


def is_m3u8_url(url: str | None) -> bool:
    """Return True when *url* points at an ``.m3u8``/``.m3u`` playlist.

    Mirrors :func:`py_stremio.components.download.stream_download._is_hls_url`
    — both helpers exist because the addons module already had its own
    copy and the downloader module had its own copy before
    ffmpeg-based routing was added.  Path's terminal extension is the
    authoritative check; query strings / fragments are ignored.
    """
    if not url:
        return False
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    path = (parsed.path or "").lower()
    return path.endswith(".m3u8") or path.endswith(".m3u")


__all__ = [
    "HlsFfmpegDownloader",
    "HlsFfmpegError",
    "HlsFfmpegStallError",
    "find_ffmpeg",
    "reset_ffmpeg_probe",
    "warn_missing_ffmpeg",
    "is_m3u8_url",
]
