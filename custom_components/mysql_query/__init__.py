"""Support for mysql_query notification."""

from __future__ import annotations

import mysql.connector
import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.typing import ConfigType
from typing import Final

DOMAIN = "mysql_query"

ATTR_NAME = "query"
DEFAULT_QUERY = "select 1 from dual"
CONF_MYSQL_HOST = "mysql_host"
CONF_MYSQL_USERNAME = "mysql_username"
CONF_MYSQL_PASSWORD = "mysql_password"
CONF_MYSQL_DB = "mysql_db"
CONF_MYSQL_TIMEOUT = "mysql_timeout"
QUERY = "query"

_LOGGER = logging.getLogger(__name__)

# Defaults
DEFAULT_MYSQL_TIMEOUT = 10

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_MYSQL_HOST): cv.string,
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
# SERVICE_QUERY_SCHEMA: vol.Schema({vol.Required("query"): cv.string})
SERVICE_QUERY_SCHEMA: Final = vol.All(
    cv.has_at_least_one_key(QUERY), cv.has_at_most_one_key(QUERY)
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config[DOMAIN]
    mysql_host = conf.get(CONF_MYSQL_HOST)
    mysql_username = conf.get(CONF_MYSQL_USERNAME)
    mysql_password = conf.get(CONF_MYSQL_PASSWORD)
    mysql_db = conf.get(CONF_MYSQL_DB)
    mysql_timeout = conf.get(CONF_MYSQL_TIMEOUT)
    try:
        _cnx = mysql.connector.connect(
            host=mysql_host,
            username=mysql_username,
            password=mysql_password,
            db=mysql_db,
            connection_timeout=mysql_timeout,
        )
    except:
        _LOGGER.error("Could not connect to mysql server")
        _cnx = None

    hass.data["mysql_connection"] = _cnx

    def query(call):
        """Handle the service call."""
        _query = call.data.get(ATTR_NAME, DEFAULT_QUERY)

        if _query != "":
            _cnx.reconnect()
            _cursor = _cnx.cursor(
                buffered=True
            )  # (Why buffered=True? I don't have a clue...)
            _cursor.execute(_query)
            _cols = _cursor.description
            _rows = _cursor.fetchall()

            if _rows is not None:
                _result = []

                for _r, _row in enumerate(_rows):
                    _values = {}
                    for _c, _col in enumerate(_cols):
                        _values[_col[0]] = _row[_c]
                    _result.append(_values)
                return {"result": _result}

    hass.services.async_register(
        DOMAIN,
        ATTR_NAME,
        query,
        schema=SERVICE_QUERY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.info("Service is now set up")

    return True
