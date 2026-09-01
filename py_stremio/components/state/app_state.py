"""Download state management."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any

from py_stremio.utils.atomic_write import atomic_write_json

# How long an indeterminate preflight result is honoured before the
# per-episode pipeline is allowed to re-attempt the full search.
# Short enough that a one-off rate-limit burst does not block a season
# for long, long enough that the next preflight within the same
# process is not needlessly re-run.
PREFLIGHT_INDETERMINATE_TTL_SECONDS = 30 * 60

# Maximum age of an ``in_progress`` marker before the next run treats
# it as stale and discards it. The .part file is the ground truth —
# this TTL is a safety net for crashed runs that left the marker
# without a matching file (e.g. process killed between the marker
# write and the .part write). 24 hours is well past the longest
# realistic single-episode download for a 4K file.
IN_PROGRESS_MAX_AGE_SECONDS = 24 * 60 * 60

# Maximum age of a ``started`` marker (the "previously started downloading"
# priority signal) before the next run treats it as stale and drops it.
# Seven days is long enough that a weekly cron run still benefits from
# the signal but short enough that a long-idle torrent's dead seeds do
# not crowd out fresh episodes. See docs/download-priority.md.
STARTED_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


@dataclass
class DownloadRecord:
    filename: str
    quality: str
    provider: str
    addon_url: str = ""
    server: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    attempts: int = 1


@dataclass
class DownloadState:
    folder_path: Path
    items: dict[str, DownloadRecord] = field(default_factory=dict)
    last_scan: str = field(default_factory=lambda: datetime.now().isoformat())
    total_downloaded: int = 0
    failed_items: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Transient bookmarks that are NOT counted as permanent failures.
    # Used to mark "this run could not complete the preflight because
    # every addon's host was rate-limit saturated" — the per-episode
    # pipeline should still attempt a fresh search the next time
    # (until the TTL expires).
    preflight_indeterminate: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Episodes whose download is currently in progress — a ``.part``
    # file is on disk and the next run should resume them before
    # touching any other episode. The on-disk ``.part`` file is the
    # ground truth; this field is the persisted cross-run cache that
    # lets the next process start with resume-first ordering instead
    # of starting the addon search from scratch for every episode.
    in_progress: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Episodes / movies that previously produced real bytes from the
    # network stream (i.e. seeds were alive at the time). On the next
    # run these are tried BEFORE never-attempted items because the
    # torrent/peers that served them yesterday are still the most
    # likely source today. Distinct from :attr:`in_progress`, which
    # only tracks live ``.part`` files. Distinct from
    # :attr:`failed_items`, which records permanent failures. See
    # docs/download-priority.md for the full rules.
    started: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_download(self, filename: str, quality: str, provider: str,
                     addon_url: str = "", server: str = "") -> None:
        """Record a successful download.

        `server` is the addon URL that actually served the stream (the same
        data that used to live in `addon_url`).  Both fields are kept for
        backward compatibility so old state files continue to work.
        """
        if server and not addon_url:
            addon_url = server
        elif addon_url and not server:
            server = addon_url
        self.items[filename] = DownloadRecord(
            filename=filename,
            quality=quality,
            provider=provider,
            addon_url=addon_url,
            server=server,
            timestamp=datetime.now().isoformat(),
        )
        self.total_downloaded += 1
        # A successful download means the episode was resolved. Drop any
        # stale failure record for the same logical episode so the state
        # file no longer claims "failed" for an item that is now on disk.
        self._clear_failed_for_filename(filename)
        # A successful download is no longer "in progress". Drop the
        # in-progress marker for this episode and any sibling form
        # (``episode_N.mkv``) so the state file no longer claims the
        # file is being downloaded.
        self._clear_in_progress_for_filename(filename)
        # Same logic for the priority list — the item is no longer
        # missing, so a "started" marker would just be noise.
        self._clear_started_for_filename(filename)

    def _clear_failed_for_filename(self, filename: str) -> None:
        """Remove any ``failed_items`` entry that points to the same episode.

        The state file uses three key shapes for an episode:
        - The final filename (with sanitised title, e.g.
          ``Rick and Morty_s09e10.mkv``)
        - The legacy ``episode_N.mkv`` key
        - The modern processing ``episode_N`` key (no extension) that
          :meth:`mark_failed` writes from the per-episode pipeline.
          Clearing this shape lets a freshly-succeeded episode drop its
          cross-run failure counter so it can re-enter the missing list
          if the file is later deleted from disk.

        Either may show up in ``failed_items`` after a previous failed
        attempt. When a successful download lands, all matching shapes
        should be dropped to avoid the misleading "state says failed but
        file is on disk" pattern called out in the download-issues
        investigation.
        """
        stem = Path(filename).stem
        episode_number = _episode_number_from_stem(stem)
        for key in list(self.failed_items):
            if key == filename:
                self.failed_items.pop(key, None)
            elif episode_number and (
                key == f"episode_{episode_number}"
                or key == f"episode_{episode_number}.mkv"
            ):
                self.failed_items.pop(key, None)
            elif episode_number and key.startswith(f"episode_{episode_number}."):
                # Legacy ``episode_N.mkv`` form, regardless of extension.
                self.failed_items.pop(key, None)

    def _clear_in_progress_for_filename(self, filename: str) -> None:
        """Remove any ``in_progress`` entry that points to the same episode.

        In-progress markers use the ``episode_N`` key shape (no file
        extension) so they share a namespace with :attr:`failed_items`
        and :attr:`preflight_indeterminate`. The legacy forms
        ``episode_N.mkv`` and ``episode_N.something`` are also accepted
        for backward compatibility with state files written by older
        pipeline versions.
        """
        stem = Path(filename).stem
        episode_number = _episode_number_from_stem(stem)
        for key in list(self.in_progress):
            if key == filename:
                self.in_progress.pop(key, None)
            elif episode_number and key in {
                f"episode_{episode_number}",
                f"episode_{episode_number}.mkv",
            }:
                self.in_progress.pop(key, None)
            elif episode_number and key.startswith(f"episode_{episode_number}."):
                # Legacy ``episode_N.mkv`` form, regardless of extension.
                self.in_progress.pop(key, None)

    def _clear_started_for_filename(self, filename: str) -> None:
        """Remove any ``started`` entry that points to the same item.

        Symmetric with :meth:`_clear_in_progress_for_filename`. The
        ``started`` field uses the same key shapes (``episode_N`` for
        series, ``<title>.mkv`` for movies) so the same lookup logic
        applies. For movies the stem-based episode extraction yields
        ``None`` and the only matching key is the bare filename — that
        is exactly what we want, since a movie has no per-episode
        history.
        """
        stem = Path(filename).stem
        episode_number = _episode_number_from_stem(stem)
        for key in list(self.started):
            if key == filename:
                self.started.pop(key, None)
            elif episode_number and key in {
                f"episode_{episode_number}",
                f"episode_{episode_number}.mkv",
            }:
                self.started.pop(key, None)
            elif episode_number and key.startswith(f"episode_{episode_number}."):
                self.started.pop(key, None)

    def get_addon_url(self, filename: str) -> str:
        if filename in self.items:
            return self.items[filename].addon_url
        return ""

    def get_server(self, filename: str) -> str:
        """Return the addon URL that served this file, or fallback to addon_url."""
        if filename not in self.items:
            return ""
        record = self.items[filename]
        return record.server or record.addon_url

    def mark_failed(self, item_key: str, error: str, attempt: int | None = None):
        """Record a failed attempt for *item_key*.

        When ``attempt`` is ``None`` (the default for new callers) the
        existing attempt counter is incremented so that the field tracks
        **consecutive failures across runs** — every run that fails the
        same episode pushes the counter one higher. A successful
        download clears the entry (see :meth:`add_download` →
        :meth:`_clear_failed_for_filename`), so the counter restarts at
        zero on the next failure.

        The legacy ``attempt``-as-fixed-value form is preserved for
        back-compat: callers that still pass an explicit integer (the
        legacy ``downloader.py`` path and the ``max_attempts`` call on
        exhaustion) record their value — but only if it is **greater
        than** the existing counter. A smaller explicit value is
        ignored so a one-off ``mark_failed(key, error, 1)`` from a
        transient within-run retry cannot silently shrink the cross-run
        budget the missing-list scan relies on.
        """
        existing = self.failed_items.get(item_key, {}).get("attempt", 0)
        if attempt is None:
            attempt = existing + 1
        elif attempt < existing:
            attempt = existing
        self.failed_items[item_key] = {
            "error": error,
            "attempt": attempt,
            "timestamp": datetime.now().isoformat(),
        }
        # A permanent failure means the .part file has been cleaned up
        # (see _delete_invalid_download in stream_download). The episode
        # is no longer "in progress".
        self.clear_in_progress(item_key)

    def mark_in_progress(self, item_key: str, part_bytes: int = 0) -> None:
        """Record that *item_key*'s download is currently in progress.

        Called when the downloader opens a ``.part`` file and starts
        writing bytes. The marker is cleared by :meth:`add_download`
        (success) and :meth:`mark_failed` (permanent failure) and by
        the next :meth:`prune_stale_in_progress` pass if the
        corresponding ``.part`` file disappears.
        """
        self.in_progress[item_key] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "part_bytes": int(part_bytes),
        }

    def clear_in_progress(self, item_key: str) -> None:
        self.in_progress.pop(item_key, None)

    def is_in_progress(self, item_key: str) -> bool:
        return item_key in self.in_progress

    def prune_stale_in_progress(
        self,
        keep_keys: set[str] | None = None,
        folder_path: Path | None = None,
        config=None,
    ) -> list[str]:
        """Remove ``in_progress`` markers that are no longer valid.

        A marker is stale when ANY of the following is true:
        - The corresponding ``.part`` file is missing on disk
        - The marker is older than :data:`IN_PROGRESS_MAX_AGE_SECONDS`
        - The marker is NOT in *keep_keys* (the live scan of .part files
          that the downloader is about to resume)

        Returns the list of keys that were removed.
        """
        now = datetime.now(timezone.utc)
        removed: list[str] = []
        for key in list(self.in_progress):
            entry = self.in_progress.get(key)
            if not entry:
                continue
            if keep_keys is not None and key in keep_keys:
                continue
            # Age check
            try:
                stamp = datetime.fromisoformat(str(entry.get("started_at", "")))
            except (TypeError, ValueError):
                stamp = None
            if stamp is not None:
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if (now - stamp) > timedelta(seconds=IN_PROGRESS_MAX_AGE_SECONDS):
                    self.in_progress.pop(key, None)
                    removed.append(key)
                    continue
            # Filesystem check
            if folder_path is not None:
                part_path = folder_path / f"{key}.part"
                if not part_path.exists():
                    self.in_progress.pop(key, None)
                    removed.append(key)
        return removed

    def mark_preflight_indeterminate(self, item_key: str, error: str) -> None:
        """Record a transient preflight 'no working addons' outcome.

        Unlike :meth:`mark_failed`, this entry does not count toward
        ``MAX_DOWNLOAD_ATTEMPTS`` and is automatically cleared by
        :meth:`is_preflight_indeterminate` once the TTL has elapsed.
        """
        self.preflight_indeterminate[item_key] = {
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def is_preflight_indeterminate(self, item_key: str) -> bool:
        """Return True if the preflight for this key was rate-limit-blocked
        within the last :data:`PREFLIGHT_INDETERMINATE_TTL_SECONDS` seconds.
        """
        entry = self.preflight_indeterminate.get(item_key)
        if not entry:
            return False
        try:
            stamp = datetime.fromisoformat(str(entry.get("timestamp", "")))
        except (TypeError, ValueError):
            return False
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - stamp
        if age > timedelta(seconds=PREFLIGHT_INDETERMINATE_TTL_SECONDS):
            self.preflight_indeterminate.pop(item_key, None)
            return False
        return True

    def clear_preflight_indeterminate(self, item_key: str | None = None) -> None:
        if item_key is None:
            self.preflight_indeterminate.clear()
        else:
            self.preflight_indeterminate.pop(item_key, None)

    def mark_started(
        self,
        item_key: str,
        server: str | None = None,
        bytes_at_first_arrival: int = 0,
    ) -> None:
        """Record that *item_key*'s download produced real bytes from the network.

        Called from the per-episode / per-movie pipeline the first time
        ``on_bytes(downloaded_bytes, total_bytes)`` reports
        ``downloaded_bytes > 0``. The marker is what powers the
        "priority list": on the next run, items in this list are
        attempted BEFORE never-attempted items because the seeds that
        served them yesterday are still the most likely source today.

        Distinct from :meth:`mark_in_progress`, which is set BEFORE
        the download attempt (and may therefore be set even when no
        bytes ever flow). The "started" signal is strictly stronger.

        ``server`` is the addon URL that produced the stream, if
        known. It is informational only — the download path does not
        skip the addon search based on this hint, because seeds may
        rotate between attempts.

        ``bytes_at_first_arrival`` is informational only — it captures
        how many bytes were on disk the moment the marker was set,
        useful for diagnostics but not consulted by the priority logic.

        Repeated calls within the same run are no-ops: the marker is
        overwritten with the latest values but the timestamp is the
        original one so the TTL window is anchored to the FIRST real
        byte arrival.
        """
        existing = self.started.get(item_key)
        if existing is not None:
            # Already set in a prior run (or earlier in this run) —
            # preserve the original timestamp so the TTL is anchored
            # to when bytes first flowed. Refresh the server hint and
            # byte count so the most recent attempt's metadata is
            # visible to operators inspecting the state file.
            if server and not existing.get("server"):
                existing["server"] = server
            if bytes_at_first_arrival and not existing.get("bytes_at_first_arrival"):
                existing["bytes_at_first_arrival"] = bytes_at_first_arrival
            return
        self.started[item_key] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "server": server or "",
            "bytes_at_first_arrival": int(bytes_at_first_arrival),
        }

    def is_started(self, item_key: str) -> bool:
        """Return True when *item_key* has a live "started" marker.

        Honours the :data:`STARTED_MAX_AGE_SECONDS` TTL — markers older
        than that are dropped on read so stale signals do not crowd
        out fresh episodes.
        """
        entry = self.started.get(item_key)
        if not entry:
            return False
        try:
            stamp = datetime.fromisoformat(str(entry.get("started_at", "")))
        except (TypeError, ValueError):
            return False
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - stamp) > timedelta(
            seconds=STARTED_MAX_AGE_SECONDS
        ):
            self.started.pop(item_key, None)
            return False
        return True

    def clear_started(self, item_key: str) -> None:
        """Drop the "started" marker for *item_key*.

        Called when the download succeeds (the item is no longer
        missing — a stale marker would just be noise), when the
        corresponding final ``.mkv`` is found on disk, and when the
        item is removed from the season's metadata.
        """
        self.started.pop(item_key, None)

    def prune_stale_started(
        self,
        keep_keys: set[str] | None = None,
        folder_path: Path | None = None,
        config=None,
    ) -> list[str]:
        """Drop "started" markers that are no longer actionable.

        A marker is stale when ANY of the following holds:

        - Older than :data:`STARTED_MAX_AGE_SECONDS` (the seeds almost
          certainly changed by now).
        - The corresponding final ``.mkv`` exists on disk (the
          download actually succeeded and the marker is misleading).
        - The corresponding episode is no longer in
          ``config.available_episodes`` (the metadata service
          trimmed it from the season — do not silently re-admit it).
        - The episode number cannot be derived from a non-``keep_keys``
          key and the caller asked for ``keep_keys`` filtering
          (symmetric with :meth:`prune_stale_in_progress`).

        Returns the list of keys that were removed.
        """
        now = datetime.now(timezone.utc)
        removed: list[str] = []
        available_episodes: set[int] | None = None
        if config is not None and getattr(config, "available_episodes", None):
            try:
                available_episodes = {int(ep) for ep in config.available_episodes}
            except (TypeError, ValueError):
                available_episodes = None

        for key in list(self.started):
            if keep_keys is not None and key not in keep_keys:
                self.started.pop(key, None)
                removed.append(key)
                continue
            entry = self.started.get(key)
            if not entry:
                continue
            # Age check — TTL is anchored to first real byte arrival.
            try:
                stamp = datetime.fromisoformat(str(entry.get("started_at", "")))
            except (TypeError, ValueError):
                stamp = None
            if stamp is not None:
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if (now - stamp) > timedelta(seconds=STARTED_MAX_AGE_SECONDS):
                    self.started.pop(key, None)
                    removed.append(key)
                    continue
            # Episode-membership check — never re-admit an episode that
            # the metadata service has removed from the season.
            if available_episodes is not None and key.startswith("episode_"):
                suffix = key[len("episode_"):]
                if suffix.isdigit():
                    if int(suffix) not in available_episodes:
                        self.started.pop(key, None)
                        removed.append(key)
                        continue
            # On-disk completion check — if the final file exists, the
            # download actually succeeded and the marker is misleading.
            if folder_path is not None and key.startswith("episode_"):
                suffix = key[len("episode_"):]
                if suffix.isdigit():
                    expected_mkv = folder_path / f"episode_{suffix}.mkv"
                    if expected_mkv.exists():
                        self.started.pop(key, None)
                        removed.append(key)
                        continue
        return removed

    def is_downloaded(self, filename: str) -> bool:
        return filename in self.items

    def was_attempted(self, item_key: str) -> int:
        if item_key in self.failed_items:
            return self.failed_items[item_key]["attempt"]
        return 0


_EPISODE_NUMBER_RE = re.compile(r"s\d+e(\d+)", re.IGNORECASE)


def _episode_number_from_stem(stem: str) -> int | None:
    """Extract the season-relative episode number from a filename stem.

    Examples:
        ``Rick and Morty_s09e10`` -> 10
        ``Bleach_s04e01``        -> 1
        ``Michael``              -> None
    """
    match = _EPISODE_NUMBER_RE.search(stem)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def load_state(folder_path: Path) -> DownloadState:
    """Load state from folder, creating default if missing."""
    state_path = folder_path / ".download-state.json"
    if not state_path.exists():
        return DownloadState(folder_path=folder_path)
    try:
        with open(state_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        from py_stremio.components.errors import report_error

        report_error(
            context=f"load_state({folder_path.name})",
            exception=exc,
            url=str(state_path),
        )
        # Backup and return fresh state — don't let a corrupted file
        # block the entire pipeline
        backup = state_path.with_suffix(".download-state.json.corrupt")
        try:
            import shutil
            shutil.copy2(state_path, backup)
        except OSError:
            pass
        return DownloadState(folder_path=folder_path)
    items = {}
    for filename, record_data in data.get("items", {}).items():
        # Backward compatibility: old states only have addon_url.
        # Populate server from addon_url if server is missing.
        if "server" not in record_data and record_data.get("addon_url"):
            record_data["server"] = record_data["addon_url"]
        items[filename] = DownloadRecord(**record_data)
    return DownloadState(
        folder_path=folder_path,
        items=items,
        last_scan=data.get("last_scan", ""),
        total_downloaded=data.get("total_downloaded", 0),
        failed_items=data.get("failed_items", {}),
        preflight_indeterminate=data.get("preflight_indeterminate", {}),
        in_progress=data.get("in_progress", {}),
        started=data.get("started", {}),
    )


def save_state(folder_path: Path, state: DownloadState) -> None:
    """Save state to file."""
    state_path = folder_path / ".download-state.json"
    data = {
        "items": {k: asdict(v) for k, v in state.items.items()},
        "last_scan": state.last_scan,
        "total_downloaded": state.total_downloaded,
        "failed_items": state.failed_items,
        "preflight_indeterminate": state.preflight_indeterminate,
        "in_progress": state.in_progress,
        "started": state.started,
    }
    atomic_write_json(state_path, data, indent=2)
