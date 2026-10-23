"""Diagnostics of the MySQL Query integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from . import MySQLQueryConfigEntry
from .const import (
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_USERNAME,
)

# Everything that says where the database is or how to log in. The title and
# the unique ID of the entry are built from the host, the port and the database
# name, so they are masked as well.
TO_REDACT_CONNECTION = {
    CONF_MYSQL_HOST,
    CONF_MYSQL_PORT,
    CONF_MYSQL_USERNAME,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_DB,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MySQLQueryConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The connection details and the credentials are masked. No statement and no
    row of the database is included: this integration keeps neither.
    """
    pool = None
    if entry.state is ConfigEntryState.LOADED:
        driver_pool = entry.runtime_data.pool
        pool = {
            "minimum": int(driver_pool.minsize),
            "maximum": int(driver_pool.maxsize),
            "open": int(driver_pool.size),
            "idle": int(driver_pool.freesize),
        }

    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "state": str(entry.state),
            "title": "**REDACTED**",
            "unique_id": "**REDACTED**",
            "data": async_redact_data(dict(entry.data), TO_REDACT_CONNECTION),
            "options": dict(entry.options),
        },
        "pool": pool,
    }
