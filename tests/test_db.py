"""Tests for the shared database helpers."""

from __future__ import annotations

import ssl
from unittest.mock import AsyncMock, patch

from aiomysql import Error as MySQLError
import pytest

from custom_components.mysql_query.const import (
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
    DEFAULT_MYSQL_PORT,
    DEFAULT_MYSQL_TIMEOUT,
)
from custom_components.mysql_query.db import (
    TLSUnavailableError,
    async_test_connection,
    async_verify_tls,
    build_connection_kwargs,
    error_details,
    tls_requested,
)

BASE_CONFIG = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
}


def test_build_connection_kwargs_applies_defaults() -> None:
    """Optional settings fall back to the documented defaults."""
    kwargs = build_connection_kwargs(BASE_CONFIG)

    assert kwargs["port"] == DEFAULT_MYSQL_PORT
    assert kwargs["connect_timeout"] == DEFAULT_MYSQL_TIMEOUT
    assert kwargs["autocommit"] is True
    # Without an explicit charset the server default is left alone.
    assert "charset" not in kwargs
    assert "init_command" not in kwargs


def test_build_connection_kwargs_reads_configured_values() -> None:
    """Explicit settings win over the defaults."""
    kwargs = build_connection_kwargs(
        {
            **BASE_CONFIG,
            CONF_MYSQL_PORT: "3307",
            CONF_MYSQL_TIMEOUT: "20",
            CONF_AUTOCOMMIT: False,
        }
    )

    assert kwargs["port"] == 3307
    assert kwargs["connect_timeout"] == 20
    assert kwargs["autocommit"] is False


def test_collation_without_charset_sets_only_the_collation() -> None:
    """Aiomysql has no collation argument, so an init_command carries it."""
    kwargs = build_connection_kwargs(
        {**BASE_CONFIG, CONF_MYSQL_COLLATION: "utf8mb4_bin"}
    )

    assert kwargs["init_command"] == "SET collation_connection = 'utf8mb4_bin'"


def test_invalid_charset_and_collation_are_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Values that are no plain identifiers never reach the init_command."""
    kwargs = build_connection_kwargs(
        {
            **BASE_CONFIG,
            CONF_MYSQL_CHARSET: "utf8mb4; DROP TABLE users",
            CONF_MYSQL_COLLATION: "utf8mb4_bin'; SELECT 1",
        }
    )

    assert "charset" not in kwargs
    assert "init_command" not in kwargs
    assert "Ignoring invalid" in caplog.text


def test_error_details_splits_server_errors() -> None:
    """Server errors carry their error number and message separately."""
    assert error_details(MySQLError(1064, "Syntax error")) == (1064, "Syntax error")


def test_error_details_handles_client_side_errors() -> None:
    """Client-side errors have no error number to report."""
    assert error_details(MySQLError("Connection refused")) == (
        None,
        "Connection refused",
    )


class _StatusCursor:
    """Cursor stand-in that answers one SHOW STATUS query.

    The shared FakeCursor is built for result sets and reports fetchone() as a
    truncation probe, which is the opposite of what this check needs.
    """

    def __init__(self, row: tuple | None) -> None:
        """Return ``row`` for the single query this cursor answers."""
        self.row = row
        self.executed: list[str] = []

    async def execute(self, query: str, args: object = None) -> None:
        """Record the statement."""
        self.executed.append(query)

    async def fetchone(self) -> tuple | None:
        """Return the prepared status row."""
        return self.row

    async def __aenter__(self) -> _StatusCursor:
        """Enter the cursor context."""
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        """Leave the cursor context."""
        return False


class _TLSConnection:
    """Connection stand-in that reports one Ssl_cipher status row."""

    def __init__(self, row: tuple | None) -> None:
        """Hand out a cursor answering with ``row``."""
        self.cursor_obj = _StatusCursor(row)
        self.ensure_closed_called = False

    def cursor(self, *cursor_classes: type) -> _StatusCursor:
        """Return the prepared cursor."""
        return self.cursor_obj

    async def ensure_closed(self) -> None:
        """Record that the connection was closed."""
        self.ensure_closed_called = True


def test_tls_is_off_by_default() -> None:
    """Without the option no context is built, so the driver never offers TLS.

    aiomysql runs the handshake only when a context is present, so leaving the
    key out is what keeps an existing installation on exactly the connection
    it had before the option existed.
    """
    assert "ssl" not in build_connection_kwargs(BASE_CONFIG)
    assert tls_requested(BASE_CONFIG) is False


def test_tls_off_explicitly_is_the_same_as_unset() -> None:
    """Turning the option off leaves the connection arguments untouched."""
    assert "ssl" not in build_connection_kwargs({**BASE_CONFIG, CONF_USE_TLS: False})


def test_tls_builds_an_unverified_context() -> None:
    """Turning the option on hands the driver a context that does not verify.

    A database on a home network nearly always has a self signed certificate,
    so verification would make the option unusable. Asserted here because
    tightening or loosening this should never happen unnoticed.
    """
    context = build_connection_kwargs({**BASE_CONFIG, CONF_USE_TLS: True})["ssl"]

    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode is ssl.CERT_NONE


async def test_verify_tls_accepts_an_encrypted_session() -> None:
    """A session reporting a cipher passes the check."""
    conn = _TLSConnection(("Ssl_cipher", "TLS_AES_256_GCM_SHA384"))

    await async_verify_tls(conn)

    assert conn.cursor_obj.executed == ["SHOW STATUS LIKE 'Ssl_cipher'"]


@pytest.mark.parametrize("row", [("Ssl_cipher", ""), None])
async def test_verify_tls_rejects_a_plain_text_session(row: tuple | None) -> None:
    """An empty cipher means the server never encrypted the connection.

    This is the case aiomysql does not report: it skips the handshake when the
    server does not advertise TLS and carries on in plain text.
    """
    with pytest.raises(TLSUnavailableError):
        await async_verify_tls(_TLSConnection(row))


async def test_test_connection_checks_tls_when_asked() -> None:
    """The config flow path verifies the session it just opened."""
    conn = _TLSConnection(("Ssl_cipher", ""))

    with (
        patch("aiomysql.connect", AsyncMock(return_value=conn)),
        pytest.raises(TLSUnavailableError),
    ):
        await async_test_connection({**BASE_CONFIG, CONF_USE_TLS: True})

    assert conn.ensure_closed_called, "connection left open on the error path"


async def test_test_connection_skips_the_check_when_tls_is_off() -> None:
    """Without TLS the extra round trip is not made at all."""
    conn = _TLSConnection(("Ssl_cipher", ""))

    with patch("aiomysql.connect", AsyncMock(return_value=conn)):
        await async_test_connection(BASE_CONFIG)

    assert conn.cursor_obj.executed == []
    assert conn.ensure_closed_called
