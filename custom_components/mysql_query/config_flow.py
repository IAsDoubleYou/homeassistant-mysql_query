"""Config flow for mysql_query integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from aiomysql import Error
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_AUTOCOMMIT,
    CONF_MYSQL_CHARSET,
    CONF_MYSQL_COLLATION,
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
    DEFAULT_MYSQL_AUTOCOMMIT,
    DEFAULT_MYSQL_PORT,
    DEFAULT_MYSQL_TIMEOUT,
    DEFAULT_QUERY_TIMEOUT,
    DEFAULT_READONLY_CONNECTION,
    DEFAULT_ROW_LIMIT,
    DEFAULT_USE_TLS,
    DOMAIN,
)
from .db import (
    ERRNO_ACCESS_DENIED,
    ERRNO_DATABASE_ACCESS_DENIED,
    ERRNO_UNKNOWN_DATABASE,
    TLSUnavailableError,
    async_test_connection,
    error_details,
)

_LOGGER = logging.getLogger(__name__)

# The driver message is shown on the form itself, so it is cut off before it
# pushes the rest of the dialog out of view.
_MAX_ERROR_LENGTH = 255


def _error_detail(err: BaseException) -> str:
    """Return the driver message in a form that fits on the dialog."""
    _, message = error_details(err)
    message = message.strip()
    # Some exceptions carry no message at all; the type is better than nothing.
    if not message:
        return type(err).__name__
    if len(message) > _MAX_ERROR_LENGTH:
        return f"{message[:_MAX_ERROR_LENGTH]}..."
    return message


async def _async_validate(config: dict[str, Any]) -> tuple[str | None, str]:
    """Try the connection.

    Returns the error key to show on the form, and the driver message that
    goes with it. Causes that speak for themselves come without a message.
    """
    try:
        await async_test_connection(config)
    except TLSUnavailableError as err:
        # The settings themselves are fine; the server just did not encrypt.
        _LOGGER.error("TLS requested but not established: %s", err)
        return "tls_unavailable", ""
    except (Error, OSError, TimeoutError) as err:
        errno, _ = error_details(err)
        if errno == ERRNO_ACCESS_DENIED:
            return "invalid_auth", ""
        if errno in (ERRNO_DATABASE_ACCESS_DENIED, ERRNO_UNKNOWN_DATABASE):
            return "unknown_database", ""
        # A refused connection, a timeout and a rejected charset all end up
        # here and each needs a different fix, so the reason from the driver
        # is shown alongside the generic advice.
        _LOGGER.error("MySQL connection error: %s", err)
        return "cannot_connect", _error_detail(err)
    except Exception as err:
        _LOGGER.exception("Unexpected exception")
        return "unknown", _error_detail(err)
    return None, ""


# A masked input. Never given a default, so the stored password is not sent to
# the browser: a default would put it in the form definition, readable in the
# page source and in the network traffic.
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def keep_stored_password(
    user_input: dict[str, Any], stored: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the input with the stored password filled in when it was left empty.

    The edit forms do not show the password, so an untouched field means "keep
    it" and not "set it to nothing".
    """
    if user_input.get(CONF_MYSQL_PASSWORD):
        return user_input
    return {**user_input, CONF_MYSQL_PASSWORD: stored.get(CONF_MYSQL_PASSWORD, "")}


