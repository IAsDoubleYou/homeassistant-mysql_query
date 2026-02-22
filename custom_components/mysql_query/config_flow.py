"""Config flow for mysql_query integration."""
from __future__ import annotations

import logging
from typing import Any

import mysql.connector
from mysql.connector import Error
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PORT,
    CONF_MYSQL_USERNAME,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_DB,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_CHARSET,
    CONF_MYSQL_COLLATION,
    CONF_AUTOCOMMIT,
    DEFAULT_MYSQL_PORT,
    DEFAULT_MYSQL_TIMEOUT,
    DEFAULT_MYSQL_AUTOCOMMIT,
)

_LOGGER = logging.getLogger(__name__)

def get_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return the schema with provided default values.

    This schema is used for both initial setup and the options flow (re-configuration),
    ensuring all fields remain editable.
    """
    return vol.Schema(
        {
            vol.Required(CONF_MYSQL_HOST, default=defaults.get(CONF_MYSQL_HOST, "")): str,
            vol.Required(CONF_MYSQL_PORT, default=defaults.get(CONF_MYSQL_PORT, DEFAULT_MYSQL_PORT)): int,
            vol.Required(CONF_MYSQL_USERNAME, default=defaults.get(CONF_MYSQL_USERNAME, "")): str,
            vol.Required(CONF_MYSQL_PASSWORD, default=defaults.get(CONF_MYSQL_PASSWORD, "")): str,
            vol.Required(CONF_MYSQL_DB, default=defaults.get(CONF_MYSQL_DB, "")): str,
            vol.Optional(CONF_MYSQL_TIMEOUT, default=defaults.get(CONF_MYSQL_TIMEOUT, DEFAULT_MYSQL_TIMEOUT)): int,
            vol.Optional(CONF_MYSQL_CHARSET, default=defaults.get(CONF_MYSQL_CHARSET, "")): str,
            vol.Optional(CONF_MYSQL_COLLATION, default=defaults.get(CONF_MYSQL_COLLATION, "")): str,
            vol.Optional(CONF_AUTOCOMMIT, default=defaults.get(CONF_AUTOCOMMIT, DEFAULT_MYSQL_AUTOCOMMIT)): bool,
        }
    )

class MySQLQueryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for mysql_query."""

    VERSION = 1

    async def _test_connection(self, user_input: dict[str, Any]) -> None:
        """Test if the database connection works with provided settings."""
        def connect():
            conn_args = {
                "host": user_input[CONF_MYSQL_HOST],
                "port": user_input[CONF_MYSQL_PORT],
                "user": user_input[CONF_MYSQL_USERNAME],
                "password": user_input[CONF_MYSQL_PASSWORD],
                "database": user_input[CONF_MYSQL_DB],
                "connection_timeout": user_input[CONF_MYSQL_TIMEOUT],
            }
            if user_input.get(CONF_MYSQL_CHARSET):
                conn_args["charset"] = user_input[CONF_MYSQL_CHARSET]
            if user_input.get(CONF_MYSQL_COLLATION):
                conn_args["collation"] = user_input[CONF_MYSQL_COLLATION]

            conn = mysql.connector.connect(**conn_args)
            conn.close()

        await self.hass.async_add_executor_job(connect)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step when a user adds the integration via UI."""
        errors = {}

        if user_input is not None:
            try:
                await self._test_connection(user_input)

                unique_id = f"{user_input[CONF_MYSQL_HOST]}_{user_input[CONF_MYSQL_DB]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = f"MySQL: {user_input[CONF_MYSQL_HOST]}/{user_input[CONF_MYSQL_DB]}"
                return self.async_create_entry(title=title, data=user_input)
            except Error as err:
                _LOGGER.error("MySQL connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=get_schema(user_input or {}),
            errors=errors
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Handle import from configuration.yaml."""
        unique_id = f"{import_data[CONF_MYSQL_HOST]}_{import_data[CONF_MYSQL_DB]}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        _LOGGER.warning(
            "Imported mysql_query settings from configuration.yaml. "
            "IMPORTANT: Please remove the 'mysql_query' section from your configuration.yaml "
            "and restart Home Assistant to complete the migration."
        )

        title = f"MySQL: {import_data[CONF_MYSQL_HOST]}/{import_data[CONF_MYSQL_DB]} (Imported)"
        return self.async_create_entry(title=title, data=import_data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> MySQLQueryOptionsFlow:
        """Create the options flow handler."""
        return MySQLQueryOptionsFlow(config_entry)


class MySQLQueryOptionsFlow(config_entries.OptionsFlow):
    """Handle options (re-configuration) for the integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # Hernoemd naar _config_entry om conflict met de gereserveerde property te voorkomen
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the settings via the Configure button."""
        if user_input is not None:
            # Update de entry data direct om wijzigingen op te slaan
            self.hass.config_entries.async_update_entry(self._config_entry, data=user_input)
            return self.async_create_entry(title="", data={})

        # Gebruik de hernoemde variabele om huidige instellingen op te halen
        current_settings = dict(self._config_entry.data)

        return self.async_show_form(
            step_id="init",
            data_schema=get_schema(current_settings)
        )