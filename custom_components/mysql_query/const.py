"""Constants for the mysql_query integration."""

DOMAIN = "mysql_query"

# Service names
SERVICE_QUERY = "query"
SERVICE_EXECUTE = "execute"

# Field names / Attributes (Matches the imports in __init__.py)
ATTR_QUERY = "query"
ATTR_DB4QUERY = "db4query"
ATTR_CONFIG_ENTRY = "config_entry"

# Configuration fields
CONF_MYSQL_HOST = "mysql_host"
CONF_MYSQL_PORT = "mysql_port"
CONF_MYSQL_USERNAME = "mysql_username"
CONF_MYSQL_PASSWORD = "mysql_password"
CONF_MYSQL_DB = "mysql_db"
CONF_MYSQL_TIMEOUT = "mysql_timeout"
CONF_MYSQL_CHARSET = "mysql_charset"
CONF_MYSQL_COLLATION = "mysql_collation"
CONF_AUTOCOMMIT = "mysql_autocommit"
CONF_ROW_LIMIT = "mysql_row_limit"

# Defaults
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_TIMEOUT = 10
DEFAULT_MYSQL_AUTOCOMMIT = True
DEFAULT_ROW_LIMIT = 1000

# Connection pool sizing. Service calls on one config entry are serialised by
# an asyncio.Lock, so one warm connection carries the normal load; the extra
# headroom keeps the pool serving while a connection is being replaced.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 5

# Drop and rebuild a pooled connection after this many seconds, so it is never
# handed out after the server closed it on its own wait_timeout.
POOL_RECYCLE_SECONDS = 3600
