"""Tests for the mysql_query config flow."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import logging
from unittest.mock import AsyncMock, patch

from aiomysql import Error as MySQLError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.mysql_query.const import (
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_QUERY_TIMEOUT,
    CONF_READONLY_CONNECTION,
    CONF_ROW_LIMIT,
    CONF_USE_TLS,
    DEFAULT_ROW_LIMIT,
    DOMAIN,
    ENTRY_MINOR_VERSION,
    ENTRY_VERSION,
    OPTION_KEYS,
)
from custom_components.mysql_query.db import TLSUnavailableError
from tests.conftest import FakePool, make_entry

USER_INPUT = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_PORT: 3306,
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
    CONF_MYSQL_TIMEOUT: 10,
}


def _form_defaults(result: dict) -> dict:
    """Return the default of every form field that has one."""
    return {
        key.schema: key.default()
        for key in result["data_schema"].schema
        if key.default is not vol.UNDEFINED
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
    assert result["options"][CONF_ROW_LIMIT] == DEFAULT_ROW_LIMIT
    # The connection stays in the data, the query behaviour goes to the options.
    assert result["version"] == ENTRY_VERSION
    assert result["minor_version"] == ENTRY_MINOR_VERSION
    assert set(result["options"]) == set(OPTION_KEYS)
    assert not set(result["data"]) & set(OPTION_KEYS)
    assert result["data"][CONF_MYSQL_HOST] == "localhost"
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


async def test_user_flow_connection_refused(hass: HomeAssistant) -> None:
    """A refusal that waiting does not fix gets the same advice as at setup.

    A host the account may not connect from is not a network problem, so the
    form does not point at the host, the port and the firewall.
    """
    with patch_driver(
        side_effect=MySQLError(1130, "Host 'ha' is not allowed to connect")
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "connection_refused"}
    assert "not allowed to connect" in result["description_placeholders"]["error"]


@pytest.mark.parametrize(
    "error",
    [
        MySQLError(2003, "Can't connect to MySQL server"),
        MySQLError(1045, "Access denied"),
        TLSUnavailableError("not encrypted"),
    ],
)
async def test_user_flow_does_not_log_what_the_form_shows(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """A failure the form reports is not logged as an error as well."""
    with patch(
        "custom_components.mysql_query.config_flow.async_test_connection",
        AsyncMock(side_effect=error),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert not [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.mysql_query")
        and record.levelno >= logging.WARNING
    ]


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_MYSQL_PORT, 0),
        (CONF_MYSQL_PORT, 65536),
        (CONF_MYSQL_TIMEOUT, 0),
        (CONF_QUERY_TIMEOUT, 0),
        (CONF_ROW_LIMIT, 0),
    ],
)
async def test_user_flow_rejects_numbers_outside_their_range(
    hass: HomeAssistant, field: str, value: int
) -> None:
    """The bounds of the number fields are enforced, not only drawn on screen.

    A port outside 1-65535 does not exist, and a timeout or a row limit below
    one would make every call fail or return nothing.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, field: value}
        )


async def test_user_flow_stores_whole_numbers(hass: HomeAssistant) -> None:
    """A number selector answers with floats; the entry keeps ints.

    3306.0 would end up in a connection argument and in the stored settings.
    """
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **USER_INPUT,
                CONF_MYSQL_PORT: 3307.0,
                CONF_MYSQL_TIMEOUT: 12.0,
                CONF_QUERY_TIMEOUT: 40.0,
                CONF_ROW_LIMIT: 250.0,
            },
        )
        await hass.async_block_till_done()

    for value in (
        result["data"][CONF_MYSQL_PORT],
        result["data"][CONF_MYSQL_TIMEOUT],
        result["options"][CONF_QUERY_TIMEOUT],
        result["options"][CONF_ROW_LIMIT],
    ):
        assert isinstance(value, int)
    assert result["data"][CONF_MYSQL_PORT] == 3307
    assert result["options"][CONF_ROW_LIMIT] == 250


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
        defaults = _form_defaults(result)
        assert defaults[CONF_USE_TLS] is False

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["data"].get(CONF_USE_TLS, False) is False


async def test_user_flow_defaults_readonly_to_off(hass: HomeAssistant) -> None:
    """An existing connection was never read-only, so the default must not be."""
    with patch_driver():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        defaults = _form_defaults(result)
        assert defaults[CONF_READONLY_CONNECTION] is False

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["options"].get(CONF_READONLY_CONNECTION, False) is False


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

    assert result["options"][CONF_READONLY_CONNECTION] is True


async def _start_reauth(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Start the reauth flow of an entry the way Home Assistant does."""
    return await entry.start_reauth_flow(hass)


async def test_reauth_flow_updates_the_credentials(hass: HomeAssistant) -> None:
    """New credentials replace the old ones on the same entry.

    The flow must not go through the user step: that one aborts on the unique
    id of the entry that is being repaired, and would create a second entry.
    """
    entry = make_entry(USER_INPUT, unique_id="localhost_test_db")
    entry.add_to_hass(hass)

    result = await _start_reauth(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with (
        patch_driver() as mock_connect,
        patch(
            "custom_components.mysql_query.async_setup_entry",
            AsyncMock(return_value=True),
        ) as setup,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MYSQL_USERNAME: "new_user", CONF_MYSQL_PASSWORD: "new_pass"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_MYSQL_USERNAME] == "new_user"
    assert entry.data[CONF_MYSQL_PASSWORD] == "new_pass"
    # Everything else stays as it was, and no second entry appeared.
    assert entry.data[CONF_MYSQL_HOST] == "localhost"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    # The new credentials were tried before they were saved, then the entry
    # was reloaded with them.
    assert mock_connect.await_args.kwargs["password"] == "new_pass"
    assert setup.await_count == 1


async def test_reauth_flow_does_not_prefill_the_password(hass: HomeAssistant) -> None:
    """The stored password never travels back to the browser."""
    entry = make_entry(USER_INPUT)
    entry.add_to_hass(hass)

    result = await _start_reauth(hass, entry)

    schema = result["data_schema"].schema
    password_key = next(k for k in schema if k == CONF_MYSQL_PASSWORD)
    assert password_key.default is vol.UNDEFINED
    username_key = next(k for k in schema if k == CONF_MYSQL_USERNAME)
    assert username_key.default() == "test_user"


async def test_reauth_flow_reports_credentials_that_are_still_refused(
    hass: HomeAssistant,
) -> None:
    """A wrong password keeps the form open, and the entry untouched."""
    entry = make_entry(USER_INPUT)
    entry.add_to_hass(hass)
    result = await _start_reauth(hass, entry)

    with patch_driver(side_effect=MySQLError(1045, "Access denied")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MYSQL_USERNAME: "test_user", CONF_MYSQL_PASSWORD: "still_wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_MYSQL_PASSWORD] == "test_pass"


async def test_user_form_has_no_password_default(hass: HomeAssistant) -> None:
    """The setup form asks for the password and prefills nothing."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert CONF_MYSQL_PASSWORD not in _form_defaults(result)
