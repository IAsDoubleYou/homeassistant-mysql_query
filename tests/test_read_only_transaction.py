"""Tests for what query puts around a statement on the server.

The classifier in sql.py only reads the text. The transaction is what makes the
server itself refuse a change, so these tests pin down exactly what is sent, in
which order, and on which paths.
"""

from __future__ import annotations

import asyncio

from aiomysql import Error as MySQLError
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.mysql_query.const import (
    ATTR_DB4QUERY,
    ATTR_QUERY,
    CONF_AUTOCOMMIT,
    CONF_QUERY_TIMEOUT,
    DOMAIN,
    SERVICE_EXECUTE,
    SERVICE_QUERY,
)
from tests.conftest import FakeConnection, FakeCursor, FakePool
from tests.test_init import ENTRY_DATA, _select_cursor, _setup_entry

START = "START TRANSACTION READ ONLY"


async def _call(hass: HomeAssistant, service: str, data: dict) -> dict:
    """Call a service and return its response."""
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def test_query_runs_inside_a_read_only_transaction(hass: HomeAssistant) -> None:
    """The statement sits between the start of the transaction and a rollback."""
    connection = FakeConnection(_select_cursor([{"id": 1}], ["id"]))
    await _setup_entry(hass, FakePool(connection))

    response = await _call(hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT id FROM t"})

    assert response["result"] == [{"id": 1}]
    assert connection.events == [START, "SELECT id FROM t", "ROLLBACK"]


async def test_the_transaction_follows_the_database_switch(
    hass: HomeAssistant,
) -> None:
    """The database is selected first, and put back only after the rollback."""
    connection = FakeConnection(_select_cursor([], ["id"]))
    await _setup_entry(hass, FakePool(connection))

    await _call(
        hass,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT 1", ATTR_DB4QUERY: "other_db"},
    )

    assert connection.events == [
        "USE other_db",
        START,
        "SELECT 1",
        "ROLLBACK",
        "USE test_db",
    ]


async def test_execute_does_not_run_in_a_read_only_transaction(
    hass: HomeAssistant,
) -> None:
    """A write has to be able to write."""
    connection = FakeConnection(_select_cursor([], ["id"]))
    await _setup_entry(hass, FakePool(connection))

    await _call(hass, SERVICE_EXECUTE, {ATTR_QUERY: "DELETE FROM t"})

    assert connection.events == ["DELETE FROM t"]
    assert connection.rollbacks == 0


async def test_a_failed_query_is_still_rolled_back(hass: HomeAssistant) -> None:
    """The transaction is closed on the error path as well."""
    cursor = FakeCursor(error=MySQLError(1064, "Syntax error"))
    connection = FakeConnection(cursor)
    pool = FakePool(connection)
    await _setup_entry(hass, pool)

    with pytest.raises(HomeAssistantError, match="Syntax error"):
        await _call(hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT BAD"})

    assert connection.events == [START, "SELECT BAD", "ROLLBACK"]
    # And it went back to the pool, instead of being dropped with the
    # transaction still open.
    assert pool.released == 1
    assert not connection.closed


async def test_the_server_refusing_a_change_reaches_the_caller(
    hass: HomeAssistant,
) -> None:
    """What the classifier cannot see, the server stops, with its own error.

    A function with side effects passes the text check; error 1792 is what the
    read-only transaction answers when it tries to write.
    """
    cursor = FakeCursor(
        error=MySQLError(1792, "Cannot execute statement in a READ ONLY transaction.")
    )
    connection = FakeConnection(cursor)
    await _setup_entry(hass, FakePool(connection))

    with pytest.raises(HomeAssistantError, match="READ ONLY transaction"):
        await _call(hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT writing_function()"})

    assert connection.rollbacks == 1


async def test_autocommit_off_leaves_nothing_open_after_a_select(
    hass: HomeAssistant,
) -> None:
    """With autocommit off a SELECT opens a transaction of its own.

    aiomysql drops a connection that goes back to the pool with one open, so
    without the rollback the pool lost its connection after every SELECT.
    """
    connection = FakeConnection(_select_cursor([{"id": 1}], ["id"]), autocommit=False)
    pool = FakePool(connection)
    await _setup_entry(hass, pool, data={**ENTRY_DATA, CONF_AUTOCOMMIT: False})

    await _call(hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT id FROM t"})

    assert connection.rollbacks == 1
    assert pool.released == 1
    assert not connection.closed


async def test_a_timeout_drops_the_connection_without_awaiting_it_again(
    hass: HomeAssistant,
) -> None:
    """After the timeout nothing more is asked of a connection that may be hung.

    Rolling back would wait for the very connection that stopped answering, and
    no limit is left to end that wait. Closing it makes the server discard the
    transaction.
    """

    async def hang(query: str) -> None:
        await asyncio.sleep(3600)

    connection = FakeConnection(_select_cursor([], ["id"], on_execute=hang))
    pool = FakePool(connection)
    await _setup_entry(hass, pool, data={**ENTRY_DATA, CONF_QUERY_TIMEOUT: 0})

    with pytest.raises(HomeAssistantError, match="timed out"):
        await _call(hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT 1"})

    assert connection.rollbacks == 0
    assert connection.closed
    # Closed and still released: only release() frees its slot in the pool.
    assert pool.released == 1


async def test_a_timeout_does_not_wait_to_restore_the_database(
    hass: HomeAssistant,
) -> None:
    """The switch back is skipped too: the connection is dropped anyway."""

    async def hang(query: str) -> None:
        await asyncio.sleep(3600)

    connection = FakeConnection(_select_cursor([], ["id"], on_execute=hang))
    await _setup_entry(
        hass, FakePool(connection), data={**ENTRY_DATA, CONF_QUERY_TIMEOUT: 0}
    )

    with pytest.raises(HomeAssistantError):
        await _call(
            hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT 1", ATTR_DB4QUERY: "other_db"}
        )

    assert connection.selected_dbs == ["other_db"]


async def test_a_timeout_while_the_transaction_starts_drops_the_connection(
    hass: HomeAssistant,
) -> None:
    """Cut off before the statement ran, nothing more is asked of the connection.

    Not even the switch back to the database of the connection, which would
    wait on the very connection that just stopped answering.
    """

    async def hang(statement: str) -> None:
        await asyncio.sleep(3600)

    connection = FakeConnection(_select_cursor([], ["id"]))
    connection.on_control = hang
    pool = FakePool(connection)
    await _setup_entry(hass, pool, data={**ENTRY_DATA, CONF_QUERY_TIMEOUT: 0})

    with pytest.raises(HomeAssistantError, match="timed out"):
        await _call(
            hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT 1", ATTR_DB4QUERY: "other_db"}
        )

    assert connection.events == ["USE other_db", START]
    assert connection.closed
    # Closed and still released: only release() frees its slot in the pool.
    assert pool.released == 1


@pytest.mark.parametrize(
    ("service", "statement", "events"),
    [
        (SERVICE_QUERY, "SELECT 1", ["USE other_db", START, "SELECT 1"]),
        (SERVICE_EXECUTE, "DELETE FROM t", ["USE other_db", "DELETE FROM t"]),
    ],
)
async def test_a_call_cancelled_by_its_caller_drops_the_connection(
    hass: HomeAssistant, service: str, statement: str, events: list[str]
) -> None:
    """A caller that stops waiting leaves the statement in flight.

    An automation that is stopped, or Home Assistant shutting down, cancels
    the call while the statement is still on the wire. That is not a timeout
    of the integration, but it leaves the connection in the same state:
    handing it back would let the next call read the leftovers.
    """
    started = asyncio.Event()

    async def hang(query: str) -> None:
        started.set()
        await asyncio.sleep(3600)

    connection = FakeConnection(_select_cursor([], ["id"], on_execute=hang))
    pool = FakePool(connection)
    await _setup_entry(hass, pool)

    call = hass.async_create_task(
        _call(hass, service, {ATTR_QUERY: statement, ATTR_DB4QUERY: "other_db"})
    )
    await started.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call

    # Nothing more was sent on it: no rollback, no switch back.
    assert connection.events == events
    assert connection.closed
    # Closed and still released: only release() frees its slot in the pool.
    assert pool.released == 1


async def test_a_connection_that_cannot_roll_back_is_dropped(
    hass: HomeAssistant,
) -> None:
    """The result still arrives, but the connection does not go back to the pool."""
    connection = FakeConnection(_select_cursor([{"id": 1}], ["id"]))
    connection.rollback_error = MySQLError(2013, "Lost connection")
    pool = FakePool(connection)
    await _setup_entry(hass, pool)

    response = await _call(hass, SERVICE_QUERY, {ATTR_QUERY: "SELECT id FROM t"})

    assert response["result"] == [{"id": 1}]
    assert connection.closed


@pytest.mark.parametrize(
    "statement",
    [
        "WITH c AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT * FROM c)",
        "with recursive c(n) as (select 1) delete from t",
        "WITH c AS (SELECT id FROM t) UPDATE t JOIN c USING (id) SET x = 1",
        "SELECT * FROM t INTO OUTFILE '/tmp/x'",
        "SELECT 1 /*! INTO OUTFILE '/tmp/x' */",
    ],
)
async def test_query_refuses_a_write_behind_a_read_looking_start(
    hass: HomeAssistant, statement: str
) -> None:
    """Refused before anything reaches the database, and execute takes it."""
    connection = FakeConnection(_select_cursor([], ["id"]))
    pool = FakePool(connection)
    await _setup_entry(hass, pool)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_QUERY, {ATTR_QUERY: statement})

    assert err.value.translation_key == "write_via_query"
    assert pool.acquired == 0

    response = await _call(hass, SERVICE_EXECUTE, {ATTR_QUERY: statement})
    assert response["succeeded"] is True