def get_schema(defaults: dict[str, Any], *, editing: bool = False) -> vol.Schema:
    """Return the schema with provided default values.

    This schema is used for both initial setup and the options flow (re-configuration),
    ensuring all fields remain editable. Editing makes the password optional,
    because the stored one is not shown and stays when the field is left empty.
    """
    password_field = (
        vol.Optional(CONF_MYSQL_PASSWORD, default="")
        if editing
        else vol.Required(CONF_MYSQL_PASSWORD)
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_MYSQL_HOST, default=defaults.get(CONF_MYSQL_HOST, "")
            ): str,
            vol.Required(
                CONF_MYSQL_PORT,
                default=defaults.get(CONF_MYSQL_PORT, DEFAULT_MYSQL_PORT),
            ): int,
            vol.Required(
                CONF_MYSQL_USERNAME, default=defaults.get(CONF_MYSQL_USERNAME, "")
            ): str,
            password_field: PASSWORD_SELECTOR,
            vol.Required(CONF_MYSQL_DB, default=defaults.get(CONF_MYSQL_DB, "")): str,
            vol.Optional(
                CONF_MYSQL_TIMEOUT,
                default=defaults.get(CONF_MYSQL_TIMEOUT, DEFAULT_MYSQL_TIMEOUT),
            ): int,
            vol.Optional(
                CONF_QUERY_TIMEOUT,
                default=defaults.get(CONF_QUERY_TIMEOUT, DEFAULT_QUERY_TIMEOUT),
            ): int,
            vol.Optional(
                CONF_MYSQL_CHARSET, default=defaults.get(CONF_MYSQL_CHARSET, "")
            ): str,
            vol.Optional(
                CONF_MYSQL_COLLATION, default=defaults.get(CONF_MYSQL_COLLATION, "")
            ): str,
            vol.Optional(
                CONF_AUTOCOMMIT,
                default=defaults.get(CONF_AUTOCOMMIT, DEFAULT_MYSQL_AUTOCOMMIT),
            ): bool,
            vol.Optional(
                CONF_ROW_LIMIT, default=defaults.get(CONF_ROW_LIMIT, DEFAULT_ROW_LIMIT)
            ): int,
            vol.Optional(
                CONF_USE_TLS, default=defaults.get(CONF_USE_TLS, DEFAULT_USE_TLS)
            ): bool,
            vol.Optional(
                CONF_READONLY_CONNECTION,
                default=defaults.get(
                    CONF_READONLY_CONNECTION, DEFAULT_READONLY_CONNECTION
                ),
            ): bool,
        }
    )


class MySQLQueryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for mysql_query."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step when a user adds the integration via UI."""
        errors: dict[str, str] = {}
        detail = ""

        if user_input is not None:
            # Fall back to the default limit when the field is empty or invalid
            if not user_input.get(CONF_ROW_LIMIT) or user_input[CONF_ROW_LIMIT] < 1:
                user_input[CONF_ROW_LIMIT] = DEFAULT_ROW_LIMIT

            error, detail = await _async_validate(user_input)
            if error is None:
                unique_id = f"{user_input[CONF_MYSQL_HOST]}_{user_input[CONF_MYSQL_DB]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = (
                    f"MySQL: {user_input[CONF_MYSQL_HOST]}/{user_input[CONF_MYSQL_DB]}"
                )
                return self.async_create_entry(title=title, data=user_input)
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=get_schema(user_input or {}),
            errors=errors,
            description_placeholders={"error": detail},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the flow that asks for new credentials.

        Home Assistant starts it when setup reports refused credentials. It
        deliberately does not go through async_step_user: that step aborts on
        a unique_id that is already configured, which is exactly the situation
        here, and it would create a second entry instead of updating this one.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the username and password, and update the entry with them."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        detail = ""

        if user_input is not None:
            error, detail = await _async_validate({**entry.data, **user_input})
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
            errors["base"] = error

        current = user_input or entry.data
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MYSQL_USERNAME,
                        default=current.get(CONF_MYSQL_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_MYSQL_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
            description_placeholders={"connection": entry.title, "error": detail},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MySQLQueryOptionsFlow:
        """Create the options flow handler."""
        return MySQLQueryOptionsFlow()


class MySQLQueryOptionsFlow(config_entries.OptionsFlow):
    """Handle options (re-configuration) for the integration."""

    # The entry is not stored here: OptionsFlow exposes it as self.config_entry,
    # which resolves it from the handler on every access. Keeping a reference of
    # our own would only add a second name for the same object.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the settings via the Configure button."""
        errors: dict[str, str] = {}
        detail = ""

        if user_input is not None:
            # Fall back to the default limit when the field is empty or invalid
            if not user_input.get(CONF_ROW_LIMIT) or user_input[CONF_ROW_LIMIT] < 1:
                user_input[CONF_ROW_LIMIT] = DEFAULT_ROW_LIMIT

            # Verified before saving: settings that cannot reach the database
            # would otherwise be stored, after which the reload fails and the
            # reason is only visible in the log.
            user_input = keep_stored_password(user_input, self.config_entry.data)
            error, detail = await _async_validate(user_input)
            if error is None:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=user_input
                )
                return self.async_create_entry(title="", data={})
            errors["base"] = error

        current_settings = user_input or dict(self.config_entry.data)

        return self.async_show_form(
            step_id="init",
            data_schema=get_schema(current_settings, editing=True),
            errors=errors,
            description_placeholders={"error": detail},
        )
