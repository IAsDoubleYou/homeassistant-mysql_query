"""The MySQL Query Service integration."""
from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
import mysql.connector
from mysql.connector import Error
from mysql.connector.abstracts import MySQLConnectionAbstract
from typing import Any, Final, TypedDict

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
    CONF_ROW_LIMIT,
    DEFAULT_ROW_LIMIT,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_DB4QUERY): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY): cv.string,
    }
)

class QueryResult(TypedDict):
    """Result payload returned by execute_on_db."""

    res: list[dict[str, Any]]
    cols: list[str]
    rows_found: int | None
    rows_returned: int | None
    rows_affected: int | None
    gen_id: int | None
    statement: str


def format_timedelta(value: timedelta) -> str:
    """Format a MySQL TIME value as ``[-]HH:MM:SS[.ffffff]``.

    MySQL TIME columns are returned as ``timedelta`` objects, which have no
    ``isoformat()``. Their ``str()`` renders spans of a day or more as
    "1 day, 2:00:00", so build the MySQL-style representation explicitly.
    """
    total_seconds = value.total_seconds()
    sign = "-" if total_seconds < 0 else ""
    remainder = abs(value)

    hours, rest = divmod(remainder.days * 86400 + remainder.seconds, 3600)
    minutes, seconds = divmod(rest, 60)

    formatted = f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}"
    if remainder.microseconds:
        formatted = f"{formatted}.{remainder.microseconds:06d}"
    return formatted


