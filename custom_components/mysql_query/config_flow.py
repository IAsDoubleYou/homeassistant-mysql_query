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
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
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
    ENTRY_VERSION,
    OPTION_KEYS,
)
from .db import (
    ERRNO_ACCESS_DENIED,
    ERRNO_DATABASE_ACCESS_DENIED,
    ERRNO_UNKNOWN_DATABASE,
    TLSUnavailableError,
    async_test_connection,
    error_details,
    merged_config,
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


def _whole_number(minimum: int, maximum: int | None = None) -> NumberSelector:
    """Return a box for a whole number from ``minimum`` on, up to ``maximum``.

    The bounds are the ones the code needs to work: a port outside 1-65535 does
    not exist, and a timeout or a limit below one would make every call fail
    or return nothing. The selector hands back a float, so whatever is saved is
    turned into an int first (see _as_whole_numbers).
    """
    # Left out rather than set to None when there is no upper bound: the
    # selector rejects a max that is present but empty.
    bounds = {"min": minimum} | ({"max": maximum} if maximum is not None else {})
    return NumberSelector(
        NumberSelectorConfig(**bounds, step=1, mode=NumberSelectorMode.BOX)
    )


PORT_SELECTOR = _whole_number(1, 65535)
SECONDS_SELECTOR = _whole_number(1)
ROW_LIMIT_SELECTOR = _whole_number(1)

# The settings a NumberSelector fills in.
_NUMBER_KEYS = (
    CONF_MYSQL_PORT,
    CONF_MYSQL_TIMEOUT,
    CONF_QUERY_TIMEOUT,
    CONF_ROW_LIMIT,
)


def _as_whole_numbers(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Return the settings with the numbers a selector gave as floats as ints."""
    return {
        key: int(value) if key in _NUMBER_KEYS and value is not None else value
        for key, value in settings.items()
    }


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


def get_connection_schema(
    defaults: Mapping[str, Any], *, editing: bool = False
) -> vol.Schema:
    """Return the schema of the settings that decide where and how to connect.

    These live in the config entry data and are changed through reconfigure.
    Editing makes the password optional, because the stored one is not shown
    and stays when the field is left empty.
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
            ): PORT_SELECTOR,
            vol.Required(
                CONF_MYSQL_USERNAME, default=defaults.get(CONF_MYSQL_USERNAME, "")
            ): str,
            password_field: PASSWORD_SELECTOR,
            vol.Required(CONF_MYSQL_DB, default=defaults.get(CONF_MYSQL_DB, "")): str,
            vol.Optional(
                CONF_MYSQL_TIMEOUT,
                default=defaults.get(CONF_MYSQL_TIMEOUT, DEFAULT_MYSQL_TIMEOUT),
            ): SECONDS_SELECTOR,
            vol.Optional(
                CONF_MYSQL_CHARSET, default=defaults.get(CONF_MYSQL_CHARSET, "")
            ): str,
            vol.Optional(
                CONF_MYSQL_COLLATION, default=defaults.get(CONF_MYSQL_COLLATION, "")
            ): str,
            vol.Optional(
                CONF_USE_TLS, default=defaults.get(CONF_USE_TLS, DEFAULT_USE_TLS)
            ): bool,
        }
    )


def get_options_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Return the schema of the settings that only decide how queries behave.

    These live in the config entry options. Changing one does not touch the
    identity of the connection, so it never needs the connection to be tried.
    """
    return vol.Schema(
        {
            vol.Optional(
                CONF_QUERY_TIMEOUT,
                default=defaults.get(CONF_QUERY_TIMEOUT, DEFAULT_QUERY_TIMEOUT),
            ): SECONDS_SELECTOR,
            vol.Optional(
                CONF_ROW_LIMIT, default=defaults.get(CONF_ROW_LIMIT, DEFAULT_ROW_LIMIT)
            ): ROW_LIMIT_SELECTOR,
            vol.Optional(
                CONF_AUTOCOMMIT,
                default=defaults.get(CONF_AUTOCOMMIT, DEFAULT_MYSQL_AUTOCOMMIT),
            ): bool,
            vol.Optional(
                CONF_READONLY_CONNECTION,
                default=defaults.get(
                    CONF_READONLY_CONNECTION, DEFAULT_READONLY_CONNECTION
                ),
            ): bool,
        }
    )


def get_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Return the setup schema: the connection and the query behaviour together."""
    return get_connection_schema(defaults).extend(get_options_schema(defaults).schema)


