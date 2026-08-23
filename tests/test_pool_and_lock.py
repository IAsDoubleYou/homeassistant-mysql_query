"""Tests for the connection pool and the per-entry concurrency lock."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from aiomysql import Error as MySQLError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.mysql_query.const import (
    ATTR_CONFIG_ENTRY,
    ATTR_DB4QUERY,
    ATTR_QUERY,
    CONF_AUTOCOMMIT,
    CONF_MYSQL_CHARSET,
    CONF_MYSQL_COLLATION,
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_ROW_LIMIT,
    DOMAIN,
    POOL_MAX_SIZE,
    POOL_MIN_SIZE,
    POOL_RECYCLE_SECONDS,
    SERVICE_EXECUTE,
    SERVICE_QUERY,
)
from tests.conftest import FakeConnection, FakeCursor, FakePool, patch_create_pool

ENTRY_DATA = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_PORT: 3306,
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
    CONF_MYSQL_TIMEOUT: 7,
    CONF_ROW_LIMIT: 10,
}


def _cursor(**kwargs) -> FakeCursor:
    """Return a cursor reporting a single-column result set."""
    return FakeCursor(description=[("id",)], rows=[{"id": 1}], rowcount=1, **kwargs)


async def _setup_entry(
    hass: HomeAssistant, pool: FakePool, data: dict | None = None
) -> MockConfigEntry:
    """Add and set up a config entry backed by the given fake pool."""
    entry = MockConfigEntry(domain=DOMAIN, data=data or ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch_create_pool(pool):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _call(hass: HomeAssistant, query: str, **extra) -> asyncio.Task:
    """Fire a query service call as a task, so calls can overlap."""
    return hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            SERVICE_QUERY,
            {ATTR_QUERY: query, **extra},
            blocking=True,
            return_response=True,
        )
    )


async def test_pool_is_created_with_the_configured_settings(
    hass: HomeAssistant,
) -> None:
    """Setup builds one bounded, recycling pool from the entry settings."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            **ENTRY_DATA,
            CONF_MYSQL_CHARSET: "utf8mb4",
            CONF_MYSQL_COLLATION: "utf8mb4_unicode_ci",
            CONF_AUTOCOMMIT: False,
        },
    )
    entry.add_to_hass(hass)

    create_pool = AsyncMock(return_value=FakePool())
    with patch("aiomysql.create_pool", create_pool):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    create_pool.assert_called_once()
    kwargs = create_pool.call_args.kwargs
    assert kwargs["host"] == "localhost"
    assert kwargs["port"] == 3306
    assert kwargs["user"] == "test_user"
    assert kwargs["db"] == "test_db"
    assert kwargs["connect_timeout"] == 7
    assert kwargs["autocommit"] is False
    assert kwargs["charset"] == "utf8mb4"
    assert kwargs["init_command"] == "SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci"
    assert kwargs["minsize"] == POOL_MIN_SIZE
    assert kwargs["maxsize"] == POOL_MAX_SIZE
    assert kwargs["pool_recycle"] == POOL_RECYCLE_SECONDS


async def test_pool_connection_is_reused_across_calls(hass: HomeAssistant) -> None:
    """Repeated service calls borrow from the pool instead of reconnecting."""
    connection = FakeConnection(_cursor())
    pool = FakePool(connection)

    create_pool = AsyncMock(return_value=pool)
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch("aiomysql.create_pool", create_pool):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        for _ in range(3):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_QUERY,
                {ATTR_QUERY: "SELECT 1"},
                blocking=True,
                return_response=True,
            )

    # One pool for the entry, and every call borrowed and returned a
    # connection from it rather than opening its own.
    assert create_pool.call_count == 1
    assert pool.acquired == 3
    assert pool.released == 3
    assert not pool.closed


async def test_pooled_connection_is_pinged_before_use(hass: HomeAssistant) -> None:
    """Each borrowed connection is revived when the server dropped it."""
    connection = FakeConnection(_cursor())

    await _setup_entry(hass, FakePool(connection))

    await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT 1"},
        blocking=True,
        return_response=True,
    )

    assert connection.pings == 1


async def test_pool_is_closed_on_unload(hass: HomeAssistant) -> None:
    """Unloading closes the pool and waits until it is really gone."""
    pool = FakePool(FakeConnection(_cursor()))
    entry = await _setup_entry(hass, pool)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert pool.closed
    assert pool.wait_closed_called


async def test_acquire_timeout_is_reported(hass: HomeAssistant) -> None:
    """A pool that never hands out a connection fails the call cleanly."""
    pool = FakePool(FakeConnection(_cursor()))

    async def never_acquire() -> FakeConnection:
        await asyncio.sleep(3600)
        raise AssertionError("should not be reached")

    await _setup_entry(hass, pool, data={**ENTRY_DATA, CONF_MYSQL_TIMEOUT: 0})
    pool.acquire = never_acquire

    with pytest.raises(HomeAssistantError, match="Timed out"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_QUERY,
            {ATTR_QUERY: "SELECT 1"},
            blocking=True,
            return_response=True,
        )


