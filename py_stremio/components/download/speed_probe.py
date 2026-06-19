"""Resolve and bootstrap the user's maximum download speed setting."""
from __future__ import annotations

import os
from pathlib import Path
import time

import httpx
from dotenv import dotenv_values

_SPEED_TEST_URL = "https://speed.cloudflare.com/__down?bytes=25000000"
_ENV_KEY = "INTERNET_MAX_SPEED_MBPS"


def _parse_speed(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip().strip('"').strip("'")
    if not stripped:
        return None
    try:
        speed = float(stripped)
    except ValueError:
        return None
    return speed if speed > 0 else None


def measure_download_speed_mbps(
    url: str = _SPEED_TEST_URL,
    max_bytes: int = 12_500_000,
    timeout_seconds: float = 15.0,
) -> float:
    """Measure approximate download throughput in megabits/sec.

    The probe downloads at most ``max_bytes`` from a public speed endpoint and
    returns the observed throughput.  It is intentionally short because this is
    only used to seed a missing user setting, not to benchmark the line forever.
    """
    started = time.monotonic()
    downloaded = 0
    with httpx.stream("GET", url, timeout=timeout_seconds, follow_redirects=True) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes(chunk_size=64 * 1024):
            if not chunk:
                continue
            downloaded += len(chunk)
            if downloaded >= max_bytes:
                break
    elapsed = max(0.001, time.monotonic() - started)
    return round((downloaded * 8) / elapsed / 1_000_000, 1)


def _append_env_value(env_path: Path, speed_mbps: float) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    separator = "" if not existing or existing.endswith("\n") else "\n"
    with env_path.open("a", encoding="utf-8") as file:
        file.write(f"{separator}{_ENV_KEY}={speed_mbps:g}\n")


def resolve_max_speed_mbps(
    env_path: str | Path = ".env",
    default_mbps: float = 100.0,
) -> float:
    """Return max Mbps from environment/.env, or measure and persist it once.

    Precedence:
    1. live ``INTERNET_MAX_SPEED_MBPS`` environment variable
    2. existing ``.env`` value
    3. one short download speed probe; append the measured value to ``.env``
    4. ``default_mbps`` if probing fails
    """
    env_speed = _parse_speed(os.getenv(_ENV_KEY))
    if env_speed is not None:
        return env_speed

    path = Path(env_path)
    if path.exists():
        file_speed = _parse_speed(dotenv_values(path).get(_ENV_KEY))
        if file_speed is not None:
            return file_speed

    if os.getenv("PYTEST_CURRENT_TEST") and env_path == ".env":
        return float(default_mbps)

    try:
        measured = measure_download_speed_mbps()
    except Exception:
        return float(default_mbps)

    if measured > 0:
        _append_env_value(path, measured)
        os.environ[_ENV_KEY] = f"{measured:g}"
        return measured

    return float(default_mbps)
