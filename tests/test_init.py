"""Tests for the mysql_query integration setup and services."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from mysql.connector import Error as MySQLError
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

ENTRY_DATA = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_PORT: 3306,
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
    CONF_ROW_LIMIT: 10,
}


def _make_select_cursor(rows: list[dict], columns: list[str]) -> MagicMock:
    cursor = MagicMock(name="cursor")
    cursor.with_rows = True
    cursor.column_names = columns
    cursor.fetchmany.return_value = rows
    cursor.fetchone.return_value = None
    cursor.rowcount = len(rows)
    cursor.lastrowid = 0
    cursor.statement = "SELECT * FROM test"
    return cursor


async def _setup_entry(
    hass: HomeAssistant, cnx: MagicMock, data: dict | None = None
) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=data or ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch("mysql.connector.connect", return_value=cnx):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_setup_entry_connect_failure(hass: HomeAssistant) -> None:
    """A failed connection aborts setup and returns False."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch(
        "mysql.connector.connect",
        side_effect=MySQLError(msg="Access denied", errno=1045),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_execute_service_select_query(hass: HomeAssistant) -> None:
    """The execute service returns rows and metadata for a SELECT."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    cursor = _make_select_cursor(
        rows=[{"id": 1, "name": "test"}], columns=["id", "name"]
    )
    cnx.cursor.return_value = cursor

    await _setup_entry(hass, cnx)

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
    cursor.close.assert_called_once()


async def test_query_service_returns_minimal_payload(hass: HomeAssistant) -> None:
    """The legacy query service only returns the result rows."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    cursor = _make_select_cursor(rows=[{"id": 1}], columns=["id"])
    cnx.cursor.return_value = cursor

    await _setup_entry(hass, cnx)

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
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    cursor = MagicMock(name="cursor")
    cursor.with_rows = False
    cursor.rowcount = 1
    cursor.lastrowid = 42
    cursor.statement = "INSERT INTO test (name) VALUES ('a')"
    cnx.cursor.return_value = cursor

    await _setup_entry(hass, cnx)

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
    cnx.commit.assert_called_once()


async def test_execute_service_row_limit_warns_on_truncation(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Exceeding the configured row limit logs a warning."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    cursor = _make_select_cursor(rows=[{"id": 1}], columns=["id"])
    cursor.fetchone.return_value = {"id": 2}
    cnx.cursor.return_value = cursor

    await _setup_entry(hass, cnx, data={**ENTRY_DATA, CONF_ROW_LIMIT: 1})

    await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "SELECT * FROM test"},
        blocking=True,
        return_response=True,
    )

    assert "overschrijdt de limiet" in caplog.text


async def test_execute_service_mysql_error_returns_error_payload(
    hass: HomeAssistant,
) -> None:
    """A MySQL error is captured in the execute response, not raised."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    cnx.cursor.side_effect = MySQLError(msg="Syntax error", errno=1064)

    await _setup_entry(hass, cnx)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE,
        {ATTR_QUERY: "BAD SQL"},
        blocking=True,
        return_response=True,
    )

    assert response["succeeded"] is False
    assert response["error"]["errno"] == 1064


async def test_query_service_mysql_error_raises(hass: HomeAssistant) -> None:
    """The legacy query service raises HomeAssistantError on failure."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    cnx.cursor.side_effect = MySQLError(msg="Syntax error", errno=1064)

    await _setup_entry(hass, cnx)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_QUERY,
            {ATTR_QUERY: "BAD SQL"},
            blocking=True,
            return_response=True,
        )


async def test_unload_entry_closes_connection(hass: HomeAssistant) -> None:
    """Unloading the entry closes the underlying MySQL connection."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True

    entry = await _setup_entry(hass, cnx)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    cnx.close.assert_called_once()
    assert entry.state is ConfigEntryState.NOT_LOADED
