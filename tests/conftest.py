"""Fixtures for mysql_query tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

# On Linux/macOS (e.g. CI) this file isn't needed: the stdlib "fcntl" module
# that homeassistant.runner imports exists natively there. On Windows it
# doesn't, so run tests with tests/_win_shims on PYTHONPATH, e.g.:
#   PYTHONPATH=tests/_win_shims pytest
# pytest's setuptools-entrypoint plugin autoloading (which triggers that
# import) runs before any conftest.py, so this can't be done from here.

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Enable loading of custom_components/mysql_query for every test."""
    yield


@pytest.fixture
def mock_mysql_connection() -> MagicMock:
    """Return a mocked, already-connected MySQL connection."""
    cnx = MagicMock(name="MySQLConnection")
    cnx.is_connected.return_value = True
    return cnx
