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

# Defaults
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_TIMEOUT = 10
DEFAULT_MYSQL_AUTOCOMMIT = True