def to_json_serializable(value: Any) -> Any:
    """Convert a MySQL column value into something HA can serialise to JSON.

    Service responses are handed to Home Assistant's JSON encoder, which only
    accepts the primitive JSON types. The MySQL connector, however, returns
    native Python objects for several column types (DECIMAL, DATE, DATETIME,
    TIME, SET, BLOB, ...), so map them onto JSON-friendly equivalents here.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value

    if isinstance(value, float):
        # NaN/Infinity are not valid JSON and are rejected by HA's encoder.
        return value if math.isfinite(value) else None

    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None

    if isinstance(value, (bytes, bytearray)):
        return "BLOB"

    if isinstance(value, memoryview):
        return "LARGE OBJECT"

    if isinstance(value, timedelta):
        return format_timedelta(value)

    # datetime is a subclass of date, so both are covered by isoformat().
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): to_json_serializable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [to_json_serializable(item) for item in value]

    if isinstance(value, (set, frozenset)):
        # MySQL SET columns arrive as a Python set; sort for a stable response.
        converted = [to_json_serializable(item) for item in value]
        try:
            return sorted(converted)
        except TypeError:
            return converted

    return str(value)


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

    def connect() -> MySQLConnectionAbstract:
        """Establish a connection with safe defaults for optional fields."""
        db_host = config.get(CONF_MYSQL_HOST)
        db_port = config.get(CONF_MYSQL_PORT, 3306)
        db_user = config.get(CONF_MYSQL_USERNAME)
        db_pass = config.get(CONF_MYSQL_PASSWORD)
        db_name = config.get(CONF_MYSQL_DB)

        conn_args: dict[str, Any] = {
            "host": db_host,
            "port": int(db_port),
            "user": db_user,
            "password": db_pass,
            "database": db_name,
            "connection_timeout": int(config.get(CONF_MYSQL_TIMEOUT, 10)),
            "autocommit": bool(config.get(CONF_AUTOCOMMIT, True)),
        }

        charset = config.get(CONF_MYSQL_CHARSET)
        if charset:
            conn_args["charset"] = charset

        collation = config.get(CONF_MYSQL_COLLATION)
        if collation:
            conn_args["collation"] = collation

        _LOGGER.info(f"Establishing connection with database {db_name} at {db_host}:{db_port}")
        return mysql.connector.connect(**conn_args)

    try:
        cnx = await hass.async_add_executor_job(connect)
        hass.data[DOMAIN][entry.entry_id] = {
            "cnx": cnx,
            "config": config,
            "title": entry.title
        }
    except Exception as e:
        _LOGGER.error("Could not connect to mysql server for %s: %s", entry.title, str(e), exc_info=True)
        return False

    async def async_handle_service(call: ServiceCall) -> ServiceResponse:
        """Handle service calls with instance selection and row limiting."""
        _query = call.data[ATTR_QUERY]
        _db4query = call.data.get(ATTR_DB4QUERY)
        target_entry_id = call.data.get(ATTR_CONFIG_ENTRY)

        if target_entry_id:
            instance = hass.data[DOMAIN].get(target_entry_id)
        else:
            instance = next(iter(hass.data[DOMAIN].values()), None)

        if not instance:
            raise HomeAssistantError("No database instance available.")

        _cnx = instance["cnx"]
        inst_config = instance["config"]
        mysql_db = inst_config.get(CONF_MYSQL_DB)
        target_db_name = _db4query if (_db4query and _db4query != "") else mysql_db
        
        row_limit = int(inst_config.get(CONF_ROW_LIMIT, DEFAULT_ROW_LIMIT))
        if row_limit < 1:
            row_limit = DEFAULT_ROW_LIMIT

        response = {
            "succeeded": False, "execution_time_ms": 0, "database": target_db_name,
            "user": inst_config.get(CONF_MYSQL_USERNAME), "statement": _query,
            "rows_found": None, "rows_returned": None, "rows_affected": None, 
            "generated_id": None, "column_names": [],
            "error": {"message": None, "errno": None, "sqlstate": None}, "result": []
        }

        start_time = time.perf_counter()

        def execute_on_db() -> QueryResult:
            active_cnx = _cnx
            if _db4query and str(_db4query).lower() != str(mysql_db).lower():
                temp_kwargs: dict[str, Any] = {
                    "host": inst_config.get(CONF_MYSQL_HOST),
                    "user": inst_config.get(CONF_MYSQL_USERNAME),
                    "password": inst_config.get(CONF_MYSQL_PASSWORD),
                    "database": _db4query,
                    "port": int(inst_config.get(CONF_MYSQL_PORT, 3306)),
                }
                active_cnx = mysql.connector.connect(**temp_kwargs)
            else:
                if not active_cnx.is_connected():
                    active_cnx.ping(reconnect=True)

            _cursor = None
            try:
                _cursor = active_cnx.cursor(buffered=True, dictionary=True)
                _cursor.execute(_query)

                res_list = []
                cols = []
                is_select = _cursor.with_rows

                if is_select:
                    cols = list(_cursor.column_names)
                    rows = _cursor.fetchmany(size=row_limit)
                    for row in rows:
                        res_list.append({k: to_json_serializable(v) for k, v in row.items()})
                    
                    if _cursor.fetchone():
                        _LOGGER.warning(
                            "Query in %s afgebroken: Resultaatset overschrijdt de limiet van %s rijen.",
                            target_db_name, row_limit
                        )

                if not is_select:
                    active_cnx.commit()

                return {
                    "res": res_list,
                    "cols": cols,
                    "rows_found": _cursor.rowcount if is_select else None,
                    "rows_returned": len(res_list) if is_select else None,
                    "rows_affected": _cursor.rowcount if not is_select else None,
                    "gen_id": _cursor.lastrowid if _cursor.lastrowid != 0 else None,
                    "statement": _cursor.statement
                }
            finally:
                if _cursor is not None:
                    _cursor.close()
                if active_cnx is not _cnx:
                    active_cnx.close()

        try:
            db_output = await hass.async_add_executor_job(execute_on_db)
            response.update({
                "succeeded": True,
                "result": db_output["res"],
                "column_names": db_output["cols"],
                "rows_found": db_output["rows_found"],
                "rows_returned": db_output["rows_returned"],
                "rows_affected": db_output["rows_affected"],
                "generated_id": db_output["gen_id"],
                "statement": db_output["statement"],
                "execution_time_ms": round((time.perf_counter() - start_time) * 1000, 2)
            })

            if call.service == SERVICE_QUERY:
                return {"result": response["result"]}
            return response

        except Error as e:
            _LOGGER.error("MySQL Error [%s]: %s", e.errno, e.msg)
            if call.service == SERVICE_QUERY:
                raise HomeAssistantError(f"MySQL Error: {e.msg}")
            response["error"] = {"message": e.msg, "errno": e.errno, "sqlstate": e.sqlstate}
            return response
        except Exception as e:
            _LOGGER.error("General Error: %s", str(e))
            if call.service == SERVICE_QUERY:
                raise HomeAssistantError(f"Error: {str(e)}")
            response["error"]["message"] = str(e)
            return response

    hass.services.async_register(DOMAIN, SERVICE_QUERY, async_handle_service, schema=SERVICE_SCHEMA, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_EXECUTE, async_handle_service, schema=SERVICE_SCHEMA, supports_response=SupportsResponse.ONLY)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    instance = hass.data[DOMAIN].pop(entry.entry_id, None)
    if instance is None:
        return True

    cnx = instance["cnx"]

    def close_connection() -> None:
        """Close the connection, if still open.

        Both is_connected() and close() talk to the server, so they must run
        in the executor instead of blocking the event loop.
        """
        if cnx.is_connected():
            cnx.close()

    await hass.async_add_executor_job(close_connection)
    return True