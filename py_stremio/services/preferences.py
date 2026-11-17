"""Persist dashboard preferences and service credentials in the local catalog."""
from __future__ import annotations

import json
import os

from py_stremio.components.configs.app_settings import settings
from py_stremio.storage.catalog import get_runtime_setting, set_runtime_setting
from py_stremio.storage.compat import get_storage_backend
from py_stremio.storage.db import get_db_path, init_db


_PREFERENCE_KEYS = {
    "download_threads": "DOWNLOAD_THREADS",
    "internet_speed_limit": "INTERNET_SPEED_LIMIT",
    "preferred_languages": "PREFERRED_LANGUAGES",
    "max_download_attempts": "MAX_DOWNLOAD_ATTEMPTS",
    "configs_cache_hours": "CONFIGS_CACHE_HOURS",
    "library_layout": "",
}
_SECRET_SETTINGS = {
    "real_debrid": "REAL_DEBRID_API_KEY",
    "premiumize": "PREMIUMIZE_API_KEY",
    "alldebrid": "ALLDEBRID_API_KEY",
    "hdhub": "HDHUB_DEBRID_KEY",
    "torrent_proxy": "TORRENT_PROXY_URL",
}
_LAYOUT_ALIASES = {"poster": "cinematic", "compact": "smart"}
_LIBRARY_LAYOUTS = {"cinematic", "streaming", "backdrop", "mosaic", "editorial", "smart"}


def load_saved_preferences() -> None:
    if not get_db_path().is_file():
        return
    init_db()
    for key, setting_name in _PREFERENCE_KEYS.items():
        value = get_runtime_setting(f"ui_pref_{key}")
        if value is None:
            continue
        try:
            parsed = json.loads(value)
            if key == "download_threads":
                parsed = max(1, min(16, int(parsed)))
            elif key == "internet_speed_limit":
                parsed = max(1, min(100, int(parsed)))
            elif key == "max_download_attempts":
                parsed = max(0, min(50, int(parsed)))
            elif key == "configs_cache_hours":
                parsed = max(0.0, min(168.0, float(parsed)))
            elif key == "preferred_languages":
                parsed = [str(language).strip() for language in parsed if str(language).strip()]
            elif key == "library_layout":
                parsed = _LAYOUT_ALIASES.get(parsed, parsed)
                if parsed not in _LIBRARY_LAYOUTS:
                    continue
            if setting_name:
                setattr(settings, setting_name, parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    for key, setting_name in _SECRET_SETTINGS.items():
        value = get_runtime_setting(f"ui_secret_{key}")
        cleared = get_runtime_setting(f"ui_secret_cleared_{key}") == "1"
        if value is not None:
            os.environ[setting_name] = value
            setattr(settings, setting_name, value)
        elif cleared:
            os.environ[setting_name] = ""
            setattr(settings, setting_name, None)


def save_preferences(values: dict) -> dict:
    init_db()
    for key, value in values.items():
        if key not in _PREFERENCE_KEYS or value is None:
            continue
        if key == "download_threads":
            value = max(1, min(16, int(value)))
        elif key == "internet_speed_limit":
            value = max(1, min(100, int(value)))
        elif key == "max_download_attempts":
            value = max(0, min(50, int(value)))
        elif key == "configs_cache_hours":
            value = max(0.0, min(168.0, float(value)))
        elif key == "preferred_languages":
            value = [str(language).strip() for language in value if str(language).strip()]
        elif key == "library_layout":
            value = _LAYOUT_ALIASES.get(value, value)
            if value not in _LIBRARY_LAYOUTS:
                continue
        set_runtime_setting(f"ui_pref_{key}", json.dumps(value))
        if _PREFERENCE_KEYS[key]:
            setattr(settings, _PREFERENCE_KEYS[key], value)
    return get_preferences()


def get_preferences() -> dict:
    library_layout = get_runtime_setting("ui_pref_library_layout", json.dumps("cinematic"))
    try:
        library_layout = json.loads(library_layout)
    except (TypeError, json.JSONDecodeError):
        library_layout = "cinematic"
    library_layout = _LAYOUT_ALIASES.get(library_layout, library_layout)
    if library_layout not in _LIBRARY_LAYOUTS:
        library_layout = "cinematic"
    return {
        "download_threads": settings.DOWNLOAD_THREADS,
        "internet_speed_limit": settings.INTERNET_SPEED_LIMIT,
        "preferred_languages": list(settings.PREFERRED_LANGUAGES),
        "max_download_attempts": settings.MAX_DOWNLOAD_ATTEMPTS,
        "configs_cache_hours": settings.CONFIGS_CACHE_HOURS,
        "library_layout": library_layout,
        "root_folder": str(settings.ROOT_FOLDER),
        "storage_backend": get_storage_backend(),
        "secrets_configured": {
            "real_debrid": bool(settings.REAL_DEBRID_API_KEY),
            "premiumize": bool(settings.PREMIUMIZE_API_KEY),
            "alldebrid": bool(settings.ALLDEBRID_API_KEY),
            "hdhub": bool(settings.HDHUB_DEBRID_KEY),
            "torrent_proxy": bool(settings.TORRENT_PROXY_URL),
        },
    }


def save_service_secrets(values: dict[str, str | None], clear: list[str] | None = None) -> dict:
    for key, secret in values.items():
        if secret is None:
            continue
        setting_name = _SECRET_SETTINGS[key]
        set_runtime_setting(f"ui_secret_{key}", secret)
        _delete_setting(f"ui_secret_cleared_{key}")
        os.environ[setting_name] = secret
        setattr(settings, setting_name, secret)
    for key in clear or []:
        setting_name = _SECRET_SETTINGS[key]
        _delete_setting(f"ui_secret_{key}")
        set_runtime_setting(f"ui_secret_cleared_{key}", "1")
        os.environ[setting_name] = ""
        setattr(settings, setting_name, None)
    return get_preferences()


def _delete_setting(key: str) -> None:
    from py_stremio.storage.db import transaction

    with transaction() as conn:
        conn.execute("DELETE FROM settings_override WHERE key=?", (key,))
