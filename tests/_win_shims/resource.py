"""No-op stand-in for the POSIX-only stdlib ``resource`` module.

homeassistant.util.resource imports this to raise the open file descriptor
limit at daemon startup - never exercised during these component-level unit
tests. See fcntl.py in this same directory for the full rationale.
"""

from __future__ import annotations

RLIMIT_NOFILE = 7


def getrlimit(resource: int) -> tuple[int, int]:
    """Return a permissive placeholder (soft, hard) limit pair."""
    return (1024, 1024)


def setrlimit(resource: int, limits: tuple[int, int]) -> None:
    """No-op replacement; file-descriptor limits aren't touched by these tests."""
    return
