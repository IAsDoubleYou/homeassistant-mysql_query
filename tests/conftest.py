"""Fixtures for mysql_query tests."""
from __future__ import annotations

import socket
import sys
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

# On Linux/macOS (e.g. CI) this file isn't needed: the stdlib "fcntl" module
# that homeassistant.runner imports exists natively there. On Windows it
# doesn't, so run tests with tests/_win_shims on PYTHONPATH, e.g.:
#   PYTHONPATH=tests/_win_shims pytest
# pytest's setuptools-entrypoint plugin autoloading (which triggers that
# import) runs before any conftest.py, so this can't be done from here.

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":
    # pytest_socket (enabled by pytest_homeassistant_custom_component) blocks
    # socket.socket while allowing AF_UNIX. asyncio's self-pipe uses
    # socket.socketpair(), which is a real AF_UNIX pair on POSIX but falls back
    # to a loopback TCP pair on Windows - so creating any event loop is blocked
    # there. Let socketpair() through using the unpatched socket class; it
    # never leaves the machine and is unrelated to what the guard protects.
    _real_socket = socket.socket
    _stdlib_socketpair = socket.socketpair

    def _unguarded_socketpair(*args: object, **kwargs: object) -> tuple:
        """Build asyncio's self-pipe with the real, unguarded socket class."""
        guarded = socket.socket
        socket.socket = _real_socket  # type: ignore[misc]
        try:
            return _stdlib_socketpair(*args, **kwargs)
        finally:
            socket.socket = guarded  # type: ignore[misc]

    socket.socketpair = _unguarded_socketpair  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Enable loading of custom_components/mysql_query for every test."""
    yield


@pytest.fixture
def mock_mysql_connection() -> MagicMock:
    """Return a mocked, already-connected MySQL connection."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    return cnx
