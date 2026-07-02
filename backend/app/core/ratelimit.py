"""Global rate limiter (slowapi).

Kept in its own module so route files can decorate handlers without
importing ``app.main`` (that would create an import cycle).

Routes opt in explicitly via ``@limiter.limit("...")``. The default is
no limit — public read endpoints stay unrestricted.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# ``enabled=False`` makes every ``.limit(...)`` decorator a no-op — used
# by the test suite where every request comes from the same TestClient
# host and would otherwise trip the register/login limits within one run.
# Set ``RATELIMIT_ENABLED=0`` (or pytest via ``PYTEST_CURRENT_TEST``) to
# disable.
_ENABLED = (
    os.environ.get("RATELIMIT_ENABLED", "1") == "1"
    and "PYTEST_CURRENT_TEST" not in os.environ
)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    enabled=_ENABLED,
)
