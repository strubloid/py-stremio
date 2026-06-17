"""pytest configuration — disables rate limiter delays and real HTTP calls during tests."""
import os
from unittest.mock import MagicMock

os.environ.setdefault("PY_STREMIO_RATE_LIMIT", "0")

# Mock preflight discovery globally to avoid real HTTP requests in unit tests
from py_stremio.components.addons import addon_search_service as _ass

_ass.preflight_discover_working_addons = MagicMock(return_value=[])
