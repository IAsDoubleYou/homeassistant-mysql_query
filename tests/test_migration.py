"""Tests for the migration of config entries to version 2, minor version 2."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.mysql_query.const import (
    CONF_AUTOCOMMIT,
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_USERNAME,
    CONF_QUERY_TIMEOUT,
    CONF_READONLY_CONNECTION,
    CONF_ROW_LIMIT,
    CONF_USE_TLS,
    DEFAULT_ROW_LIMIT,
    DOMAIN,
    ENTRY_MINOR_VERSION,
    ENTRY_VERSION,
    SERVICE_EXECUTE,
)
from tests.conftest import FakePool, patch_create_pool

CONNECTION = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_PORT: 3306,
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
    CONF_USE_TLS: True,
}
BEHAVIOUR = {
    CONF_ROW_LIMIT: 250,
    CONF_QUERY_TIMEOUT: 45,
    CONF_AUTOCOMMIT: False,
    CONF_READONLY_CONNECTION: True,
}


async def _migrate(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set an entry up, which migrates it first."""
    entry.add_to_hass(hass)
    with patch_create_pool(FakePool()), _tls_ok():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _tls_ok():
    """Let the TLS check pass; the fake pool cannot answer SHOW STATUS."""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    return patch("custom_components.mysql_query.async_verify_tls", AsyncMock())


async def test_a_version_1_entry_moves_the_four_settings_to_the_options(
    hass: HomeAssistant,
) -> None:
    """Everything that decides how queries behave leaves the data."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, data={**CONNECTION, **BEHAVIOUR})

    await _migrate(hass, entry)

    assert entry.version == ENTRY_VERSION
    assert entry.data == CONNECTION
    assert entry.options == BEHAVIOUR
    assert entry.state is ConfigEntryState.LOADED


async def test_a_version_1_entry_without_those_settings_migrates_cleanly(
    hass: HomeAssistant,
) -> None:
    """Entries from before the settings existed have none to move."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=dict(CONNECTION))

    await _migrate(hass, entry)

    assert entry.version == ENTRY_VERSION
    assert entry.data == CONNECTION
    assert entry.options == {}
    assert entry.state is ConfigEntryState.LOADED


async def test_a_version_1_entry_with_some_of_the_settings_moves_only_those(
    hass: HomeAssistant,
) -> None:
    """Whatever is present moves; whatever is absent stays absent."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={**CONNECTION, CONF_ROW_LIMIT: 10, CONF_READONLY_CONNECTION: True},
    )

    await _migrate(hass, entry)

    assert entry.data == CONNECTION
    assert entry.options == {CONF_ROW_LIMIT: 10, CONF_READONLY_CONNECTION: True}


async def test_a_migrated_read_only_flag_still_applies(hass: HomeAssistant) -> None:
    """The reason for the migration: the flag must survive it and be enforced."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={**CONNECTION, CONF_READONLY_CONNECTION: True},
    )

    await _migrate(hass, entry)

    with pytest.raises(HomeAssistantError, match="read-only"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_EXECUTE,
            {"query": "DELETE FROM t"},
            blocking=True,
            return_response=True,
        )


async def test_a_current_entry_is_left_alone(hass: HomeAssistant) -> None:
    """Migrating twice changes nothing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        minor_version=ENTRY_MINOR_VERSION,
        data=dict(CONNECTION),
        options=dict(BEHAVIOUR),
    )

    await _migrate(hass, entry)

    assert entry.data == CONNECTION
    assert entry.options == BEHAVIOUR


@pytest.mark.parametrize("stored", [0, -5])
async def test_minor_version_2_replaces_a_row_limit_below_1(
    hass: HomeAssistant, stored: int
) -> None:
    """An import from YAML could store one; it used to be fixed on every call.

    Now it is fixed once, in the entry, and the other settings stay as they
    were.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        minor_version=1,
        data=dict(CONNECTION),
        options={**BEHAVIOUR, CONF_ROW_LIMIT: stored},
    )

    await _migrate(hass, entry)

    assert entry.minor_version == ENTRY_MINOR_VERSION
    assert entry.options == {**BEHAVIOUR, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    assert entry.state is ConfigEntryState.LOADED


async def test_minor_version_2_keeps_a_valid_row_limit(hass: HomeAssistant) -> None:
    """Only a value below 1 changes; an absent one stays absent."""
    valid = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        minor_version=1,
        data=dict(CONNECTION),
        options=dict(BEHAVIOUR),
    )
    absent = MockConfigEntry(
        domain=DOMAIN, version=ENTRY_VERSION, minor_version=1, data=dict(CONNECTION)
    )

    await _migrate(hass, valid)
    await _migrate(hass, absent)

    assert valid.options == BEHAVIOUR
    assert absent.options == {}
    assert valid.minor_version == absent.minor_version == ENTRY_MINOR_VERSION


async def test_a_version_1_entry_gets_both_steps(hass: HomeAssistant) -> None:
    """The settings move to the options, and a row limit below 1 is replaced."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, data={**CONNECTION, CONF_ROW_LIMIT: 0}
    )

    await _migrate(hass, entry)

    assert (entry.version, entry.minor_version) == (ENTRY_VERSION, ENTRY_MINOR_VERSION)
    assert entry.data == CONNECTION
    assert entry.options == {CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}


async def test_an_entry_from_a_newer_release_is_refused(hass: HomeAssistant) -> None:
    """A downgrade fails loudly instead of running with settings it cannot read."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=ENTRY_VERSION + 1, data=dict(CONNECTION)
    )

    await _migrate(hass, entry)

    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.data == CONNECTION
