"""Tests for the mysql_query config flow."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from aiomysql import Error as MySQLError
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
from tests.conftest import FakePool

USER_INPUT = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_PORT: 3306,
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
    CONF_MYSQL_TIMEOUT: 10,
}


@contextmanager
def patch_driver(**connect_kwargs) -> Iterator[AsyncMock]:
    """Patch the connection test of the flow and the pool of the entry setup.

    A successful flow creates a config entry, which Home Assistant sets up
    right away, so the pool has to be mocked as well.
    """
    connect = AsyncMock(**({"return_value": AsyncMock()} | connect_kwargs))
    with (
        patch("aiomysql.connect", connect),
        patch("aiomysql.create_pool", AsyncMock(return_value=FakePool())),
    ):
        yield connect


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A valid connection creates a config entry."""
    with patch_driver() as mock_connect:
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
    # A single throwaway connection to verify the settings; setting up the
    # created entry builds a pool instead.
    assert mock_connect.call_count == 1


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """A MySQL connection error surfaces as a form error."""
    with patch_driver(side_effect=MySQLError(1045, "Access denied")):
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
    with patch_driver(side_effect=RuntimeError("boom")):
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
    with patch_driver():
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


async def test_options_flow_saves_the_submitted_settings(hass: HomeAssistant) -> None:
    """The submitted settings replace the data of the config entry.

    The settings live in entry.data, not in entry.options, so the options
    flow writes them through async_update_entry and creates an empty options
    entry. An automation reading the entry keeps seeing them where they were.
    """
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**USER_INPUT, CONF_MYSQL_DB: "other_db", CONF_ROW_LIMIT: 500},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_MYSQL_DB] == "other_db"
    assert entry.data[CONF_ROW_LIMIT] == 500
    assert entry.options == {}


async def test_options_flow_invalid_row_limit_falls_back_to_default(
    hass: HomeAssistant,
) -> None:
    """A row limit below one is replaced by the default before saving."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: 500}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_ROW_LIMIT: 0}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_ROW_LIMIT] == DEFAULT_ROW_LIMIT


async def test_options_flow_form_is_prefilled_with_current_settings(
    hass: HomeAssistant,
) -> None:
    """The form opens on the settings the entry is running with."""
    data = {**USER_INPUT, CONF_MYSQL_DB: "current_db", CONF_ROW_LIMIT: 250}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    defaults = {
        key.schema: key.default() for key in result["data_schema"].schema
    }
    assert defaults[CONF_MYSQL_DB] == "current_db"
    assert defaults[CONF_MYSQL_HOST] == USER_INPUT[CONF_MYSQL_HOST]
    assert defaults[CONF_ROW_LIMIT] == 250


async def test_import_flow_creates_entry(hass: HomeAssistant) -> None:
    """Settings from configuration.yaml become a config entry."""
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data=dict(USER_INPUT),
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MySQL: localhost/test_db (Imported)"
    assert result["data"][CONF_MYSQL_DB] == "test_db"


async def test_import_flow_adds_the_default_row_limit(hass: HomeAssistant) -> None:
    """A YAML section without a row limit still gets the default."""
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data=dict(USER_INPUT),
        )
        await hass.async_block_till_done()

    assert result["data"][CONF_ROW_LIMIT] == DEFAULT_ROW_LIMIT


async def test_import_flow_keeps_an_explicit_row_limit(hass: HomeAssistant) -> None:
    """A row limit set in YAML is not overwritten by the default."""
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={**USER_INPUT, CONF_ROW_LIMIT: 42},
        )
        await hass.async_block_till_done()

    assert result["data"][CONF_ROW_LIMIT] == 42


async def test_import_flow_aborts_when_already_configured(
    hass: HomeAssistant,
) -> None:
    """Importing the same host and database twice does not duplicate it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT},
        unique_id="localhost_test_db",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_IMPORT},
        data=dict(USER_INPUT),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
