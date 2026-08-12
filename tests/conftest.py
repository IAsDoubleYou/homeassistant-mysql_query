"""Fixtures for mysql_query tests."""
from __future__ import annotations

import socket
import sys
from collections.abc import Awaitable, Callable, Generator, Sequence
from typing import Any
from unittest.mock import AsyncMock, patch

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


class FakeCursor:
    """Stand-in for an aiomysql DictCursor.

    Only the surface the integration touches is implemented: it is an async
    context manager that executes a statement and hands back prepared rows.
    """

    def __init__(
        self,
        *,
        description: Sequence[tuple] | None = None,
        rows: Sequence[dict[str, Any]] | None = None,
        rowcount: int = 0,
        lastrowid: int = 0,
        has_more_rows: bool = False,
        error: Exception | None = None,
        on_execute: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Configure the result the cursor will report."""
        self.description = description
        self.rows = list(rows or [])
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.has_more_rows = has_more_rows
        self.error = error
        self.on_execute = on_execute
        self.executed: list[str] = []
        # The values bound to each statement, so a test can assert both what
        # was sent and that nothing was bound at all (None).
        self.executed_args: list[Any] = []
        self.closed = False

    async def execute(self, query: str, args: Any = None) -> None:
        """Record the statement and raise the configured error, if any."""
        self.executed.append(query)
        self.executed_args.append(args)
        if self.on_execute is not None:
            await self.on_execute(query)
        if self.error is not None:
            raise self.error

    async def fetchmany(self, size: int) -> list[dict[str, Any]]:
        """Return at most ``size`` rows, like a buffered cursor does."""
        return self.rows[:size]

    async def fetchone(self) -> dict[str, Any] | None:
        """Return a row only when the result set outgrew the row limit."""
        return {"overflow": 1} if self.has_more_rows else None

    async def close(self) -> None:
        """Mark the cursor as closed."""
        self.closed = True

    async def __aenter__(self) -> FakeCursor:
        """Enter the cursor context."""
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        """Close the cursor on leaving the context."""
        await self.close()
        return False


class FakeConnection:
    """Stand-in for a pooled aiomysql connection."""

    def __init__(
        self,
        cursor: FakeCursor | None = None,
        *,
        autocommit: bool = True,
        select_db_errors: dict[str, Exception] | None = None,
    ) -> None:
        """Create a connection handing out ``cursor`` for every cursor call."""
        self.cursor_obj = cursor if cursor is not None else FakeCursor()
        self.autocommit = autocommit
        # Keyed by database name, so a test can fail the switch, the switch
        # back, or both.
        self.select_db_errors = select_db_errors or {}
        self.pings = 0
        self.commits = 0
        self.selected_dbs: list[str] = []
        self.closed = False

    def cursor(self, *cursor_classes: type) -> FakeCursor:
        """Return the prepared cursor; usable as an async context manager."""
        return self.cursor_obj

    def get_autocommit(self) -> bool:
        """Report the autocommit mode the connection was created with."""
        return self.autocommit

    async def ping(self, reconnect: bool = True) -> None:
        """Count the liveness checks the integration performs."""
        self.pings += 1

    async def commit(self) -> None:
        """Count explicit commits."""
        self.commits += 1

    async def select_db(self, database: str) -> None:
        """Record a database switch, or fail when the test asked for it."""
        self.selected_dbs.append(database)
        if (error := self.select_db_errors.get(database)) is not None:
            raise error

    def close(self) -> None:
        """Mark the connection as closed."""
        self.closed = True


class FakePool:
    """Stand-in for an aiomysql connection pool."""

    def __init__(self, connection: FakeConnection | None = None) -> None:
        """Create a pool that always hands out the same connection."""
        self.connection = connection if connection is not None else FakeConnection()
        self.acquired = 0
        self.released = 0
        self.closed = False
        self.wait_closed_called = False

    async def acquire(self) -> FakeConnection:
        """Hand out the pooled connection."""
        self.acquired += 1
        return self.connection

    def release(self, conn: FakeConnection) -> None:
        """Take the connection back into the pool."""
        self.released += 1

    def close(self) -> None:
        """Start closing the pool."""
        self.closed = True

    async def wait_closed(self) -> None:
        """Wait until the pool finished closing."""
        self.wait_closed_called = True


def patch_create_pool(*pools: FakePool) -> Any:
    """Patch aiomysql.create_pool so setups get the given fake pools."""
    if len(pools) == 1:
        return patch("aiomysql.create_pool", AsyncMock(return_value=pools[0]))
    return patch("aiomysql.create_pool", AsyncMock(side_effect=list(pools)))
