"""Tests for the reconfigure flow and the options flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from aiomysql import Error as MySQLError
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.mysql_query.const import (
    CONF_AUTOCOMMIT,
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_QUERY_TIMEOUT,
    CONF_READONLY_CONNECTION,
    CONF_ROW_LIMIT,
    CONF_USE_TLS,
    DOMAIN,
    SERVICE_QUERY,
)
from custom_components.mysql_query.db import TLSUnavailableError
from tests.conftest import FakePool, make_entry, patch_create_pool
from tests.test_config_flow import (
    USER_INPUT,
    _form_defaults,
    patch_driver,
    patch_tls_ok,
)

UNIQUE_ID = "localhost_test_db"


def _entry(hass: HomeAssistant, **kwargs):
    """Add an entry in the shape the current release stores."""
    entry = make_entry(
        {**USER_INPUT, CONF_ROW_LIMIT: 500},
        unique_id=kwargs.pop("unique_id", UNIQUE_ID),
        title=kwargs.pop("title", "MySQL: localhost/test_db"),
    )
    entry.add_to_hass(hass)
    return entry


async def _reconfigure(hass: HomeAssistant, entry, user_input: dict) -> dict:
    """Open the reconfigure flow of an entry and submit the given input."""
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def _connection_input(**changes) -> dict:
    """Return the connection fields of the form, with the given changes."""
    keep = {k: v for k, v in USER_INPUT.items() if k != CONF_MYSQL_PASSWORD}
    return {**keep, CONF_MYSQL_PASSWORD: "", **changes}


# --- reconfigure -----------------------------------------------------------


async def test_reconfigure_updates_the_connection(hass: HomeAssistant) -> None:
    """New connection settings replace the old ones and the entry reloads."""
    entry = _entry(hass)

    with patch_driver(), patch_create_pool(FakePool()):
        result = await _reconfigure(
            hass, entry, _connection_input(**{CONF_MYSQL_HOST: "db.local"})
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_MYSQL_HOST] == "db.local"
    # The query behaviour is not part of this form and stays as it was.
    assert entry.options[CONF_ROW_LIMIT] == 500


async def test_reconfigure_follows_a_changed_host_or_database(
    hass: HomeAssistant,
) -> None:
    """The unique id and the generated title follow the host and database."""
    entry = _entry(hass)

    with patch_driver(), patch_create_pool(FakePool()):
        await _reconfigure(
            hass, entry, _connection_input(**{CONF_MYSQL_DB: "other_db"})
        )
        await hass.async_block_till_done()

    assert entry.unique_id == "localhost_other_db"
    assert entry.title == "MySQL: localhost/other_db"


async def test_reconfigure_keeps_a_title_the_user_chose(hass: HomeAssistant) -> None:
    """Only the generated title is rewritten; a renamed connection keeps its name."""
    entry = _entry(hass, title="Home automation")

    with patch_driver(), patch_create_pool(FakePool()):
        await _reconfigure(
            hass, entry, _connection_input(**{CONF_MYSQL_DB: "other_db"})
        )
        await hass.async_block_till_done()

    assert entry.title == "Home automation"
    assert entry.unique_id == "localhost_other_db"


async def test_reconfigure_without_a_new_host_or_database_keeps_the_unique_id(
    hass: HomeAssistant,
) -> None:
    """Changing only a credential or a timeout does not touch the identity.

    The unique id would match the entry being edited, which must not count as
    a conflict.
    """
    entry = _entry(hass)

    with patch_driver(), patch_create_pool(FakePool()):
        result = await _reconfigure(
            hass, entry, _connection_input(**{CONF_USE_TLS: False, "mysql_timeout": 20})
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == UNIQUE_ID
    assert entry.data["mysql_timeout"] == 20


async def test_reconfigure_to_a_connection_another_entry_has_is_refused(
    hass: HomeAssistant,
) -> None:
    """Pointing an entry at a host and database that another one covers aborts."""
    entry = _entry(hass)
    other = make_entry(
        {**USER_INPUT, CONF_MYSQL_DB: "taken_db"}, unique_id="localhost_taken_db"
    )
    other.add_to_hass(hass)

    with patch_driver():
        result = await _reconfigure(
            hass, entry, _connection_input(**{CONF_MYSQL_DB: "taken_db"})
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_MYSQL_DB] == "test_db"
    assert entry.unique_id == UNIQUE_ID


async def test_reconfigure_with_an_empty_password_keeps_the_stored_one(
    hass: HomeAssistant,
) -> None:
    """The form does not show the password, so empty means keep."""
    entry = _entry(hass)

    with patch_driver() as mock_connect, patch_create_pool(FakePool()):
        await _reconfigure(
            hass, entry, _connection_input(**{CONF_MYSQL_HOST: "db.local"})
        )
        await hass.async_block_till_done()

    assert entry.data[CONF_MYSQL_PASSWORD] == "test_pass"
    # The connection was tried with the kept password, not with an empty one.
    assert mock_connect.await_args.kwargs["password"] == "test_pass"


async def test_reconfigure_with_a_new_password_replaces_it(
    hass: HomeAssistant,
) -> None:
    """A filled-in password field replaces the stored one."""
    entry = _entry(hass)

    with patch_driver(), patch_create_pool(FakePool()):
        await _reconfigure(
            hass, entry, _connection_input(**{CONF_MYSQL_PASSWORD: "new_pass"})
        )
        await hass.async_block_till_done()

    assert entry.data[CONF_MYSQL_PASSWORD] == "new_pass"


async def test_reconfigure_form_never_contains_the_stored_password(
    hass: HomeAssistant,
) -> None:
    """The stored password is not sent to the browser, not even as a default."""
    entry = _entry(hass)

    result = await entry.start_reconfigure_flow(hass)

    assert _form_defaults(result)[CONF_MYSQL_PASSWORD] == ""
    assert "test_pass" not in repr(result["data_schema"].schema)
    # The rest is prefilled with what the entry runs on.
    assert _form_defaults(result)[CONF_MYSQL_HOST] == "localhost"
    assert CONF_ROW_LIMIT not in _form_defaults(result)


async def test_reconfigure_rejects_settings_it_cannot_connect_with(
    hass: HomeAssistant,
) -> None:
    """Settings that cannot reach the database are not saved."""
    entry = _entry(hass)
    stored = dict(entry.data)

    with patch_driver(side_effect=MySQLError(2003, "Connection refused")):
        result = await _reconfigure(
            hass, entry, _connection_input(**{CONF_MYSQL_HOST: "typo.local"})
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "Connection refused" in result["description_placeholders"]["error"]
    # The form comes back with what was typed, and the entry is unchanged.
    assert _form_defaults(result)[CONF_MYSQL_HOST] == "typo.local"
    assert entry.data == stored


async def test_reconfigure_recovers_after_an_error(hass: HomeAssistant) -> None:
    """Correcting the settings after a failure still saves them."""
    entry = _entry(hass)
    result = await entry.start_reconfigure_flow(hass)

    with patch_driver(side_effect=MySQLError(1045, "Access denied")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _connection_input(**{CONF_MYSQL_PASSWORD: "wrong"})
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch_driver(), patch_create_pool(FakePool()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _connection_input(**{CONF_MYSQL_PASSWORD: "right"})
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_MYSQL_PASSWORD] == "right"


async def test_reconfigure_tls_unavailable(hass: HomeAssistant) -> None:
    """Turning encryption on against a server without TLS is refused."""
    entry = _entry(hass)
    stored = dict(entry.data)

    with patch(
        "custom_components.mysql_query.config_flow.async_test_connection",
        AsyncMock(side_effect=TLSUnavailableError("not encrypted")),
    ):
        result = await _reconfigure(
            hass, entry, _connection_input(**{CONF_USE_TLS: True})
        )

    assert result["errors"] == {"base": "tls_unavailable"}
    assert entry.data == stored


async def test_reconfigure_turns_tls_on(hass: HomeAssistant) -> None:
    """A server that does encrypt lets the option be saved."""
    entry = _entry(hass)

    with patch_driver(), patch_tls_ok(), patch_create_pool(FakePool()):
        await _reconfigure(hass, entry, _connection_input(**{CONF_USE_TLS: True}))
        await hass.async_block_till_done()

    assert entry.data[CONF_USE_TLS] is True


# --- options ---------------------------------------------------------------


async def test_options_flow_saves_the_behaviour_settings(hass: HomeAssistant) -> None:
    """The options flow writes to the options and leaves the data alone."""
    entry = _entry(hass)
    stored = dict(entry.data)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ROW_LIMIT: 250,
            CONF_QUERY_TIMEOUT: 45,
            CONF_AUTOCOMMIT: False,
            CONF_READONLY_CONNECTION: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_ROW_LIMIT: 250,
        CONF_QUERY_TIMEOUT: 45,
        CONF_AUTOCOMMIT: False,
        CONF_READONLY_CONNECTION: True,
    }
    assert entry.data == stored


async def test_options_flow_has_no_connection_fields(hass: HomeAssistant) -> None:
    """Host, credentials and TLS are reconfigure's business, not Configure's."""
    entry = _entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert {key.schema for key in result["data_schema"].schema} == {
        CONF_ROW_LIMIT,
        CONF_QUERY_TIMEOUT,
        CONF_AUTOCOMMIT,
        CONF_READONLY_CONNECTION,
    }


async def test_options_flow_form_is_prefilled_with_current_options(
    hass: HomeAssistant,
) -> None:
    """The form opens on the settings the entry is running with."""
    entry = _entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert _form_defaults(result)[CONF_ROW_LIMIT] == 500


async def test_options_flow_rejects_numbers_below_one(hass: HomeAssistant) -> None:
    """A row limit or a timeout below one would break every call."""
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    for field in (CONF_ROW_LIMIT, CONF_QUERY_TIMEOUT):
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(
                result["flow_id"], {field: 0}
            )


async def test_options_flow_stores_whole_numbers(hass: HomeAssistant) -> None:
    """The selector answers with floats; the options keep ints."""
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ROW_LIMIT: 250.0, CONF_QUERY_TIMEOUT: 40.0}
    )

    assert entry.options[CONF_ROW_LIMIT] == 250
    assert isinstance(entry.options[CONF_ROW_LIMIT], int)
    assert isinstance(entry.options[CONF_QUERY_TIMEOUT], int)


async def test_options_flow_reloads_the_entry(hass: HomeAssistant) -> None:
    """A changed option rebuilds the pool, which is what applies it."""
    entry = _entry(hass)
    first, second = FakePool(), FakePool()

    with patch_create_pool(first, second):
        assert await hass.config_entries.async_setup(entry.entry_id)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ROW_LIMIT: 5}
        )
        await hass.async_block_till_done()

    assert first.closed
    assert not second.closed
    assert hass.services.has_service(DOMAIN, SERVICE_QUERY)


async def test_options_flow_does_not_reload_when_nothing_changed(
    hass: HomeAssistant,
) -> None:
    """Saving the form untouched leaves the running pool alone."""
    entry = make_entry(
        {
            **USER_INPUT,
            CONF_ROW_LIMIT: 500,
            CONF_QUERY_TIMEOUT: 30,
            CONF_AUTOCOMMIT: True,
            CONF_READONLY_CONNECTION: False,
        },
        unique_id=UNIQUE_ID,
    )
    entry.add_to_hass(hass)
    pool = FakePool()

    with patch_create_pool(pool, FakePool()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {**_form_defaults(result)}
        )
        await hass.async_block_till_done()

    assert not pool.closed
