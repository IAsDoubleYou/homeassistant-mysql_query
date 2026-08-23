"""Tests for the mysql_query config flow."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from aiomysql import Error as MySQLError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mysql_query.const import (
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_READONLY_CONNECTION,
    CONF_ROW_LIMIT,
    CONF_USE_TLS,
    DEFAULT_ROW_LIMIT,
    DOMAIN,
)
from custom_components.mysql_query.db import TLSUnavailableError
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


@contextmanager
def patch_tls_ok() -> Iterator[None]:
    """Let the TLS check pass, in the config flow and in the entry setup.

    Both call async_verify_tls, each through its own module namespace, and the
    mocked driver of patch_driver() cannot answer a SHOW STATUS query.
    """
    with (
        patch("custom_components.mysql_query.db.async_verify_tls", AsyncMock()),
        patch("custom_components.mysql_query.async_verify_tls", AsyncMock()),
    ):
        yield


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
    """An unreachable server is reported on the form, with the reason.

    A refused connection, a timeout and a rejected charset all end up here
    and each needs a different fix, so the driver message is shown next to
    the generic advice about the host and the firewall.
    """
    with patch_driver(
        side_effect=MySQLError(2003, "Can't connect to MySQL server on 'db.local'")
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert (
        "Can't connect to MySQL server" in result["description_placeholders"]["error"]
    )


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

    with patch_driver():
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

    with patch_driver():
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
    entry = MockConfigEntry(domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: 500})
    entry.add_to_hass(hass)

    with patch_driver():
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
    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
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


async def test_user_flow_invalid_auth(hass: HomeAssistant) -> None:
    """Wrong credentials are reported as such, without the driver message.

    "Access denied for user ..." says nothing the form does not already say,
    so the cause is named instead of repeated verbatim.
    """
    with patch_driver(
        side_effect=MySQLError(
            1045, "Access denied for user 'test_user'@'localhost' (using password: YES)"
        )
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.parametrize("errno", [1044, 1049])
async def test_user_flow_unknown_database(hass: HomeAssistant, errno: int) -> None:
    """A missing database and a denied one are reported as such."""
    with patch_driver(side_effect=MySQLError(errno, "Unknown database 'test_db'")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown_database"}


async def test_user_flow_shows_the_reason_for_an_unknown_error(
    hass: HomeAssistant,
) -> None:
    """An unexpected exception carries its message onto the form."""
    with patch_driver(side_effect=RuntimeError("something odd")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["errors"] == {"base": "unknown"}
    assert result["description_placeholders"]["error"] == "something odd"


async def test_user_flow_long_error_is_shortened(hass: HomeAssistant) -> None:
    """A driver message that would fill the dialog is cut off."""
    with patch_driver(side_effect=MySQLError(2003, "x" * 500)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    detail = result["description_placeholders"]["error"]
    assert detail.endswith("...")
    assert len(detail) == 258


async def test_user_flow_error_without_message(hass: HomeAssistant) -> None:
    """An exception carrying no message falls back to its type."""
    with patch_driver(side_effect=RuntimeError()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["description_placeholders"]["error"] == "RuntimeError"


async def test_user_flow_recovers_after_an_error(hass: HomeAssistant) -> None:
    """Correcting the settings after a failure still creates the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch_driver(side_effect=MySQLError(1045, "Access denied")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch_driver():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_flow_rejects_settings_it_cannot_connect_with(
    hass: HomeAssistant,
) -> None:
    """Settings that cannot reach the database are not saved.

    Without the check they would be stored anyway, after which the reload
    fails and the reason is only visible in the log.
    """
    data = {**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    with patch_driver(side_effect=MySQLError(1045, "Access denied")):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_MYSQL_PASSWORD: "wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    # The entry still runs on what it was configured with.
    assert entry.data == data


async def test_options_flow_keeps_the_submitted_values_on_the_form(
    hass: HomeAssistant,
) -> None:
    """A rejected form comes back filled in, not reset to the stored settings."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    )
    entry.add_to_hass(hass)

    with patch_driver(side_effect=MySQLError(2003, "Connection refused")):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_MYSQL_HOST: "typo.local"}
        )

    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults[CONF_MYSQL_HOST] == "typo.local"
    assert "Connection refused" in result["description_placeholders"]["error"]


async def test_options_flow_recovers_after_an_error(hass: HomeAssistant) -> None:
    """Correcting the settings after a failure still saves them."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    with patch_driver(side_effect=MySQLError(1045, "Access denied")):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_MYSQL_DB: "other_db"}
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch_driver():
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_MYSQL_DB: "other_db"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_MYSQL_DB] == "other_db"


async def test_user_flow_tls_unavailable(hass: HomeAssistant) -> None:
    """A server that does not encrypt is reported as such, not as a refusal.

    The settings are fine and the server let us in; it just never ran the
    handshake. Reporting that as "cannot connect" would send someone looking
    at their host and firewall instead of at their database's TLS setup.
    """
    with patch(
        "custom_components.mysql_query.config_flow.async_test_connection",
        AsyncMock(side_effect=TLSUnavailableError("not encrypted")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_USE_TLS: True}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "tls_unavailable"}


async def test_user_flow_stores_the_tls_choice(hass: HomeAssistant) -> None:
    """The option ends up in the config entry."""
    with patch_driver(), patch_tls_ok():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_USE_TLS: True}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USE_TLS] is True


async def test_user_flow_defaults_tls_to_off(hass: HomeAssistant) -> None:
    """Submitting the form untouched leaves encryption off.

    Existing installations must keep the connection they had, so the default
    is what decides whether an upgrade breaks them.
    """
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        defaults = {key.schema: key.default() for key in result["data_schema"].schema}
        assert defaults[CONF_USE_TLS] is False

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["data"].get(CONF_USE_TLS, False) is False


async def test_options_flow_tls_unavailable(hass: HomeAssistant) -> None:
    """Turning encryption on against a server without TLS is refused."""
    data = {**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.mysql_query.config_flow.async_test_connection",
        AsyncMock(side_effect=TLSUnavailableError("not encrypted")),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_USE_TLS: True}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "tls_unavailable"}
    # Nothing was stored, so the entry keeps running unencrypted as before.
    assert entry.data == data


async def test_options_flow_turns_tls_on(hass: HomeAssistant) -> None:
    """A server that does encrypt lets the option be saved."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    )
    entry.add_to_hass(hass)

    with patch_driver(), patch_tls_ok():
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_USE_TLS: True}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_USE_TLS] is True


async def test_user_flow_defaults_readonly_to_off(hass: HomeAssistant) -> None:
    """An existing connection was never read-only, so the default must not be."""
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        defaults = {key.schema: key.default() for key in result["data_schema"].schema}
        assert defaults[CONF_READONLY_CONNECTION] is False

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["data"].get(CONF_READONLY_CONNECTION, False) is False


async def test_user_flow_stores_the_readonly_choice(hass: HomeAssistant) -> None:
    """Marking a connection read-only at setup time is remembered."""
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_READONLY_CONNECTION: True}
        )
        await hass.async_block_till_done()

    assert result["data"][CONF_READONLY_CONNECTION] is True


async def test_options_flow_can_mark_a_connection_readonly(
    hass: HomeAssistant,
) -> None:
    """The flag can be turned on afterwards, without re-adding the connection."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT, CONF_ROW_LIMIT: DEFAULT_ROW_LIMIT}
    )
    entry.add_to_hass(hass)

    with patch_driver():
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_READONLY_CONNECTION: True}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_READONLY_CONNECTION] is True
