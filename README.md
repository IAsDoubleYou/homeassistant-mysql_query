# MySQL Query for Home Assistant

[![HACS Custom][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Community Forum][community_forum_shield]][community_forum]

A Home Assistant custom component that provides *Responding services* to execute MySQL database queries. The results are available as an iterable data structure.

## Key Features

- **UI Configuration**: Modern setup and management through the Home Assistant Integrations page (Config Flow).
- **Two Service Modes**: Choose between a simple result list (```query```) or an extended metadata response (```execute```).
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
3. Download all files from this repository and place them in that directory.
4. Restart Home Assistant.

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
    - **Charset**: (Optional) Specify the character set (e.g., ```utf8mb4```).
    - **Collation**: (Optional) Specify the collation (e.g., ```utf8mb4_unicode_ci```).
    - **Autocommit**: Checkbox to toggle autocommit (Default: True).

### Multi-Instance & Default Configuration
This integration supports **multiple database connections**. 
- Each connection you add via the UI will appear as a separate entry.
- **Default Instance**: If you do not specify a connection in your service call, the integration will automatically use the **first configured instance** (usually the one imported from YAML or the first one added via the UI).
- **Selection**: Use the ```config_entry``` (Connection) field in the service call to target a specific database server.

### Via YAML (Legacy Import)
If you still use ```configuration.yaml```, your settings will be imported automatically. 

**IMPORTANT**: Once imported, please remove the ```mysql_query:``` block from your YAML file to prevent conflicts.

```yaml
mysql_query:
  mysql_host: 192.168.1.50
  mysql_username: ha_user
  mysql_password: your_password
  mysql_db: homeassistant
  mysql_port: 3306
  mysql_timeout: 10
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
result: []                 # List: The result set (list of dictionaries)
rows_affected: 0           # Integer: Number of rows changed
generated_id: null         # Integer: Last inserted ID (if applicable)
column_names: []           # List: List of column names
error:
  message: null            # String: Human-readable error message
  errno: null              # Integer: MySQL error number
  sqlstate: null           # String: SQL state code
```

---

## Automation Examples

### Example 1: Selecting a specific connection (Multi-Instance)
In this example, we specify which connection to use by selecting the Connection (config_entry) in the UI or YAML.

```yaml
alias: Query Specific Database
action:
  - service: mysql_query.execute
    data:
      query: "SELECT status FROM system_logs"
      config_entry: "7da8f6..." # The ID of your connection
    response_variable: db_status
```

### Example 2: Using ```mysql_query.execute``` with Error Handling
```yaml
alias: Secure Database Insert
action:
  - service: mysql_query.execute
    data:
      query: "INSERT INTO logs (message) VALUES ('HA Triggered')"
      db4query: "alternative_db"
    response_variable: db_result
  - if:
      - condition: template
        value_template: "{{ not db_result.succeeded }}"
    then:
      - service: notify.admin
        data:
          title: "Database Error"
          message: "Failed to log in {{ db_result.database }}! Error: {{ db_result.error.message }}"
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
[community_forum_shield]: https://img.shields.io/static/v1.svg?label=%20&message=Forum&style=for-the-badge&color=41bdf5&logo=HomeAssistant&logoColor=white
[community_forum]: https://community.home-assistant.io/t/mysql-query/734346