def split_settings(
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split settings into what belongs in the entry data and its options."""
    data = {k: v for k, v in settings.items() if k not in OPTION_KEYS}
    options = {k: v for k, v in settings.items() if k in OPTION_KEYS}
    return data, options


def _unique_id(config: Mapping[str, Any]) -> str:
    """Return the identity of a connection: its server and its database."""
    return f"{config[CONF_MYSQL_HOST]}_{config[CONF_MYSQL_DB]}"


def _title(config: Mapping[str, Any]) -> str:
    """Return the title a connection gets when the user did not pick one."""
    return f"MySQL: {config[CONF_MYSQL_HOST]}/{config[CONF_MYSQL_DB]}"


class MySQLQueryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for mysql_query."""

    # Version 2 moved the query behaviour settings from the entry data to its
    # options. A major bump, not a minor one: an older release looks for them
    # in the data and would silently run with its defaults, for instance
    # without the read-only switch. Home Assistant refuses to load an entry
    # that is newer than the integration instead.
    VERSION = ENTRY_VERSION

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step when a user adds the integration via UI."""
        errors: dict[str, str] = {}
        detail = ""

        if user_input is not None:
            user_input = _as_whole_numbers(user_input)

            error, detail = await _async_validate(user_input)
            if error is None:
                await self.async_set_unique_id(_unique_id(user_input))
                self._abort_if_unique_id_configured()

                data, options = split_settings(user_input)
                return self.async_create_entry(
                    title=_title(user_input), data=data, options=options
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=get_schema(user_input or {}),
            errors=errors,
            description_placeholders={"error": detail},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change where and how the connection is made."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        detail = ""

        if user_input is not None:
            user_input = keep_stored_password(_as_whole_numbers(user_input), entry.data)
            candidate = {**entry.data, **user_input}

            # The options take part, because autocommit is a connection argument.
            error, detail = await _async_validate({**entry.options, **candidate})
            if error is None:
                changes: dict[str, Any] = {}
                new_unique_id = _unique_id(candidate)
                if new_unique_id != entry.unique_id:
                    # Only a changed host or database can collide with another
                    # connection; an unchanged one would match the entry itself.
                    other = self.hass.config_entries.async_entry_for_domain_unique_id(
                        DOMAIN, new_unique_id
                    )
                    if other is not None and other.entry_id != entry.entry_id:
                        return self.async_abort(reason="already_configured")
                    changes["unique_id"] = new_unique_id
                    # A title the user picked stays; the generated one follows.
                    if entry.title == _title(entry.data):
                        changes["title"] = _title(candidate)
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input, **changes
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=get_connection_schema(user_input or entry.data, editing=True),
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
            error, detail = await _async_validate(merged_config(entry) | user_input)
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


class MySQLQueryOptionsFlow(config_entries.OptionsFlowWithReload):
    """Handle the query behaviour settings of a connection.

    Reloads the entry when the options changed, which is what rebuilds the pool
    with the new autocommit mode and re-reads the other settings.
    """

    # The entry is not stored here: OptionsFlow exposes it as self.config_entry,
    # which resolves it from the handler on every access. Keeping a reference of
    # our own would only add a second name for the same object.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the settings via the Configure button."""
        if user_input is not None:
            return self.async_create_entry(data=_as_whole_numbers(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=get_options_schema(self.config_entry.options),
        )
