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
ATTR_RAISE_ON_ERROR: Final = "raise_on_error"

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
CONF_USE_TLS: Final = "mysql_use_tls"
CONF_READONLY_CONNECTION: Final = "mysql_readonly"

# Defaults
DEFAULT_MYSQL_PORT: Final = 3306
DEFAULT_MYSQL_TIMEOUT: Final = 10
DEFAULT_MYSQL_AUTOCOMMIT: Final = True
DEFAULT_ROW_LIMIT: Final = 1000

# Off for compatibility: an existing connection was never read-only, and
# turning it on for everyone would refuse writes people rely on. It is a
# choice per connection, meant for one that only feeds dashboards.
DEFAULT_READONLY_CONNECTION: Final = False

# TODO: flip this to True in a future release.
#
# Off for now so upgrading changes nothing: a database that has no certificate
# configured is the normal case on a home network, and turning TLS on for those
# installations would fail every connection on the first restart after the
# update. Flipping the default is a breaking change and needs its own release,
# with the switch called out in the release notes so people whose server has no
# TLS can turn it back off.
DEFAULT_USE_TLS: Final = False

# Connection pool sizing. Service calls on one config entry are serialised by
# an asyncio.Lock, so one warm connection carries the normal load; the extra
# headroom keeps the pool serving while a connection is being replaced.
POOL_MIN_SIZE: Final = 1
POOL_MAX_SIZE: Final = 5

# Drop and rebuild a pooled connection after this many seconds, so it is never
# handed out after the server closed it on its own wait_timeout.
POOL_RECYCLE_SECONDS: Final = 3600
