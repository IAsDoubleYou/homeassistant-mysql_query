"""The MySQL Query Service integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
import logging
import math
import time
from typing import Any, Final, TypedDict

import aiomysql
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, TemplateError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CONFIG_ENTRY,
    ATTR_DB4QUERY,
    ATTR_QUERY,
    ATTR_RAISE_ON_ERROR,
    ATTR_VALUES,
    CONF_MYSQL_DB,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_READONLY_CONNECTION,
    CONF_ROW_LIMIT,
    DEFAULT_MYSQL_TIMEOUT,
    DEFAULT_READONLY_CONNECTION,
    DEFAULT_ROW_LIMIT,
    DOMAIN,
    SERVICE_EXECUTE,
    SERVICE_QUERY,
)
from .db import (
    TLSUnavailableError,
    async_create_pool,
    async_verify_tls,
    error_details,
    tls_requested,
)
from .sql import is_read_only, split_statements

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

QUERY_SCHEMA: Final = vol.Schema(
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
        # Both services take this switch; only the default differs, so each
        # keeps the behaviour it always had unless the call says otherwise.
        vol.Optional(ATTR_RAISE_ON_ERROR, default=True): cv.boolean,
    }
)

EXECUTE_SCHEMA: Final = QUERY_SCHEMA.extend(
    {vol.Optional(ATTR_RAISE_ON_ERROR, default=False): cv.boolean}
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
    # Set by the user on the connection itself. A hard boundary: it refuses
    # execute without looking at the statement at all.
    read_only: bool = False
    # One lock per config entry. Home Assistant can fire several service calls
    # at the same time, and MySQL only handles one statement per connection at
    # a time, so the lock keeps the calls from interleaving.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


type MySQLQueryConfigEntry = ConfigEntry[MySQLInstance]


def _query_response(response: dict[str, Any]) -> dict[str, Any]:
    """Return the part of the response that query reports.

    The metadata a SELECT through execute used to carry, so moving such a
    call over to query loses nothing. error travels along on every call, not
    only on a failed one, so the shape a template sees never changes.
    """
    return {
        "result": response["result"],
        "succeeded": response["succeeded"],
        "execution_time_ms": response["execution_time_ms"],
        "rows_found": response["rows_found"],
        "column_names": response["column_names"],
        "error": response["error"],
    }


def _service_response(call: ServiceCall, response: dict[str, Any]) -> dict[str, Any]:
    """Return the response in the shape the called service reports."""
    if call.service == SERVICE_QUERY:
        return _query_response(response)
    return response


@callback
def _raises_on_error(call: ServiceCall) -> bool:
    """Return whether a failed statement should stop the caller.

    The default differs per service, so each keeps what it always did: query
    raises, execute reports the failure in its response. Either can be told
    to do the other, which is what a call moving between the two needs.
    """
    default = call.service == SERVICE_QUERY
    return bool(call.data.get(ATTR_RAISE_ON_ERROR, default))


@callback
def _async_check_call(instance: MySQLInstance, service: str, query: str) -> None:
    """Refuse a call that does not belong on this service or this connection.

    Raises rather than reporting through the response: this is a refusal to
    run anything, not the outcome of a statement, and a caller that does not
    read `succeeded` would otherwise take it for a success.
    """
    if service == SERVICE_EXECUTE and instance.read_only:
        raise HomeAssistantError(
            f"The connection '{instance.title}' is marked read-only, so "
            f"{DOMAIN}.{SERVICE_EXECUTE} is refused on it whatever the "
            "statement says. Use another connection, or turn the read-only "
            "option off under Configure."
        )

    statements = split_statements(query)

    if not statements:
        raise HomeAssistantError("No SQL statement was given.")

    if len(statements) > 1:
        raise HomeAssistantError(
            f"This call carries {len(statements)} statements separated by a "
            "semicolon. The driver would run every one of them while only the "
            "first reports a result, so a call carries exactly one statement."
        )

    read_only = is_read_only(statements[0])

    if service == SERVICE_QUERY and not read_only:
        raise HomeAssistantError(
            f"{DOMAIN}.{SERVICE_QUERY} only runs statements that read, such "
            f"as SELECT, WITH, SHOW, DESCRIBE and EXPLAIN. Call "
            f"{DOMAIN}.{SERVICE_EXECUTE} for a statement that changes "
            "anything; the parameters are the same."
        )

    if service == SERVICE_EXECUTE and read_only:
        raise HomeAssistantError(
            f"{DOMAIN}.{SERVICE_EXECUTE} only runs statements that change "
            f"something. Call {DOMAIN}.{SERVICE_QUERY} for a statement that "
            "only reads; it reports the same metadata."
        )


@callback
def _async_instance(hass: HomeAssistant, entry_id: str | None) -> MySQLInstance | None:
    """Return the connection a service call should run on.

    Without an entry ID the first loaded connection is used. That order comes
    from the config entry registry, so it is the same on every call and does
    not shift when one of the connections is reloaded.
    """
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if entry_id:
        return next(
            (entry.runtime_data for entry in entries if entry.entry_id == entry_id),
            None,
        )
    return next((entry.runtime_data for entry in entries), None)


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
                    "Query on %s truncated: the result set exceeds the limit "
                    "of %s rows.",
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


async def async_setup_entry(  # noqa: PLR0915
    hass: HomeAssistant, entry: MySQLQueryConfigEntry
) -> bool:
    """Set up mysql_query from a config entry.

    Long on purpose: the service handler is nested here so it closes over
    hass. It is registered once and serves every connection, looking up the
    one to use at call time.
    """
    config = entry.data

    try:
        pool = await async_create_pool(config)
    except Exception as e:
        _LOGGER.error(
            "Could not connect to mysql server for %s: %s",
            entry.title,
            str(e),
            exc_info=True,
        )
        return False

    # Asking for TLS is not the same as getting it: aiomysql skips the
    # handshake when the server does not advertise it and carries on in plain
    # text. Fail the setup instead, so a connection that is supposed to be
    # encrypted never quietly stops being encrypted.
    if tls_requested(config):
        try:
            conn = await pool.acquire()
            try:
                await async_verify_tls(conn)
            finally:
                pool.release(conn)
        except (TLSUnavailableError, aiomysql.Error, OSError) as err:
            _LOGGER.error("TLS is enabled for %s but %s", entry.title, err)
            pool.close()
            await pool.wait_closed()
            return False

    entry.runtime_data = MySQLInstance(
        pool=pool,
        config=config,
        title=entry.title,
        read_only=bool(
            config.get(CONF_READONLY_CONNECTION, DEFAULT_READONLY_CONNECTION)
        ),
    )

    # Changed settings must rebuild the pool, so reload the entry on update.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    async def async_handle_service(call: ServiceCall) -> ServiceResponse:
        """Handle service calls with instance selection and row limiting."""
        _query = call.data[ATTR_QUERY]
        _values = call.data.get(ATTR_VALUES)
        _db4query = call.data.get(ATTR_DB4QUERY)
        target_entry_id = call.data.get(ATTR_CONFIG_ENTRY)

        instance = _async_instance(hass, target_entry_id)
        if instance is None:
            raise HomeAssistantError("No database instance available.")

        # Before anything is borrowed from the pool: a refused call must not
        # cost a connection.
        _async_check_call(instance, call.service, _query)

        inst_config = instance.config
        mysql_db = inst_config.get(CONF_MYSQL_DB)
        target_db_name = _db4query if (_db4query and _db4query != "") else mysql_db

        row_limit = int(inst_config.get(CONF_ROW_LIMIT, DEFAULT_ROW_LIMIT))
        if row_limit < 1:
            row_limit = DEFAULT_ROW_LIMIT

        response = {
            "succeeded": False,
            "execution_time_ms": 0,
            "database": target_db_name,
            "user": inst_config.get(CONF_MYSQL_USERNAME),
            "statement": _query,
            "rows_found": None,
            "rows_returned": None,
            "rows_affected": None,
            "generated_id": None,
            "column_names": [],
            "error": {"message": None, "errno": None, "sqlstate": None},
            "result": [],
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

            response.update(
                {
                    "succeeded": True,
                    "result": db_output["res"],
                    "column_names": db_output["cols"],
                    "rows_found": db_output["rows_found"],
                    "rows_returned": db_output["rows_returned"],
                    "rows_affected": db_output["rows_affected"],
                    "generated_id": db_output["gen_id"],
                    "statement": db_output["statement"],
                    "execution_time_ms": execution_time_ms,
                }
            )

            # Kept inside the try, next to the response they read, rather than
            # moved into an else block that would sit below the handlers.
            if call.service == SERVICE_QUERY:
                return _query_response(response)
            return response  # noqa: TRY300

        except aiomysql.Error as e:
            errno, message = error_details(e)
            _LOGGER.error("MySQL Error [%s]: %s", errno, message)
            if _raises_on_error(call):
                raise HomeAssistantError(f"MySQL Error: {message}") from e
            response["error"] = {"message": message, "errno": errno, "sqlstate": None}
            return _service_response(call, response)
        except TimeoutError as e:
            message = "Timed out waiting for a free connection from the pool"
            _LOGGER.error("%s (%s)", message, instance.title)
            if _raises_on_error(call):
                raise HomeAssistantError(message) from e
            response["error"]["message"] = message
            return _service_response(call, response)
        except Exception as e:
            _LOGGER.error("General Error: %s", str(e))
            if _raises_on_error(call):
                raise HomeAssistantError(f"Error: {e!s}") from e
            response["error"]["message"] = str(e)
            return _service_response(call, response)

    # The services are global, not per entry: registering them once keeps a
    # second config entry from replacing the handler of the first.
    if not hass.services.has_service(DOMAIN, SERVICE_QUERY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_QUERY,
            async_handle_service,
            schema=QUERY_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_EXECUTE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_EXECUTE,
            async_handle_service,
            schema=EXECUTE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    return True


async def async_reload_entry(hass: HomeAssistant, entry: MySQLQueryConfigEntry) -> None:
    """Reload the entry after its settings changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MySQLQueryConfigEntry) -> bool:
    """Unload a config entry."""
    # An entry whose setup failed never got its runtime data.
    instance = getattr(entry, "runtime_data", None)
    if instance is None:
        return True

    # Taking the lock first lets a service call that is still running finish
    # before its connection is pulled out from under it.
    async with instance.lock:
        instance.pool.close()
        await instance.pool.wait_closed()

    # This entry left the loaded set before the unload was handed to us, so an
    # empty list here means it was the last connection.
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_QUERY)
        hass.services.async_remove(DOMAIN, SERVICE_EXECUTE)

    return True
