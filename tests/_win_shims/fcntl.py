"""No-op stand-in for the POSIX-only stdlib ``fcntl`` module.

Home Assistant's ``runner.py`` unconditionally imports ``fcntl`` for PID-file
locking, which only happens when HA runs as a full daemon - never during
these component-level unit tests. This shim lets the import succeed when
running the test suite on Windows, without touching the venv's site-packages.
On Linux/macOS the real stdlib module is used instead (see conftest.py).
"""

from __future__ import annotations

LOCK_EX = 2
LOCK_NB = 4


def flock(fd: int, operation: int) -> None:
    """No-op replacement; PID-file locking is never exercised by these tests."""
    return
