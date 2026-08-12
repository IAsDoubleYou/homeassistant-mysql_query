"""The MySQL Query Service integration."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
from typing import Any, Final, TypedDict

import aiomysql

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    DOMAIN,
    SERVICE_QUERY,
    SERVICE_EXECUTE,
    ATTR_QUERY,
    ATTR_VALUES,
    ATTR_DB4QUERY,
    ATTR_CONFIG_ENTRY,
    CONF_MYSQL_DB,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_ROW_LIMIT,
    DEFAULT_MYSQL_TIMEOUT,
    DEFAULT_ROW_LIMIT,
)
from .db import async_create_pool, error_details

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_QUERY): cv.string,
        # Values bound to the %s placeholders of a parameterized query. Only
        # scalars are accepted: those are the types MySQL can bind to a single
        # placeholder. Strings are allowed to still be templates here, because
        # a call made straight through the API arrives unrendered.
        vol.Optional(ATTR_VALUES): vol.All(
            cv.ensure_list, [vol.Any(None, bool, int, float, str)]
        ),
        vol.Optional(ATTR_DB4QUERY): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY): cv.string,
    }
)

class QueryResult(TypedDict):
    """Result payload returned by a single executed statement."""

    res: list[dict[str, Any]]
    cols: list[str]
    rows_found: int | None
    rows_returned: int | None
    rows_affected: int | None
    gen_id: int | None
    statement: str


@dataclass(slots=True)
class MySQLInstance:
    """Runtime data of one configured database."""

    pool: aiomysql.Pool
    config: Mapping[str, Any]
    title: str
    # One lock per config entry. Home Assistant can fire several service calls
    # at the same time, and MySQL only handles one statement per connection at
    # a time, so the lock keeps the calls from interleaving.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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


def render_value(hass: HomeAssistant, value: Any) -> Any:
    """Render a single placeholder value, keeping its native Python type.

    A call from an automation arrives with its templates already rendered, but
    one made through the API or the developer tools does not, so render them
    here as well. Rendering is native (``parse_result=True``) so a template
    that yields a number, a boolean or none is bound as an int, float, bool or
    NULL instead of as text.

    Literal strings are handed to MySQL untouched: parsing those as well would
    turn a value like "1,2" into a tuple and "42" into an int, which would
    change what ends up in the database.
    """
    if not isinstance(value, str):
        return value

    template = Template(value, hass)
    if template.is_static:
        return value

    try:
        return template.async_render(parse_result=True)
    except TemplateError as err:
        raise HomeAssistantError(f"Invalid template in values: {err}") from err


def render_values(
    hass: HomeAssistant, values: Sequence[Any] | None
) -> tuple[Any, ...] | None:
    """Render the placeholder values of a parameterized query.

    Returns None when there is nothing to bind. That is not the same as an
    empty tuple: the driver only interpolates the statement when the arguments
    are not None, so an empty tuple would break a plain query that contains a
    literal percent sign, such as LIKE '%text%'.
    """
    if not values:
        return None

    return tuple(render_value(hass, value) for value in values)


async def _async_execute_statement(
    conn: aiomysql.Connection,
    query: str,
    row_limit: int,
    database: str | None,
    values: Sequence[Any] | None = None,
) -> QueryResult:
    """Execute one statement on an open connection and collect its result."""
    async with conn.cursor(aiomysql.DictCursor) as cursor:
        # Passing the values to the driver keeps them out of the statement
        # itself: it escapes and quotes them per type, so the query cannot be
        # rewritten by whatever they contain.
        await cursor.execute(query, values)

        res_list: list[dict[str, Any]] = []
        cols: list[str] = []
        # Only statements that produced a result set carry a description.
        is_select = cursor.description is not None

        if is_select:
            cols = [column[0] for column in cursor.description]
            for row in await cursor.fetchmany(row_limit):
                res_list.append({k: to_json_serializable(v) for k, v in row.items()})

            if await cursor.fetchone():
                _LOGGER.warning(
                    "Query on %s truncated: the result set exceeds the limit of %s rows.",
                    database,
                    row_limit,
                )
        elif not conn.get_autocommit():
            await conn.commit()

        return {
            "res": res_list,
            "cols": cols,
            "rows_found": cursor.rowcount if is_select else None,
            "rows_returned": len(res_list) if is_select else None,
            "rows_affected": cursor.rowcount if not is_select else None,
            "gen_id": cursor.lastrowid or None,
            "statement": query,
        }


async def _async_restore_database(conn: aiomysql.Connection, database: str) -> None:
    """Point a pooled connection back at the database of its config entry."""
    try:
        await conn.select_db(database)
    except (aiomysql.Error, OSError):
        # Never return a connection to the pool while it still points at
        # another database: closing it makes the pool build a fresh one.
        _LOGGER.warning(
            "Could not switch back to database %s; dropping the connection", database
        )
        conn.close()


async def _async_run_statement(
    instance: MySQLInstance,
    query: str,
    db4query: str | None,
    row_limit: int,
    values: Sequence[Any] | None = None,
) -> QueryResult:
    """Run a statement on a connection borrowed from the pool."""
    default_db = instance.config.get(CONF_MYSQL_DB)
    timeout = int(instance.config.get(CONF_MYSQL_TIMEOUT, DEFAULT_MYSQL_TIMEOUT))
    # A one-off query against another database reuses the pooled connection and
    # switches back afterwards, instead of paying for a new connection.
    switch_db = bool(
        db4query and default_db and db4query.lower() != str(default_db).lower()
    )

    # Never wait for a free connection indefinitely; the pool is bounded.
    async with asyncio.timeout(timeout):
        conn = await instance.pool.acquire()

    try:
        # The server can have dropped this connection while it sat idle in the
        # pool (wait_timeout); ping() reconnects instead of failing the call.
        await conn.ping(reconnect=True)

        if switch_db:
            await conn.select_db(db4query)
        try:
            return await _async_execute_statement(
                conn, query, row_limit, db4query or default_db, values
            )
        finally:
            if switch_db:
                await _async_restore_database(conn, str(default_db))
    finally:
        instance.pool.release(conn)


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
    instances: dict[str, MySQLInstance] = hass.data.setdefault(DOMAIN, {})
    config = entry.data

    try:
        pool = await async_create_pool(config)
    except Exception as e:
        _LOGGER.error("Could not connect to mysql server for %s: %s", entry.title, str(e), exc_info=True)
        return False

    instances[entry.entry_id] = MySQLInstance(
        pool=pool, config=config, title=entry.title
    )

    # Changed settings must rebuild the pool, so reload the entry on update.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    async def async_handle_service(call: ServiceCall) -> ServiceResponse:
        """Handle service calls with instance selection and row limiting."""
        _query = call.data[ATTR_QUERY]
        _values = call.data.get(ATTR_VALUES)
        _db4query = call.data.get(ATTR_DB4QUERY)
        target_entry_id = call.data.get(ATTR_CONFIG_ENTRY)

        if target_entry_id:
            instance = instances.get(target_entry_id)
        else:
            instance = next(iter(instances.values()), None)

        if instance is None:
            raise HomeAssistantError("No database instance available.")

        inst_config = instance.config
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

        try:
            # Rendering inside the try keeps a broken template on the same
            # error path as a broken statement: reported in the response for
            # execute, raised for query.
            rendered_values = render_values(hass, _values)

            # Serialise the calls on this entry: without the lock two service
            # calls would push their statements onto the same connection at
            # the same time and read each other's results.
            async with instance.lock:
                start_time = time.perf_counter()
                db_output = await _async_run_statement(
                    instance, _query, _db4query, row_limit, rendered_values
                )
                execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

            response.update({
                "succeeded": True,
                "result": db_output["res"],
                "column_names": db_output["cols"],
                "rows_found": db_output["rows_found"],
                "rows_returned": db_output["rows_returned"],
                "rows_affected": db_output["rows_affected"],
                "generated_id": db_output["gen_id"],
                "statement": db_output["statement"],
                "execution_time_ms": execution_time_ms
            })

            if call.service == SERVICE_QUERY:
                return {"result": response["result"]}
            return response

        except aiomysql.Error as e:
            errno, message = error_details(e)
            _LOGGER.error("MySQL Error [%s]: %s", errno, message)
            if call.service == SERVICE_QUERY:
                raise HomeAssistantError(f"MySQL Error: {message}") from e
            response["error"] = {"message": message, "errno": errno, "sqlstate": None}
            return response
        except TimeoutError as e:
            message = "Timed out waiting for a free connection from the pool"
            _LOGGER.error("%s (%s)", message, instance.title)
            if call.service == SERVICE_QUERY:
                raise HomeAssistantError(message) from e
            response["error"]["message"] = message
            return response
        except Exception as e:
            _LOGGER.error("General Error: %s", str(e))
            if call.service == SERVICE_QUERY:
                raise HomeAssistantError(f"Error: {str(e)}")
            response["error"]["message"] = str(e)
            return response

    # The services are global, not per entry: registering them once keeps a
    # second config entry from replacing the handler of the first.
    if not hass.services.has_service(DOMAIN, SERVICE_QUERY):
        hass.services.async_register(DOMAIN, SERVICE_QUERY, async_handle_service, schema=SERVICE_SCHEMA, supports_response=SupportsResponse.ONLY)
    if not hass.services.has_service(DOMAIN, SERVICE_EXECUTE):
        hass.services.async_register(DOMAIN, SERVICE_EXECUTE, async_handle_service, schema=SERVICE_SCHEMA, supports_response=SupportsResponse.ONLY)

    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after its settings changed."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    instances: dict[str, MySQLInstance] = hass.data.get(DOMAIN, {})
    instance = instances.pop(entry.entry_id, None)
    if instance is None:
        return True

    # Taking the lock first lets a service call that is still running finish
    # before its connection is pulled out from under it.
    async with instance.lock:
        instance.pool.close()
        await instance.pool.wait_closed()

    if not instances:
        hass.services.async_remove(DOMAIN, SERVICE_QUERY)
        hass.services.async_remove(DOMAIN, SERVICE_EXECUTE)

    return True
