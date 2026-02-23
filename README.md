# MySQL Query Service for Home Assistant

[![HACS Custom][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub Downloads (latest Release)][downloads_latest_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Community Forum][community_forum_shield]][community_forum]

A Home Assistant custom component that provides ```Responding services``` to execute MySQL database queries. The results are available as an iterable data structure.

## Key Features

- **UI Configuration**: Modern setup and management through the Home Assistant Integrations page (Config Flow).
- **Two Service Modes**: Choose between a simple result list (```query```) or an extended metadata response (```execute```).
- **Stability Protection**: Built-in row limiting to prevent Home Assistant from hanging on large result sets.
- Support for all SQL query types (SELECT, INSERT, UPDATE, DELETE, etc.).
- **Multiple database support**: Configure multiple connections via UI and select them in service calls.
- **Dynamic Overrides**: Override the database name per individual query using ```db4query```.
- Full integration with Home Assistant automations and scripts.
- Support for Service Response Data (introduced in HA 2023.7).

⚠️ **WARNING**: Exercise caution with destructive statements like UPDATE, DELETE, or DROP. The developer takes no responsibility for any data loss.

## Requirements

- Home Assistant version 2023.7 or newer (due to Responding services functionality)

## Installation

### Option 1: Using HACS (recommended)

1. Open HACS in your Home Assistant installation.
2. Add this repository as a custom repository: ```https://github.com/IAsDoubleYou/homeassistant-mysql_query```
3. Search for "MySQL Query" in HACS and install.

### Option 2: Manual Installation

1. Navigate to your Home Assistant configuration directory.
2. Create a ```custom_components/mysql_query``` directory.
3. Download the ```mysql_query.zip``` from the [latest release](https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest).
4. Extract the contents into the ```custom_components/mysql_query``` directory.
5. Restart Home Assistant.

---

## Configuration

### Via UI (Recommended)
1. Navigate to **Settings** > **Devices & Services**.
2. Click **Add Integration** (+ button) and search for **MySQL Query Service**.
3. Enter your connection details:
    - **Host**: IP address or hostname.
    - **Port**: Default is 3306.
    - **Username/Password**: Database credentials.
    - **Database**: The default database for this connection.
    - **Connect Timeout**: Seconds to wait (Default: 10).
    - **Charset/Collation**: (Optional) Specify character settings.
    - **Autocommit**: Checkbox to toggle autocommit (Default: True).
    - **Row Limit**: Maximum number of rows to return (Default: 1000).

### Stability & Performance
To prevent Home Assistant from becoming unresponsive when querying large tables, this integration uses a **Row Limit**. 
- If a query returns more rows than configured, the result set is truncated, and a warning is logged in the Home Assistant logs.
- Increasing this limit beyond 1000 is possible but should be done with caution, as large amounts of data can impact system memory.

#### Understanding Row Limits
There are two ways rows are limited: the SQL-level ```LIMIT``` (user-defined) and the Integration-level ```Row Limit``` (safety net). **Note:** An explicit ```LIMIT``` in your SQL statement always overrides the integration safety limit.

| Scenario (Table has 10.000 rows) | Integration Row Limit | SQL Query | ```rows_found``` | ```rows_returned``` |
| :--- | :--- | :--- | :--- | :--- |
| **No limit in SQL** | 1000 | SELECT * FROM table | 10.000 | **1000** |
| **SQL limit < Row Limit** | 1000 | SELECT * FROM table LIMIT 500 | 500 | **500** |
| **SQL limit > Row Limit** | 1000 | SELECT * FROM table LIMIT 5000 | 5000 | **5000** |

### Via YAML (Legacy Import)
If you still use ```configuration.yaml```, your settings will be imported automatically. 

**IMPORTANT**: Once imported, please remove the ```mysql_query:``` block from your YAML file.

```yaml
mysql_query:
  mysql_host: 192.168.1.50
  mysql_username: ha_user
  mysql_password: your_password
  mysql_db: homeassistant
```

---

## Services

Both services require a ```response_variable``` to capture the output.

### 1. Service: ```mysql_query.query``` (Legacy/Simple)
Ideal for quick data retrieval. It returns only the list of results under the key ```result```.

**Response Format:**
```yaml
result:
  - column1: "value1"
    column2: "value2"
```

### 2. Service: ```mysql_query.execute``` (Advanced/Recommended)
Returns a detailed response including metadata, timing, and execution details.

**Response Format:**
```yaml
succeeded: true            # Boolean: True if execution was successful
execution_time_ms: 12.5    # Float: Time taken in milliseconds
database: "active_db"      # String: The database used for this query
user: "ha_user"            # String: The database user that executed the query
statement: "SELECT..."     # String: The actual executed SQL statement
result: []                 # List: The result set (truncated by Row Limit if exceeded)
rows_found: 257761         # Integer: Total rows found by SQL (SELECT only, else null)
rows_returned: 1000        # Integer: Rows actually returned in 'result' (SELECT only, else null)
rows_affected: 0           # Integer: Rows changed (UPDATE/INSERT/DELETE only, else null)
generated_id: null         # Integer: Last inserted ID (if applicable)
column_names: []           # List: List of column names
error:
  message: null            # String: Human-readable error message
  errno: null              # Integer: MySQL error number
```

---

## Automation Examples

### Example 1: Selecting a specific connection (Multi-Instance)
```yaml
alias: Query Specific Database
action:
  - service: mysql_query.execute
    data:
      query: "SELECT status FROM system_logs"
      config_entry: "7da8f6..." # The ID of your connection
    response_variable: db_status
```

## Related Projects

- [HA MySQL](https://github.com/IAsDoubleYou/ha_mysql) - MySQL sensor component.
- [coinbase_crypto_monitor](https://github.com/IAsDoubleYou/coinbase_crypto_monitor) - Coinbase monitor sensor.

[hacs_shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[latest_release]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest
[releases_shield]: https://img.shields.io/github/release/IAsDoubleYou/homeassistant-mysql_query.svg?style=for-the-badge
[releases]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/
[downloads_total_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/total?style=for-the-badge
[downloads_latest_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/latest/total?style=for-the-badge
[community_forum_shield]: https://img.shields.io/static/v1.svg?label=%20&message=Forum&style=for-the-badge&color=41bdf5&logo=HomeAssistant&logoColor=white
[community_forum]: https://community.home-assistant.io/t/mysql-query/734346