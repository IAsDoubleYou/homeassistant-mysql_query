"""Support for mysql_query service."""

from __future__ import annotations

import mysql.connector
from mysql.connector import Error
import logging
import time
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from functools import partial
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import HomeAssistantError
from typing import Final

DOMAIN = "mysql_query"
SERVICE = "query"
SERVICE_EXECUTE = "execute"

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
        _LOGGER.error("Could not connect to mysql server: %s",
                      str(e), exc_info=True)
        _cnx = None
        raise HomeAssistantError(
            f"Could not connect to mysql server: {str(e)}")

    _LOGGER.info(f"Connection established with database {
                 mysql_db} at {mysql_host}:{mysql_port}")
    hass.data["mysql_connection"] = _cnx

    def replace_blob_with_description(value):
        if isinstance(value, (bytes, bytearray)):
            return "BLOB"
        elif isinstance(value, memoryview):
            return "LARGE OBJECT"
        else:
            return value

    def handle_query(call):
        """Handle the original query service call (Legacy/Backward Compatible)."""
        _query = call.data.get(ATTR_QUERY)
        _result = []

        if _query != None:
            _db4query = call.data.get(ATTR_DB4QUERY, None)
            if ((_db4query is not None) and (_db4query != "") and (_db4query.lower() != mysql_db.lower())):
                try:
                    connect_kwargs["database"] = _db4query
                    _cnx4qry = mysql.connector.connect(**connect_kwargs)
                except Exception as e:
                    raise HomeAssistantError(f"Could not connect to mysql server: {str(e)}")
            else:
                _cnx4qry = _cnx

            if _cnx4qry is not None:
                try:
                    _cnx4qry.ping(reconnect=True)
                    _cursor = _cnx4qry.cursor(buffered=True)
                    _cursor.execute(_query)
                    if _cursor.with_rows:
                        _cols = _cursor.description
                        _rows = _cursor.fetchall()
                        for _row in _rows:
                            _values = {}
                            for _c, _col in enumerate(_cols):
                                _values[_col[0]] = replace_blob_with_description(_row[_c])
                            _result.append(_values)
                except Exception as e:
                    raise HomeAssistantError(f"{str(e)}")
        else:
            raise HomeAssistantError("No query provided")

        return {"result": _result}

    def handle_execute(call):
        """Handle the new execute service call with structured response."""
        _query = call.data.get(ATTR_QUERY)
        _db4query = call.data.get(ATTR_DB4QUERY, None)

        response = {
            "succeeded": False,
            "execution_time_ms": 0,
            "statement": _query,
            "results": [],
            "rows_affected": 0,
            "generated_id": None,
            "column_names": [],
            "error": {"message": None, "errno": None, "sqlstate": None}
        }

        start_time = time.perf_counter()

        try:
            # Connection logic
            if (_db4query and _db4query != "" and _db4query.lower() != mysql_db.lower()):
                temp_kwargs = connect_kwargs.copy()
                temp_kwargs["database"] = _db4query
                target_cnx = mysql.connector.connect(**temp_kwargs)
            else:
                target_cnx = _cnx
                target_cnx.ping(reconnect=True)

            _cursor = target_cnx.cursor(buffered=True)
            _cursor.execute(_query)

            response["statement"] = _cursor.statement
            response["rows_affected"] = _cursor.rowcount
            response["generated_id"] = _cursor.lastrowid if _cursor.lastrowid != 0 else None

            if _cursor.with_rows:
                _cols = _cursor.description
                response["column_names"] = [col[0] for col in _cols]
                _rows = _cursor.fetchall()
                for _row in _rows:
                    _values = {}
                    for _c, _col in enumerate(_cols):
                        _values[_col[0]] = replace_blob_with_description(_row[_c])
                    response["results"].append(_values)

            response["succeeded"] = True

        except Error as e:
            response["error"]["message"] = e.msg
            response["error"]["errno"] = e.errno
            response["error"]["sqlstate"] = e.sqlstate
            _LOGGER.error("MySQL Execute Error [%s]: %s", e.errno, e.msg)
        except Exception as e:
            response["error"]["message"] = str(e)
            _LOGGER.error("General Error during MySQL Execute: %s", str(e))
        finally:
            end_time = time.perf_counter()
            response["execution_time_ms"] = round((end_time - start_time) * 1000, 2)

        return response

    # Register Legacy Service
    hass.services.async_register(
        DOMAIN,
        SERVICE,
        handle_query,
        schema=SERVICE_QUERY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    # Register New Execute Service
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE,
        handle_execute,
        schema=SERVICE_QUERY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.info("Service mysql_query (query & execute) is now set up")
    return True