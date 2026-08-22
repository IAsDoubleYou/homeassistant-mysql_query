"""Constants for the mysql_query integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "mysql_query"

# Service names
SERVICE_QUERY: Final = "query"
SERVICE_EXECUTE: Final = "execute"

# Field names / Attributes (Matches the imports in __init__.py)
ATTR_QUERY: Final = "query"
ATTR_VALUES: Final = "values"
ATTR_DB4QUERY: Final = "db4query"
ATTR_CONFIG_ENTRY: Final = "config_entry"

# Configuration fields
CONF_MYSQL_HOST: Final = "mysql_host"
CONF_MYSQL_PORT: Final = "mysql_port"
CONF_MYSQL_USERNAME: Final = "mysql_username"
CONF_MYSQL_PASSWORD: Final = "mysql_password"
CONF_MYSQL_DB: Final = "mysql_db"
CONF_MYSQL_TIMEOUT: Final = "mysql_timeout"
CONF_MYSQL_CHARSET: Final = "mysql_charset"
CONF_MYSQL_COLLATION: Final = "mysql_collation"
CONF_AUTOCOMMIT: Final = "mysql_autocommit"
CONF_ROW_LIMIT: Final = "mysql_row_limit"

# Defaults
DEFAULT_MYSQL_PORT: Final = 3306
DEFAULT_MYSQL_TIMEOUT: Final = 10
DEFAULT_MYSQL_AUTOCOMMIT: Final = True
DEFAULT_ROW_LIMIT: Final = 1000

# Connection pool sizing. Service calls on one config entry are serialised by
# an asyncio.Lock, so one warm connection carries the normal load; the extra
# headroom keeps the pool serving while a connection is being replaced.
POOL_MIN_SIZE: Final = 1
POOL_MAX_SIZE: Final = 5

# Drop and rebuild a pooled connection after this many seconds, so it is never
# handed out after the server closed it on its own wait_timeout.
POOL_RECYCLE_SECONDS: Final = 3600
