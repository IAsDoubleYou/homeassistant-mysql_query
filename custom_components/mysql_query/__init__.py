"""Support for mysql_query service."""

from __future__ import annotations

import mysql.connector
import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from functools import partial
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import HomeAssistantError
from typing import Final

DOMAIN = "mysql_query"
SERVICE = "query"

ATTR_QUERY = "query"
ATTR_DB4QUERY = "db4query"
CONF_MYSQL_HOST = "mysql_host"
CONF_MYSQL_USERNAME = "mysql_username"
CONF_MYSQL_PASSWORD = "mysql_password"
CONF_MYSQL_DB = "mysql_db"
CONF_MYSQL_PORT = "mysql_port"
CONF_MYSQL_TIMEOUT = "mysql_timeout"
CONF_MYSQL_CHARSET = "mysql_charset"
CONF_MYSQL_COLLATION = "mysql_collation"
CONF_AUTOCOMMIT = "mysql_autocommit"
QUERY = "query"
DB4QUERY = "db4query"

_LOGGER = logging.getLogger(__name__)

# Defaults
DEFAULT_MYSQL_TIMEOUT = 10
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_AUTOCOMMIT = True

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_MYSQL_HOST): cv.string,
                vol.Optional(CONF_MYSQL_PORT, default=DEFAULT_MYSQL_PORT): vol.Coerce(
                    int
                ),
                vol.Required(CONF_MYSQL_USERNAME): cv.string,
                vol.Required(CONF_MYSQL_PASSWORD): cv.string,
                vol.Required(CONF_MYSQL_DB): cv.string,
                vol.Optional(CONF_MYSQL_TIMEOUT, default=DEFAULT_MYSQL_TIMEOUT): vol.Coerce(int),
                vol.Optional(CONF_MYSQL_CHARSET): cv.string,
                vol.Optional(CONF_MYSQL_COLLATION): cv.string,
                vol.Optional(CONF_AUTOCOMMIT, default=DEFAULT_MYSQL_AUTOCOMMIT): cv.boolean,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_QUERY: Final = "query"
SERVICE_DB4QUERY: Final = "db4query"

SERVICE_QUERY_SCHEMA: Final = vol.All(
    cv.has_at_least_one_key(QUERY), cv.has_at_most_one_key(QUERY)
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config[DOMAIN]
    mysql_host = conf.get(CONF_MYSQL_HOST)
    mysql_port = conf.get(CONF_MYSQL_PORT, DEFAULT_MYSQL_PORT)
    mysql_username = conf.get(CONF_MYSQL_USERNAME)
    mysql_password = conf.get(CONF_MYSQL_PASSWORD)
    mysql_db = conf.get(CONF_MYSQL_DB)
    mysql_timeout = conf.get(CONF_MYSQL_TIMEOUT, DEFAULT_MYSQL_TIMEOUT)
    mysql_collation = conf.get(CONF_MYSQL_COLLATION, None)
    mysql_charset = conf.get(CONF_MYSQL_CHARSET, None)
    mysql_autocommit = conf.get(CONF_AUTOCOMMIT, DEFAULT_MYSQL_AUTOCOMMIT)

    # Standard required connection arguments
    connect_kwargs = {
        "host": mysql_host,
        "user": mysql_username,
        "password": mysql_password,
        "database": mysql_db,
        "port": str(mysql_port),
        "autocommit": mysql_autocommit,
    }

    # Additional, optional connection arguments
    if mysql_charset is not None:
        connect_kwargs["charset"] = mysql_charset
    if mysql_collation is not None:
        connect_kwargs["collation"] = mysql_collation

    try:
        _LOGGER.info(f"Establishing connection with database {
                     mysql_db} at {mysql_host}:{mysql_port}")
        _cnx = await hass.async_add_executor_job(partial(mysql.connector.connect, **connect_kwargs))

    except Exception as e:
        # Log the rror with the full stack trace
        _LOGGER.error("Could not connect to mysql server: %s",
                      str(e), exc_info=True)
        _cnx = None
        raise HomeAssistantError(
            f"Could not connect to mysql server: {str(e)}")

    _LOGGER.info(f"Connection established with database {
                 mysql_db} at {mysql_host}:{mysql_port}")
    hass.data["mysql_connection"] = _cnx

    def replace_blob_with_description(value):
        """
        Check if the value is a large object and if so return a description instead of the value.
        """
        if isinstance(value, (bytes, bytearray)):  # Detect BLOBs
            return "BLOB"
        elif isinstance(value, memoryview):  # Other large objects
            return "LARGE OBJECT"
        else:
            return value  # Don't adjust other, normal values

    def handle_query(call):
        """Handle the service call."""
        _query = call.data.get(ATTR_QUERY)
        _LOGGER.debug(f"received query: {_query}")

        _result = []

        if _query != None:
            _db4query = call.data.get(ATTR_DB4QUERY, None)
            if (
                (_db4query is not None)
                and (_db4query != "")
                and (_db4query.lower() != mysql_db.lower())
            ):
                _LOGGER.debug(f"Provided database for this query: {_db4query}")

                try:
                    # Override the default database with the one provided for this query
                    connect_kwargs["database"] = _db4query

                    _LOGGER.debug(f"Establishing connection with database {
                                  _db4query} at {mysql_host}:{mysql_port}")
                    _cnx4qry = mysql.connector.connect(**connect_kwargs)

                except Exception as e:
                    # Log the rror with the full stack trace
                    _LOGGER.error(
                        "Could not connect to mysql server: %s", str(e), exc_info=True)
                    _cnx4qry = None
                    raise HomeAssistantError(
                        f"Could not connect to mysql server: {str(e)}")
            else:
                _cnx4qry = _cnx

            if _cnx4qry is not None:
                try:
                    _cnx4qry.ping(reconnect=True)
                    _cursor = _cnx4qry.cursor(buffered=True)
                    _LOGGER.debug(f"Executing query: {_query}")
                    _cursor.execute(_query)

                    if _cursor.with_rows:
                        _cols = _cursor.description
                        _LOGGER.debug(f"Fetching all records")
                        _rows = _cursor.fetchall()
                    else:
                        _rows = None

                except Exception as e:
                    raise HomeAssistantError(f"{str(e)}")

                if _rows is not None:
                    _i = 0
                    _LOGGER.debug(f"Found {len(_rows)} rows")
                    for _r, _row in enumerate(_rows):
                        _i+1
                        _LOGGER.debug(f"Fetching values")
                        _values = {}
                        for _c, _col in enumerate(_cols):
                            _values[_col[0]] = replace_blob_with_description(
                                _row[_c])
                        _result.append(_values)
                        _LOGGER.debug(f"{_i}: _values: {_values}")
        else:
            _LOGGER.error("No query provided")
            raise HomeAssistantError("No query provided")

        _LOGGER.debug(f"Returning result: {_result}")
        return {"result": _result}

    hass.services.async_register(
        DOMAIN,
        SERVICE,
        handle_query,
        schema=SERVICE_QUERY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.info("Service mysql_query is now set up")

    return True
