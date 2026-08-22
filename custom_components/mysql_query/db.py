"""Database plumbing shared by the config flow and the integration setup."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import re
import ssl
from typing import Any

import aiomysql

from .const import (
    CONF_AUTOCOMMIT,
    CONF_MYSQL_CHARSET,
    CONF_MYSQL_COLLATION,
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_USE_TLS,
    DEFAULT_MYSQL_AUTOCOMMIT,
    DEFAULT_MYSQL_PORT,
    DEFAULT_MYSQL_TIMEOUT,
    DEFAULT_USE_TLS,
    POOL_MAX_SIZE,
    POOL_MIN_SIZE,
    POOL_RECYCLE_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# Charset and collation end up in an init_command instead of a placeholder,
# because MySQL does not accept parameters there. Only accept the character
# class real charset/collation names use, so config values can never smuggle
# extra statements into that command.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


class TLSUnavailableError(Exception):
    """Raised when TLS was asked for but the connection ended up in plain text."""


def tls_requested(config: Mapping[str, Any]) -> bool:
    """Return whether this connection is configured to use TLS."""
    return bool(config.get(CONF_USE_TLS, DEFAULT_USE_TLS))


def _tls_context() -> ssl.SSLContext:
    """Return the TLS context used for an encrypted connection.

    The server certificate is deliberately not checked. A database on a home
    network nearly always carries a self signed certificate, and demanding a
    verifiable one would make the option unusable for most setups. This
    encrypts the traffic, which keeps it from being read off the network; it
    does not prove the server is the one it claims to be, so a man in the
    middle presenting its own certificate is not covered.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def async_verify_tls(conn: aiomysql.Connection) -> None:
    """Raise when a connection that asked for TLS is not actually encrypted.

    aiomysql only runs the handshake when the server advertises TLS, and
    carries on in plain text when it does not, without reporting anything. So
    asking for TLS is not the same as getting it, and the session status is
    the only thing that says which of the two happened.
    """
    async with conn.cursor() as cursor:
        await cursor.execute("SHOW STATUS LIKE 'Ssl_cipher'")
        row = await cursor.fetchone()

    if not (row and row[1]):
        raise TLSUnavailableError(
            "The server accepted the connection but did not encrypt it. "
            "Check that the database is configured for TLS, or turn the "
            "option off."
        )
    _LOGGER.debug("Connection encrypted with %s", row[1])


# A server-side driver error carries (errno, message); a client-side one, such
# as a refused connection, carries only the message.
_ERRNO_MESSAGE_ARGS = 2


def build_connection_kwargs(config: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a config entry into aiomysql connection arguments."""
    kwargs: dict[str, Any] = {
        "host": config.get(CONF_MYSQL_HOST),
        "port": int(config.get(CONF_MYSQL_PORT, DEFAULT_MYSQL_PORT)),
        "user": config.get(CONF_MYSQL_USERNAME),
        "password": config.get(CONF_MYSQL_PASSWORD) or "",
        "db": config.get(CONF_MYSQL_DB),
        "connect_timeout": int(config.get(CONF_MYSQL_TIMEOUT, DEFAULT_MYSQL_TIMEOUT)),
        "autocommit": bool(config.get(CONF_AUTOCOMMIT, DEFAULT_MYSQL_AUTOCOMMIT)),
    }

    charset = _valid_identifier(config.get(CONF_MYSQL_CHARSET), CONF_MYSQL_CHARSET)
    collation = _valid_identifier(
        config.get(CONF_MYSQL_COLLATION), CONF_MYSQL_COLLATION
    )

    if charset:
        kwargs["charset"] = charset

    # aiomysql has no collation argument, so apply it on every fresh connection
    # through the init_command the driver sends right after the handshake.
    if collation and charset:
        kwargs["init_command"] = f"SET NAMES {charset} COLLATE {collation}"
    elif collation:
        kwargs["init_command"] = f"SET collation_connection = '{collation}'"

    # Left out entirely when TLS is off, which is what keeps aiomysql from
    # offering it: it only runs the handshake when a context is present.
    if tls_requested(config):
        kwargs["ssl"] = _tls_context()

    return kwargs


def _valid_identifier(value: Any, field: str) -> str | None:
    """Return the value when it is a usable MySQL identifier, else None."""
    if not value:
        return None

    text = str(value).strip()
    if not _IDENTIFIER_RE.match(text):
        _LOGGER.warning("Ignoring invalid %s value %r", field, text)
        return None

    return text


async def async_create_pool(config: Mapping[str, Any]) -> aiomysql.Pool:
    """Create the connection pool for a config entry.

    Connections are recycled periodically so a pooled connection is never
    handed out after the server dropped it for being idle too long.
    """
    kwargs = build_connection_kwargs(config)
    _LOGGER.debug(
        "Creating connection pool for database %s at %s:%s",
        kwargs["db"],
        kwargs["host"],
        kwargs["port"],
    )
    return await aiomysql.create_pool(
        minsize=POOL_MIN_SIZE,
        maxsize=POOL_MAX_SIZE,
        pool_recycle=POOL_RECYCLE_SECONDS,
        **kwargs,
    )


async def async_test_connection(config: Mapping[str, Any]) -> None:
    """Open and close a single connection to validate the settings.

    Raises TLSUnavailableError when TLS was asked for and the server did not
    provide it; see async_verify_tls.
    """
    conn = await aiomysql.connect(**build_connection_kwargs(config))
    try:
        if tls_requested(config):
            await async_verify_tls(conn)
    finally:
        await conn.ensure_closed()


def error_details(err: BaseException) -> tuple[int | None, str]:
    """Split a driver error into its MySQL error number and message.

    aiomysql raises the PyMySQL exceptions, which carry ``(errno, message)``
    in ``args`` for server-side errors and a single message for client-side
    ones such as a refused connection.
    """
    args = getattr(err, "args", ())
    if len(args) >= _ERRNO_MESSAGE_ARGS and isinstance(args[0], int):
        return args[0], str(args[1])
    if len(args) == 1:
        return None, str(args[0])
    return None, str(err)
