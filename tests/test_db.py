"""Tests for the shared database helpers."""

from __future__ import annotations

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
    DEFAULT_MYSQL_PORT,
    DEFAULT_MYSQL_TIMEOUT,
)
from custom_components.mysql_query.db import build_connection_kwargs, error_details

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
