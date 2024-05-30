"""Support for mysql_query service."""

from __future__ import annotations

import mysql.connector
import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.typing import ConfigType
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
QUERY = "query"
DB4QUERY = "db4query"

_LOGGER = logging.getLogger(__name__)

# Defaults
DEFAULT_MYSQL_TIMEOUT = 10
DEFAULT_MYSQL_PORT = 3306

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
                vol.Optional(
                    CONF_MYSQL_TIMEOUT, default=DEFAULT_MYSQL_TIMEOUT
                ): vol.Coerce(int),
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
    try:
        _cnx = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            username=mysql_username,
            password=mysql_password,
            db=mysql_db,
            connection_timeout=mysql_timeout,
        )
    except:
        _LOGGER.error("Could not connect to mysql server")
        _cnx = None

    hass.data["mysql_connection"] = _cnx

    def handle_query(call):
        """Handle the service call."""
        _query = call.data.get(ATTR_QUERY)

        _result = []

            _db4query = call.data.get(ATTR_DB4QUERY, None)

            if (
                (_db4query is not None)
                and (_db4query != "")
                and (_db4query.lower() != mysql_db.lower())
            ):
                try:
                    _cnx4qry = mysql.connector.connect(
                        host=mysql_host,
                        port=mysql_port,
                        username=mysql_username,
                        password=mysql_password,
                        db=_db4query,
                        connection_timeout=mysql_timeout,
                    )
                except:
                    _LOGGER.error("Could not connect to mysql server")
                    _cnx4qry = None
            else:
                _cnx4qry = _cnx

            if _cnx4qry is not None:
                _cnx4qry.reconnect()
                _cursor = _cnx4qry.cursor(buffered=True)
                _cursor.execute(_query)
                _cols = _cursor.description
                _rows = _cursor.fetchall()

                if _rows is not None:
                    for _r, _row in enumerate(_rows):
                        _values = {}
                        for _c, _col in enumerate(_cols):
                            _values[_col[0]] = _row[_c]
                        _result.append(_values)
        else:
            _LOGGER.error(
                "Query does not start with one of the allowed keywords 'SELECT' or 'WITH' : [ "
                + _query
                + " ]"
            )

        return {"result": _result}

    hass.services.async_register(
        DOMAIN,
        SERVICE,
        handle_query,
        schema=SERVICE_QUERY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.info("Service is now set up")

    return True