async def test_db4query_switches_and_restores_the_database(
    hass: HomeAssistant,
) -> None:
    """Another database reuses the pooled connection and is switched back."""
    connection = FakeConnection(_cursor())

    await _setup_entry(hass, FakePool(connection))

    await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT 1", ATTR_DB4QUERY: "other_db"},
        blocking=True,
        return_response=True,
    )

    assert connection.selected_dbs == ["other_db", "test_db"]
    assert not connection.closed


async def test_db4query_drops_connection_when_restore_fails(
    hass: HomeAssistant,
) -> None:
    """A connection that is stuck on the other database never returns clean."""
    # The switch to other_db works, switching back to test_db does not.
    connection = FakeConnection(
        _cursor(), select_db_errors={"test_db": MySQLError(1044, "Denied")}
    )

    await _setup_entry(hass, FakePool(connection))

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "UPDATE t SET a = 1", ATTR_DB4QUERY: "other_db"},
        blocking=True,
        return_response=True,
    )

    # The query itself still succeeded; only the connection is discarded.
    assert response["succeeded"] is True
    assert connection.selected_dbs == ["other_db", "test_db"]
    assert connection.closed


async def test_concurrent_calls_are_serialised_by_the_lock(
    hass: HomeAssistant,
) -> None:
    """A second call waits for the first to finish before it touches MySQL."""
    started: list[str] = []
    finished: list[str] = []
    release_first = asyncio.Event()

    async def on_execute(query: str) -> None:
        started.append(query)
        if query == "SELECT 1":
            # Hold the lock until the test lets go.
            await release_first.wait()
        finished.append(query)

    connection = FakeConnection(_cursor(on_execute=on_execute))
    pool = FakePool(connection)
    await _setup_entry(hass, pool)

    first = _call(hass, "SELECT 1")
    # Let the first call reach the database and block there.
    while not started:
        await asyncio.sleep(0)

    second = _call(hass, "SELECT 2")
    # Give the second call every chance to slip past the first one.
    for _ in range(20):
        await asyncio.sleep(0)

    assert started == ["SELECT 1"], "second call ran while the first held the lock"
    assert pool.acquired == 1

    release_first.set()
    assert (await first)["result"] == [{"id": 1}]
    assert (await second)["result"] == [{"id": 1}]

    # Strictly sequential: the first finished before the second started.
    assert started == ["SELECT 1", "SELECT 2"]
    assert finished == ["SELECT 1", "SELECT 2"]
    assert pool.acquired == 2
    assert pool.released == 2


async def test_lock_is_not_shared_between_config_entries(
    hass: HomeAssistant,
) -> None:
    """Each entry has its own lock, so two databases still run in parallel."""
    started: list[str] = []
    release = asyncio.Event()

    async def on_execute(query: str) -> None:
        started.append(query)
        await release.wait()

    first_pool = FakePool(FakeConnection(_cursor(on_execute=on_execute)))
    second_pool = FakePool(FakeConnection(_cursor(on_execute=on_execute)))

    first_entry = await _setup_entry(hass, first_pool)
    second_entry = await _setup_entry(
        hass, second_pool, data={**ENTRY_DATA, CONF_MYSQL_DB: "other_db"}
    )

    calls = [
        _call(hass, "SELECT 1", **{ATTR_CONFIG_ENTRY: first_entry.entry_id}),
        _call(hass, "SELECT 2", **{ATTR_CONFIG_ENTRY: second_entry.entry_id}),
    ]
    for _ in range(20):
        await asyncio.sleep(0)

    # Both are inside the database call at the same time: the lock of one
    # entry does not hold back the other.
    assert sorted(started) == ["SELECT 1", "SELECT 2"]

    release.set()
    await asyncio.gather(*calls)

    assert first_pool.acquired == 1
    assert second_pool.acquired == 1


async def test_unload_waits_for_a_running_call(hass: HomeAssistant) -> None:
    """The pool is not torn down while a service call is still using it."""
    release = asyncio.Event()
    pool_closed_during_call = []

    async def on_execute(query: str) -> None:
        await release.wait()
        pool_closed_during_call.append(pool.closed)

    pool = FakePool(FakeConnection(_cursor(on_execute=on_execute)))
    entry = await _setup_entry(hass, pool)

    call = _call(hass, "SELECT 1")
    while pool.acquired == 0:
        await asyncio.sleep(0)

    unload = hass.async_create_task(hass.config_entries.async_unload(entry.entry_id))
    for _ in range(20):
        await asyncio.sleep(0)

    assert not pool.closed, "pool was closed while a call was still running"

    release.set()
    await call
    assert await unload

    assert pool_closed_during_call == [False]
    assert pool.closed


