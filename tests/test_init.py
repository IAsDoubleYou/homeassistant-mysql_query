"""Tests for the mysql_query integration setup and services."""
from __future__ import annotations

from unittest.mock import patch

from aiomysql import Error as MySQLError
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysql_query.const import (
    ATTR_QUERY,
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_USERNAME,
    CONF_ROW_LIMIT,
    DOMAIN,
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
    CONF_ROW_LIMIT: 10,
}


def _select_cursor(rows: list[dict], columns: list[str], **kwargs) -> FakeCursor:
    """Return a cursor that reports a result set for the given columns."""
    return FakeCursor(
        description=[(column,) for column in columns],
        rows=rows,
        rowcount=len(rows),
        **kwargs,
    )


async def _setup_entry(
    hass: HomeAssistant, pool: FakePool, data: dict | None = None
) -> MockConfigEntry:
    """Add and set up a config entry backed by the given fake pool."""
    entry = MockConfigEntry(domain=DOMAIN, data=data or ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch_create_pool(pool):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_setup_entry_connect_failure(hass: HomeAssistant) -> None:
    """A failed connection aborts setup and returns False."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch("aiomysql.create_pool", side_effect=MySQLError(1045, "Access denied")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_execute_service_select_query(hass: HomeAssistant) -> None:
    """The execute service returns rows and metadata for a SELECT."""
    cursor = _select_cursor(rows=[{"id": 1, "name": "test"}], columns=["id", "name"])
    pool = FakePool(FakeConnection(cursor))

    await _setup_entry(hass, pool)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "SELECT * FROM test"},
        blocking=True,
        return_response=True,
    )

    assert response["succeeded"] is True
    assert response["result"] == [{"id": 1, "name": "test"}]
    assert response["column_names"] == ["id", "name"]
    assert response["rows_found"] == 1
    assert response["rows_returned"] == 1
    assert response["rows_affected"] is None
    assert response["statement"] == "SELECT * FROM test"
    assert cursor.closed


async def test_query_service_returns_minimal_payload(hass: HomeAssistant) -> None:
    """The legacy query service only returns the result rows."""
    pool = FakePool(FakeConnection(_select_cursor(rows=[{"id": 1}], columns=["id"])))

    await _setup_entry(hass, pool)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT * FROM test"},
        blocking=True,
        return_response=True,
    )

    assert response == {"result": [{"id": 1}]}


async def test_execute_service_insert_reports_affected_rows(
    hass: HomeAssistant,
) -> None:
    """A non-SELECT statement reports rows_affected and generated_id."""
    # No description means the statement produced no result set.
    cursor = FakeCursor(description=None, rowcount=1, lastrowid=42)
    connection = FakeConnection(cursor, autocommit=False)

    await _setup_entry(hass, FakePool(connection))

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "INSERT INTO test (name) VALUES ('a')"},
        blocking=True,
        return_response=True,
    )

    assert response["succeeded"] is True
    assert response["rows_affected"] == 1
    assert response["generated_id"] == 42
    assert connection.commits == 1


async def test_execute_service_insert_skips_commit_when_autocommit(
    hass: HomeAssistant,
) -> None:
    """An autocommitting connection needs no extra commit round trip."""
    connection = FakeConnection(
        FakeCursor(description=None, rowcount=1), autocommit=True
    )

    await _setup_entry(hass, FakePool(connection))

    await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "INSERT INTO test (name) VALUES ('a')"},
        blocking=True,
        return_response=True,
    )

    assert connection.commits == 0


async def test_execute_service_row_limit_warns_on_truncation(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Exceeding the configured row limit logs a warning."""
    cursor = _select_cursor(rows=[{"id": 1}], columns=["id"], has_more_rows=True)

    await _setup_entry(
        hass, FakePool(FakeConnection(cursor)), data={**ENTRY_DATA, CONF_ROW_LIMIT: 1}
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "SELECT * FROM test"},
        blocking=True,
        return_response=True,
    )

    assert "exceeds the limit" in caplog.text


async def test_execute_service_mysql_error_returns_error_payload(
    hass: HomeAssistant,
) -> None:
    """A MySQL error is captured in the execute response, not raised."""
    cursor = FakeCursor(error=MySQLError(1064, "Syntax error"))

    await _setup_entry(hass, FakePool(FakeConnection(cursor)))

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "BAD SQL"},
        blocking=True,
        return_response=True,
    )

    assert response["succeeded"] is False
    assert response["error"]["errno"] == 1064
    assert response["error"]["message"] == "Syntax error"


async def test_query_service_mysql_error_raises(hass: HomeAssistant) -> None:
    """The legacy query service raises HomeAssistantError on failure."""
    cursor = FakeCursor(error=MySQLError(1064, "Syntax error"))

    await _setup_entry(hass, FakePool(FakeConnection(cursor)))

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_QUERY,
            {ATTR_QUERY: "BAD SQL"},
            blocking=True,
            return_response=True,
        )


async def test_unload_entry_closes_connection(hass: HomeAssistant) -> None:
    """Unloading the entry shuts the pool down and drops the services."""
    pool = FakePool()

    entry = await _setup_entry(hass, pool)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert pool.closed
    assert pool.wait_closed_called
    assert not hass.services.has_service(DOMAIN, SERVICE_QUERY)
    assert entry.state is ConfigEntryState.NOT_LOADED
