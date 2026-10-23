"""Tests for the diagnostics of the MySQL Query integration."""

from __future__ import annotations

import json
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.mysql_query.const import CONF_READONLY_CONNECTION
from custom_components.mysql_query.diagnostics import async_get_config_entry_diagnostics
from tests.conftest import FakePool, make_entry, patch_create_pool
from tests.test_init import ENTRY_DATA

REDACTED = "**REDACTED**"


async def _loaded_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a set up entry with fake pool numbers."""
    entry = make_entry(
        {**ENTRY_DATA, CONF_READONLY_CONNECTION: True},
        title="test_db @ localhost",
        unique_id="localhost:3306/test_db",
    )
    entry.add_to_hass(hass)
    with patch_create_pool(FakePool()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entry.runtime_data.pool = SimpleNamespace(minsize=1, maxsize=10, size=3, freesize=2)
    return entry


async def test_the_connection_is_masked(hass: HomeAssistant) -> None:
    """Neither the credentials nor the place of the database are reported."""
    entry = await _loaded_entry(hass)

    result = await async_get_config_entry_diagnostics(hass, entry)

    data = result["entry"]["data"]
    for key in (
        "mysql_host",
        "mysql_port",
        "mysql_username",
        "mysql_password",
        "mysql_db",
    ):
        assert data[key] == REDACTED
    assert result["entry"]["title"] == REDACTED
    assert result["entry"]["unique_id"] == REDACTED


async def test_nothing_of_the_connection_leaks_anywhere(hass: HomeAssistant) -> None:
    """No value of the connection shows up in the output, wherever it is."""
    entry = await _loaded_entry(hass)

    text = json.dumps(await async_get_config_entry_diagnostics(hass, entry))

    for value in ("localhost", "test_user", "test_pass", "test_db"):
        assert f'"{value}"' not in text
        assert value not in text


async def test_the_behaviour_settings_and_the_pool_are_reported(
    hass: HomeAssistant,
) -> None:
    """What decides how calls behave is in, next to the size of the pool."""
    entry = await _loaded_entry(hass)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry"]["options"][CONF_READONLY_CONNECTION] is True
    assert result["entry"]["options"]["mysql_row_limit"] == 10
    assert result["pool"] == {"minimum": 1, "maximum": 10, "open": 3, "idle": 2}


async def test_an_entry_that_is_not_loaded_has_no_pool(hass: HomeAssistant) -> None:
    """Without a running connection there is no pool to describe."""
    entry = make_entry(ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["pool"] is None
