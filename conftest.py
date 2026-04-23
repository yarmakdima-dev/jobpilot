"""Root conftest.py — Python 3.10 sandbox compatibility shim.

The project targets Python >=3.11 (pyproject.toml).  The CI/dev environment
runs 3.11+.  This shim backfills ``datetime.UTC`` (added in 3.11) so the
test suite runs in 3.10 sandboxes without modifying production code.
"""

import datetime as _dt
import sys

if sys.version_info < (3, 11) and not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc  # type: ignore[attr-defined]
