"""job_runs logging — stopgap JSONL store for scheduled run records.

The full plan (see ``plan.md``) replaces this with the SQLite catalog;
until then the JSONL file is append-only, which matches the
single-writer cron design (``flock`` in the wrapper drops concurrent
runs, and the wrapper writes the ``skipped`` records itself).

Record shape::

    {
      "job": "download",
      "started_at": "2026-09-24T00:10:00+00:00",
      "ended_at": "2026-09-24T00:12:03+00:00",
      "status": "ok" | "failed" | "interrupted" | "skipped",
      "error": "...",            # failed/interrupted only
      "skipped_reason": "..."    # skipped only
    }
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def job_runs_path() -> Path:
    """Return the JSONL file path.

    Override with ``PY_STREMIO_JOB_LOG``; otherwise ``$XDG_DATA_HOME``
    (fallback ``~/.local/share``) plus ``py-stremio/job-runs.jsonl``.
    The wrapper writes skips to the same path so every record — real
    runs and lock-drops — ends up in one place.
    """
    override = os.environ.get("PY_STREMIO_JOB_LOG")
    if override:
        return Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "py-stremio" / "job-runs.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_job_run(record: dict) -> Path:
    """Append one JSON record to the job-runs log. Returns the file path."""
    path = job_runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_job_runs(limit: int = 200) -> list[dict]:
    """Read the most recent job-run records, newest first."""
    path = job_runs_path()
    if not path.is_file():
        return []
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    records.reverse()  # file is oldest-first
    return records[:limit]


@contextmanager
def job_run(job: str) -> Iterator[None]:
    """Record start/end for a scheduled job.

    Status is ``ok``, ``failed`` (an exception propagated), or
    ``interrupted`` (cooperative shutdown was requested — e.g. the
    ``[Q]`` control or Ctrl+C surfaced by :meth:`AppService.run`).
    """
    from py_stremio.utils.cancellation import shutdown_requested

    started = _now_iso()
    status = "ok"
    error: str | None = None
    try:
        yield
    except KeyboardInterrupt:
        status = "interrupted"
        error = "KeyboardInterrupt"
        raise
    except BaseException as exc:  # noqa: BLE001 — record, then re-raise
        status = "failed"
        from py_stremio.components.errors.error_reporter import redact_url

        error = redact_url(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        # AppService.run swallows KeyboardInterrupt internally but sets
        # the shutdown flag — detect it here so the run is recorded as
        # ``interrupted`` rather than a clean ``ok``.
        if status == "ok" and shutdown_requested():
            status = "interrupted"
        record: dict = {
            "job": job,
            "started_at": started,
            "ended_at": _now_iso(),
            "status": status,
        }
        if error:
            record["error"] = error
        try:
            append_job_run(record)
        except OSError:
            # Logging must never break the underlying run.
            pass
        try:
            from py_stremio.storage.catalog import record_job_run

            record_job_run(
                job,
                status,
                record["started_at"],
                record["ended_at"],
                detail=error,
            )
        except Exception:
            pass
