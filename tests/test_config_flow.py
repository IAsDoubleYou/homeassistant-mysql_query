"""Tests for the mysql_query config flow."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from mysql.connector import Error as MySQLError
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysql_query.const import (
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_ROW_LIMIT,
    DEFAULT_ROW_LIMIT,
    DOMAIN,
)

USER_INPUT = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_PORT: 3306,
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
    CONF_MYSQL_TIMEOUT: 10,
}


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A valid connection creates a config entry."""
    with patch("mysql.connector.connect", return_value=MagicMock()) as mock_connect:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MySQL: localhost/test_db"
    assert result["data"][CONF_ROW_LIMIT] == DEFAULT_ROW_LIMIT
    # Called once by the config flow's connection test, and again when HA
    # sets up the newly created config entry (async_setup_entry).
    assert mock_connect.call_count == 2


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """A MySQL connection error surfaces as a form error."""
    with patch(
        "mysql.connector.connect",
        side_effect=MySQLError(msg="Access denied", errno=1045),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass: HomeAssistant) -> None:
    """An unexpected exception surfaces as an unknown form error."""
    with patch("mysql.connector.connect", side_effect=RuntimeError("boom")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_invalid_row_limit_falls_back_to_default(
    hass: HomeAssistant,
) -> None:
    """An invalid row limit is replaced by the default before saving."""
    with patch("mysql.connector.connect", return_value=MagicMock()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_ROW_LIMIT: 0}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ROW_LIMIT] == DEFAULT_ROW_LIMIT


async def test_options_flow_updates_entry(hass: HomeAssistant) -> None:
    """The options flow updates the existing config entry data."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_ROW_LIMIT: 500}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_ROW_LIMIT] == 500
