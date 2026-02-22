"""The MySQL Query Service integration."""
from __future__ import annotations

import logging
import time
import mysql.connector
from mysql.connector import Error
from functools import partial
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    DOMAIN,
    SERVICE_QUERY,
    SERVICE_EXECUTE,
    ATTR_QUERY,
    ATTR_DB4QUERY,
    ATTR_CONFIG_ENTRY,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PORT,
    CONF_MYSQL_USERNAME,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_DB,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_CHARSET,
    CONF_MYSQL_COLLATION,
    CONF_AUTOCOMMIT,
)

_LOGGER = logging.getLogger(__name__)

# Service schema: query is required, config_entry and db4query are optional
SERVICE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_DB4QUERY): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY): cv.string,
    }
)

def replace_blob_with_description(value: Any) -> Any:
    """Replace binary data with a string description for JSON compatibility."""
    if isinstance(value, (bytes, bytearray)):
        return "BLOB"
    elif isinstance(value, memoryview):
        return "LARGE OBJECT"
    else:
        return value

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the mysql_query component from YAML (Legacy/Import)."""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=config[DOMAIN],
            )
        )
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up mysql_query from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = entry.data

    def connect():
        conn_args = {
            "host": config[CONF_MYSQL_HOST],
            "port": str(config[CONF_MYSQL_PORT]),
            "user": config[CONF_MYSQL_USERNAME],
            "password": config[CONF_MYSQL_PASSWORD],
            "database": config[CONF_MYSQL_DB],
            "connection_timeout": config.get(CONF_MYSQL_TIMEOUT, 10),
            "autocommit": config.get(CONF_AUTOCOMMIT, True),
        }
        if config.get(CONF_MYSQL_CHARSET):
            conn_args["charset"] = config[CONF_MYSQL_CHARSET]
        if config.get(CONF_MYSQL_COLLATION):
            conn_args["collation"] = config[CONF_MYSQL_COLLATION]

        _LOGGER.info(f"Establishing connection with database {config[CONF_MYSQL_DB]} at {config[CONF_MYSQL_HOST]}:{config[CONF_MYSQL_PORT]}")
        return mysql.connector.connect(**conn_args)

    try:
        cnx = await hass.async_add_executor_job(connect)
        _LOGGER.info(f"Connection established with database {config[CONF_MYSQL_DB]} at {config[CONF_MYSQL_HOST]}:{config[CONF_MYSQL_PORT]}")

        hass.data[DOMAIN][entry.entry_id] = {
            "cnx": cnx,
            "config": config,
            "title": entry.title
        }
    except Exception as e:
        _LOGGER.error("Could not connect to mysql server for %s: %s", entry.title, str(e), exc_info=True)
        return False

    async def async_handle_service(call: ServiceCall) -> ServiceResponse:
        """Handle service calls with instance selection and legacy compatibility."""
        _query = call.data[ATTR_QUERY]
        _db4query = call.data.get(ATTR_DB4QUERY)
        target_entry_id = call.data.get(ATTR_CONFIG_ENTRY)

        # 1. Select instance (Target ID or fallback to first available)
        if target_entry_id:
            instance = hass.data[DOMAIN].get(target_entry_id)
        else:
            instance = next(iter(hass.data[DOMAIN].values()), None)

        if not instance:
            raise HomeAssistantError("No database instance available. Please configure the integration.")

        _cnx = instance["cnx"]
        inst_config = instance["config"]
        mysql_db = inst_config[CONF_MYSQL_DB]
        target_db_name = _db4query if (_db4query and _db4query != "") else mysql_db

        # 2. Prepare response structure
        response = {
            "succeeded": False, "execution_time_ms": 0, "database": target_db_name,
            "user": inst_config[CONF_MYSQL_USERNAME], "statement": _query,
            "rows_affected": 0, "generated_id": None, "column_names": [],
            "error": {"message": None, "errno": None, "sqlstate": None}, "result": []
        }

        start_time = time.perf_counter()

        def execute_on_db():
            # Connection management
            active_cnx = _cnx
            if _db4query and _db4query.lower() != mysql_db.lower():
                temp_kwargs = {
                    "host": inst_config[CONF_MYSQL_HOST], "user": inst_config[CONF_MYSQL_USERNAME],
                    "password": inst_config[CONF_MYSQL_PASSWORD], "database": _db4query,
                    "port": str(inst_config[CONF_MYSQL_PORT]),
                }
                active_cnx = mysql.connector.connect(**temp_kwargs)
            else:
                if not active_cnx.is_connected():
                    active_cnx.ping(reconnect=True)

            try:
                _cursor = active_cnx.cursor(buffered=True, dictionary=True)
                _cursor.execute(_query)

                res_list = []
                cols = []
                if _cursor.with_rows:
                    cols = list(_cursor.column_names)
                    for row in _cursor.fetchall():
                        res_list.append({k: replace_blob_with_description(v) for k, v in row.items()})

                # Commit if not a select
                if not _cursor.with_rows:
                    active_cnx.commit()

                return {
                    "res": res_list,
                    "cols": cols,
                    "rows_affected": _cursor.rowcount,
                    "gen_id": _cursor.lastrowid if _cursor.lastrowid != 0 else None,
                    "statement": _cursor.statement
                }
            finally:
                _cursor.close()
                if active_cnx is not _cnx:
                    active_cnx.close()

        try:
            db_output = await hass.async_add_executor_job(execute_on_db)

            # Populate modern response
            response.update({
                "succeeded": True,
                "result": db_output["res"],
                "column_names": db_output["cols"],
                "rows_affected": db_output["rows_affected"],
                "generated_id": db_output["gen_id"],
                "statement": db_output["statement"],
                "execution_time_ms": round((time.perf_counter() - start_time) * 1000, 2)
            })

            # 3. Return format based on service called
            if call.service == SERVICE_QUERY:
                return {"result": response["result"]}

            return response

        except Error as e:
            _LOGGER.error("MySQL Error [%s]: %s", e.errno, e.msg)
            if call.service == SERVICE_QUERY:
                raise HomeAssistantError(f"MySQL Error: {e.msg}")

            response["error"] = {"message": e.msg, "errno": e.errno, "sqlstate": e.sqlstate}
            response["execution_time_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
            return response
        except Exception as e:
            _LOGGER.error("General Error: %s", str(e))
            if call.service == SERVICE_QUERY:
                raise HomeAssistantError(f"Error: {str(e)}")

            response["error"]["message"] = str(e)
            return response

    # Register Services
    hass.services.async_register(
        DOMAIN, SERVICE_QUERY, async_handle_service, schema=SERVICE_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_EXECUTE, async_handle_service, schema=SERVICE_SCHEMA, supports_response=SupportsResponse.ONLY
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    instance = hass.data[DOMAIN].pop(entry.entry_id, None)
    if instance and instance["cnx"].is_connected():
        await hass.async_add_executor_job(instance["cnx"].close)
    return True