async def test_connection_is_returned_after_a_failed_statement(
    hass: HomeAssistant,
) -> None:
    """A statement the server rejects still hands its connection back.

    Every borrowed connection has to reach pool.release(), on the error path
    as much as on the happy one. A connection that is not returned stays
    checked out for good, and once that has happened POOL_MAX_SIZE times the
    pool hands out nothing at all and every later call times out waiting.
    """
    pool = FakePool(FakeConnection(_cursor(error=MySQLError(1146, "No such table"))))

    await _setup_entry(hass, pool)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "DELETE FROM nope"},
        blocking=True,
        return_response=True,
    )

    assert response["succeeded"] is False
    assert response["error"]["errno"] == 1146
    assert pool.acquired == 1
    assert pool.released == 1


async def test_connection_is_returned_when_the_database_switch_fails(
    hass: HomeAssistant,
) -> None:
    """A failed switch to db4query does not swallow the connection."""
    connection = FakeConnection(
        _cursor(), select_db_errors={"other_db": MySQLError(1044, "Denied")}
    )
    pool = FakePool(connection)

    await _setup_entry(hass, pool)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "UPDATE t SET a = 1", ATTR_DB4QUERY: "other_db"},
        blocking=True,
        return_response=True,
    )

    assert response["succeeded"] is False
    assert connection.selected_dbs == ["other_db"]
    assert pool.acquired == 1
    assert pool.released == 1


async def test_connections_are_returned_across_repeated_failures(
    hass: HomeAssistant,
) -> None:
    """Repeated failures do not drain the pool one connection at a time."""
    pool = FakePool(FakeConnection(_cursor(error=MySQLError(1064, "Syntax error"))))

    await _setup_entry(hass, pool)

    for _ in range(POOL_MAX_SIZE + 1):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_EXECUTE,
            {ATTR_QUERY: "DELETE FROM ("},
            blocking=True,
            return_response=True,
        )

    assert pool.acquired == POOL_MAX_SIZE + 1
    assert pool.released == pool.acquired


async def _setup_two_entries(
    hass: HomeAssistant, first: FakePool, second: FakePool
) -> tuple[MockConfigEntry, MockConfigEntry]:
    """Set up two connections, in registry order."""
    first_entry = await _setup_entry(hass, first)
    second_entry = await _setup_entry(
        hass, second, data={**ENTRY_DATA, CONF_MYSQL_DB: "other_db"}
    )
    return first_entry, second_entry


async def test_call_without_config_entry_uses_the_first_connection(
    hass: HomeAssistant,
) -> None:
    """A call that names no connection runs on the first one."""
    first = FakePool(FakeConnection(_cursor()))
    second = FakePool(FakeConnection(_cursor()))

    await _setup_two_entries(hass, first, second)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT 1"},
        blocking=True,
        return_response=True,
    )

    assert first.acquired == 1
    assert second.acquired == 0


async def test_default_connection_survives_a_reload(hass: HomeAssistant) -> None:
    """Reloading a connection does not move the default to another one.

    The connection is picked from the config entry registry, whose order does
    not change when an entry is unloaded and set up again. Reading the order
    from a dict filled during setup would put the reloaded entry last, and
    silently hand later calls to the other connection.
    """
    first = FakePool(FakeConnection(_cursor()))
    second = FakePool(FakeConnection(_cursor()))

    first_entry, _ = await _setup_two_entries(hass, first, second)

    # Reload the connection that calls default to.
    reloaded = FakePool(FakeConnection(_cursor()))
    with patch_create_pool(reloaded):
        assert await hass.config_entries.async_reload(first_entry.entry_id)
        await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT 1"},
        blocking=True,
        return_response=True,
    )

    assert reloaded.acquired == 1, "the default moved to the other connection"
    assert second.acquired == 0


async def test_unloading_one_connection_keeps_the_services(
    hass: HomeAssistant,
) -> None:
    """The services stay registered while another connection is still loaded."""
    first = FakePool(FakeConnection(_cursor()))
    second = FakePool(FakeConnection(_cursor()))

    first_entry, _ = await _setup_two_entries(hass, first, second)

    assert await hass.config_entries.async_unload(first_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_QUERY)
    assert hass.services.has_service(DOMAIN, SERVICE_EXECUTE)

    # The remaining connection is now the one calls default to.
    await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT 1"},
        blocking=True,
        return_response=True,
    )
    assert second.acquired == 1


async def test_unloading_the_last_connection_removes_the_services(
    hass: HomeAssistant,
) -> None:
    """The services are gone once no connection is loaded any more."""
    entry = await _setup_entry(hass, FakePool(FakeConnection(_cursor())))

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.services.has_service(DOMAIN, SERVICE_QUERY)
    assert not hass.services.has_service(DOMAIN, SERVICE_EXECUTE)


async def test_call_on_an_unloaded_connection_is_refused(hass: HomeAssistant) -> None:
    """Naming a connection that is no longer loaded fails the call."""
    first = FakePool(FakeConnection(_cursor()))
    second = FakePool(FakeConnection(_cursor()))

    first_entry, _ = await _setup_two_entries(hass, first, second)

    assert await hass.config_entries.async_unload(first_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match="No database instance available"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_QUERY,
            {ATTR_QUERY: "SELECT 1", ATTR_CONFIG_ENTRY: first_entry.entry_id},
            blocking=True,
            return_response=True,
        )
