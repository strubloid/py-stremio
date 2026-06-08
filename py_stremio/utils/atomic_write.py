"""Crash-safe, thread-safe file persistence helpers."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

_PATH_LOCKS: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)
_PATH_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    """Return a process-local lock for one absolute file path."""
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS[key]


def atomic_write_json(path: Path | str, data: Any, *, indent: int = 2) -> None:
    """Write JSON without truncating the existing file until the new file is complete.

    The write is serialized per path inside this process, written to a temp file
    in the same directory, flushed/fsync'd, then atomically replaced into place.
    If serialization or disk I/O fails part-way through, the previous target file
    is left untouched and the temp file is removed when possible.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(path)

    with lock:
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=str(path.parent),
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
            tmp_name = None
            _fsync_directory(path.parent)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass


def atomic_write_text(path: Path | str, text: str) -> None:
    """Atomically write text to a file with the same locking policy as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(path)

    with lock:
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=str(path.parent),
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
            tmp_name = None
            _fsync_directory(path.parent)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory entry after os.replace."""
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
