"""Tests for converting MySQL column values into JSON-serialisable data."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps

from custom_components.mysql_query import format_timedelta, to_json_serializable
from custom_components.mysql_query.const import (
    ATTR_QUERY,
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_USERNAME,
    CONF_ROW_LIMIT,
    DOMAIN,
    SERVICE_QUERY,
)
from tests.conftest import FakeConnection, FakeCursor, FakePool, patch_create_pool

ENTRY_DATA = {
    CONF_MYSQL_HOST: "localhost",
    CONF_MYSQL_PORT: 3306,
    CONF_MYSQL_USERNAME: "test_user",
    CONF_MYSQL_PASSWORD: "test_pass",
    CONF_MYSQL_DB: "test_db",
    CONF_ROW_LIMIT: 10,
}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Passed through untouched.
        (None, None),
        (True, True),
        (42, 42),
        (1.5, 1.5),
        ("plain", "plain"),
        # DECIMAL columns.
        (Decimal("19.99"), 19.99),
        (Decimal("-0.5"), -0.5),
        (Decimal("7"), 7.0),
        (Decimal("NaN"), None),
        (Decimal("Infinity"), None),
        # DATE / DATETIME / TIMESTAMP / YEAR columns.
        (date(2026, 8, 8), "2026-08-08"),
        (datetime(2026, 8, 8, 14, 30, 5), "2026-08-08T14:30:05"),
        (datetime(2026, 8, 8, 14, 30, 5, 250000), "2026-08-08T14:30:05.250000"),
        (time(23, 59, 59), "23:59:59"),
        # TIME columns arrive as timedelta.
        (timedelta(hours=1, minutes=30), "01:30:00"),
        (timedelta(days=1, hours=2), "26:00:00"),
        (timedelta(hours=-2, minutes=-15), "-02:15:00"),
        (timedelta(seconds=5, microseconds=250000), "00:00:05.250000"),
        (timedelta(0), "00:00:00"),
        # Binary columns.
        (b"\x00\x01", "BLOB"),
        (bytearray(b"\x00\x01"), "BLOB"),
        (memoryview(b"\x00\x01"), "LARGE OBJECT"),
        # SET columns arrive as a Python set; JSON has no set type.
        ({"b", "a"}, ["a", "b"]),
        (frozenset({"x"}), ["x"]),
        # Non-finite floats are not valid JSON.
        (float("nan"), None),
        (float("inf"), None),
    ],
)
def test_to_json_serializable_converts_mysql_types(value, expected) -> None:
    """Every MySQL-native type maps onto a JSON-friendly equivalent."""
    converted = to_json_serializable(value)

    assert converted == expected
    # The whole point of the conversion: it must survive HA's JSON encoder.
    json_dumps(converted)


def test_to_json_serializable_converts_nested_structures() -> None:
    """JSON columns can nest values that each need converting."""
    value = {
        "amount": Decimal("10.25"),
        "history": [date(2026, 1, 1), timedelta(minutes=90)],
        "nested": {"blob": b"\xff"},
    }

    assert to_json_serializable(value) == {
        "amount": 10.25,
        "history": ["2026-01-01", "01:30:00"],
        "nested": {"blob": "BLOB"},
    }


def test_to_json_serializable_falls_back_to_string() -> None:
    """Unknown objects degrade to their string representation."""

    class Custom:
        def __str__(self) -> str:
            return "custom-value"

    assert to_json_serializable(Custom()) == "custom-value"


def test_format_timedelta_matches_mysql_time_format() -> None:
    """MySQL TIME spans of a day or more keep counting hours."""
    assert format_timedelta(timedelta(days=2, hours=3, minutes=4, seconds=5)) == (
        "51:04:05"
    )


async def test_execute_service_response_is_json_serializable(
    hass: HomeAssistant,
) -> None:
    """A SELECT with MySQL-native types yields a serialisable service response."""
    cursor = FakeCursor(
        description=[("price",), ("created",), ("duration",), ("payload",)],
        rows=[
            {
                "price": Decimal("19.99"),
                "created": date(2026, 8, 8),
                "duration": timedelta(hours=1, minutes=30),
                "payload": b"\x00\x01",
            }
        ],
        rowcount=1,
    )

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch_create_pool(FakePool(FakeConnection(cursor))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_QUERY,
        {ATTR_QUERY: "SELECT * FROM orders"},
        blocking=True,
        return_response=True,
    )

    assert response["result"] == [
        {
            "price": 19.99,
            "created": "2026-08-08",
            "duration": "01:30:00",
            "payload": "BLOB",
        }
    ]
    # Would raise if any raw Decimal/date/timedelta had leaked through.
    json_dumps(response)
