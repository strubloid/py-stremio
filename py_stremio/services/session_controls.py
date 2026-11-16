"""Expose live download controls to the in-process local dashboard."""
from __future__ import annotations

import threading


_lock = threading.RLock()
_active_ui = None


def register_download_ui(ui) -> None:
    global _active_ui
    with _lock:
        _active_ui = ui


def unregister_download_ui(ui) -> None:
    global _active_ui
    with _lock:
        if _active_ui is ui:
            _active_ui = None


def apply_session_controls(**controls) -> dict | None:
    with _lock:
        if _active_ui is None:
            return None
        return _active_ui.apply_controls(**controls)
