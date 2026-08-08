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
- **Dynamic Overrides**: Query another database on the same server per individual call using ```db4query```.
- **JSON-safe results**: MySQL types such as ```DECIMAL```, ```DATE``` and ```TIME``` are converted automatically.
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

### Adding a connection (Config Flow)

1. Navigate to **Settings** > **Devices & Services**.
2. Click **Add Integration** (+ button) and search for **MySQL Query Service**.
3. Fill in the connection details described below and submit.

The connection is tested before the entry is created. If the credentials or the host are wrong, the form is redisplayed with an error instead of creating a broken entry.

You can add the integration as many times as you like to connect to **multiple servers or databases**. Each entry is identified by its host and database name, so the same host/database combination cannot be added twice.

### Editing a connection (Options Flow)

Open **Settings** > **Devices & Services** > **MySQL Query Service** and press **Configure** on the connection you want to change. The options form contains exactly the same fields as the setup form, so every setting — including credentials and the row limit — can be corrected afterwards without removing and re-adding the integration.

### Configuration parameters

All fields below appear both in the setup form and in the options form. The **Key** column lists the internal name, which is what you use in ```configuration.yaml``` when importing a legacy configuration.

| Field | Key | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Host** | ```mysql_host``` | Yes | – | IP address or hostname of the MySQL/MariaDB server, for example ```192.168.1.50``` or ```db.local```. |
| **Port** | ```mysql_port``` | Yes | ```3306``` | Network port the database server listens on. |
| **Username** | ```mysql_username``` | Yes | – | Database user used for every query on this connection. Grant it only the privileges you actually need. |
| **Password** | ```mysql_password``` | Yes | – | Password of that database user. Stored in the Home Assistant config entry and never written to the log. |
| **Database** | ```mysql_db``` | Yes | – | Name of the default database. Every query on this connection runs against it unless you override it with ```db4query```. |
| **Connect Timeout (seconds)** | ```mysql_timeout``` | No | ```10``` | How long to wait for the initial connection before giving up. Raise it for slow or remote servers. |
| **Charset** | ```mysql_charset``` | No | driver default (```utf8mb4```) | Optional character set for the connection, for example ```utf8mb4```. Leave empty to use the driver default. |
| **Collation** | ```mysql_collation``` | No | server default | Optional collation, for example ```utf8mb4_unicode_ci```. Must be compatible with the chosen charset. Leave empty to use the server default. |
| **Autocommit** | ```mysql_autocommit``` | No | ```true``` | When enabled, every statement is committed immediately. With autocommit disabled the integration still commits explicitly after a successful non-SELECT statement, so writes are not lost. |
| **Row Limit (Safety Cap)** | ```mysql_row_limit``` | No | ```1000``` | Maximum number of rows a single SELECT may return to Home Assistant. This is a memory safety net, not a SQL ```LIMIT```. Values below ```1``` fall back to the default. |

### Stability & Performance

To prevent Home Assistant from becoming unresponsive when querying large tables, this integration uses a **Row Limit**.
- If a query returns more rows than configured, the result set is truncated, and a warning is logged in the Home Assistant logs.
- Increasing this limit beyond 1000 is possible but should be done with caution, as large amounts of data can impact system memory.

#### Understanding Row Limits
There are two ways rows are limited: the SQL-level ```LIMIT``` (user-defined) and the Integration-level ```Row Limit``` (safety net). **The lower of the two wins** — the safety net is applied to whatever the database sends back, so it also caps a larger explicit ```LIMIT```.

| Scenario (Table has 10.000 rows) | Integration Row Limit | SQL Query | ```rows_found``` | ```rows_returned``` |
| :--- | :--- | :--- | :--- | :--- |
| **No limit in SQL** | 1000 | SELECT * FROM table | 10.000 | **1000** |
| **SQL limit < Row Limit** | 1000 | SELECT * FROM table LIMIT 500 | 500 | **500** |
| **SQL limit > Row Limit** | 1000 | SELECT * FROM table LIMIT 5000 | 5000 | **1000** |

```rows_found``` reports what the query matched on the server, so comparing it with ```rows_returned``` tells you whether the safety net truncated your result. Whenever it does, a warning is written to the Home Assistant log. To actually retrieve more than the cap, raise **Row Limit** on the connection.

### Via YAML (Legacy Import)
If you still use ```configuration.yaml```, your settings will be imported automatically.

**IMPORTANT**: Once imported, please remove the ```mysql_query:``` block from your YAML file.

```yaml
mysql_query:
  mysql_host: 192.168.1.50
  mysql_port: 3306
  mysql_username: ha_user
  mysql_password: your_password
  mysql_db: homeassistant
  mysql_row_limit: 1000
```

---

## Services

The integration registers two services. Both are **responding services**: they return data to the caller, so a ```response_variable``` is required to capture the output.

| Service | Use it for | Returns |
| :--- | :--- | :--- |
| ```mysql_query.query``` | Reading data (SELECT) with the least amount of ceremony. | Only the list of rows, under the key ```result```. |
| ```mysql_query.execute``` | Everything, and especially writes (INSERT/UPDATE/DELETE/CREATE/DROP). | The rows plus full metadata: row counts, generated id, timing and errors. |

Both services accept exactly the same three fields:

| Field | Required | Description |
| :--- | :--- | :--- |
| ```query``` | Yes | The SQL statement to execute. |
| ```db4query``` | No | Run this single statement against a different database **on the same server**, instead of the configured default database. |
| ```config_entry``` | No | The id of the connection to use when you have configured more than one. If omitted, the first configured connection is used. |

> **Note:** There is no per-call row limit field. The row limit is a property of the connection (```mysql_row_limit```) — see [Example 1c](#example-1c-controlling-how-many-rows-come-back).

### 1. Service: ```mysql_query.query``` (Legacy/Simple)

Ideal for quick data retrieval. It returns only the list of results under the key ```result```.

**Response Format:**
```yaml
result:
  - column1: "value1"
    column2: "value2"
```

If the statement fails, this service **raises an error** and the automation or script stops at that step. Use ```mysql_query.execute``` if you would rather inspect the failure yourself and continue.

#### Example 1a: A standard query on the default database

```yaml
actions:
  - action: mysql_query.query
    data:
      query: >-
        SELECT entity_id, state, last_updated
        FROM states
        WHERE entity_id = 'sensor.outside_temperature'
        ORDER BY last_updated DESC
        LIMIT 5
    response_variable: recent_states
```

#### Example 1b: Querying another database with ```db4query```

```db4query``` temporarily points the statement at a different database on the same server, using the same host, port and credentials as the configured connection. The integration opens a short-lived connection for that statement and closes it again afterwards, so your default connection stays untouched.

```yaml
actions:
  - action: mysql_query.query
    data:
      query: "SELECT id, name, active FROM customers WHERE active = 1"
      db4query: reporting
    response_variable: active_customers
```

The database user configured for this connection must have access to the database named in ```db4query```. To reach a database on a *different server*, add a second connection instead and select it with ```config_entry```.

#### Example 1c: Controlling how many rows come back

The connection-wide **Row Limit** is a safety net, not something you tune per call. To limit a single query, put a ```LIMIT``` in the SQL itself — that is what the database honours, and it is faster because the rows never leave the server:

```yaml
actions:
  - action: mysql_query.query
    data:
      query: "SELECT entity_id, state FROM states ORDER BY last_updated DESC LIMIT 25"
    response_variable: last_25_states
```

If you genuinely need more rows than the safety net allows, you have two options:

1. Raise **Row Limit** on the connection via **Configure** (Options Flow). This applies to every query on that connection.
2. Add a second connection to the same database with a higher **Row Limit**, and select it per call with ```config_entry```. This keeps your everyday queries protected while allowing one deliberate "bulk" connection.

When a result set is truncated by the safety net, a warning is written to the Home Assistant log and ```rows_returned``` (in ```execute```) is lower than ```rows_found```.

#### Example 1d: Using the response in an automation

The response variable is a normal template variable. For ```mysql_query.query``` the rows live under ```result```, so ```result[0]``` is the first row and each column is a key on it.

```yaml
alias: Notify on the latest application error
triggers:
  - trigger: time_pattern
    hours: "/1"
conditions: []
actions:
  - action: mysql_query.query
    data:
      query: >-
        SELECT message, created_at
        FROM app_errors
        ORDER BY created_at DESC
        LIMIT 1
    response_variable: latest_error

  - condition: template
    value_template: "{{ latest_error.result | count > 0 }}"

  - action: notify.persistent_notification
    data:
      title: Latest application error
      message: >-
        {{ latest_error.result[0].message }}
        (logged at {{ latest_error.result[0].created_at }})
mode: single
```

Iterating over all returned rows works the same way:

```yaml
actions:
  - action: mysql_query.query
    data:
      query: "SELECT room, temperature FROM room_readings"
    response_variable: readings

  - action: notify.persistent_notification
    data:
      title: Room temperatures
      message: >-
        {% for row in readings.result %}
        {{ row.room }}: {{ row.temperature }}°C
        {% endfor %}
```

A script can hand the data back to its own caller by ending with a ```stop``` action:

```yaml
script:
  get_energy_total:
    sequence:
      - action: mysql_query.query
        data:
          query: "SELECT SUM(kwh) AS total FROM energy_log WHERE day = CURDATE()"
        response_variable: energy
      - stop: "Done"
        response_variable: energy
```

### 2. Service: ```mysql_query.execute``` (Advanced/Recommended)

Returns a detailed response including metadata, timing, and execution details. This is the service to use for INSERT, UPDATE, DELETE, CREATE and DROP statements, because it tells you what the statement actually did.

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
  sqlstate: null           # String: MySQL SQLSTATE code
```

Unlike ```mysql_query.query```, this service does **not** raise on a SQL error. It returns ```succeeded: false``` with the details in ```error```, so your automation keeps running and can decide what to do.

#### Example 2a: Storing a sensor value in your own table

```yaml
alias: Log power consumption every 5 minutes
triggers:
  - trigger: time_pattern
    minutes: "/5"
conditions: []
actions:
  - action: mysql_query.execute
    data:
      query: >-
        INSERT INTO ha_measurements (entity_id, value, measured_at)
        VALUES (
          'sensor.power_consumption',
          {{ states('sensor.power_consumption') | float(0) }},
          '{{ now().strftime("%Y-%m-%d %H:%M:%S") }}'
        )
    response_variable: insert_result

  - condition: template
    value_template: "{{ not insert_result.succeeded }}"

  - action: persistent_notification.create
    data:
      title: Logging power consumption failed
      message: "{{ insert_result.error.message }} (errno {{ insert_result.error.errno }})"
mode: single
```

After this call ```insert_result.rows_affected``` is ```1``` and ```insert_result.generated_id``` holds the ```AUTO_INCREMENT``` id of the new row.

⚠️ **Templating and SQL injection**: statements are sent to the server as plain text — the integration does not support bound parameters. Only interpolate values you control, and be careful with free-form text (such as an attribute a user can edit), because a single quote in the value will break or alter your statement. Where possible, cast to a number (```| float(0)```, ```| int(0)```) as shown above.

#### Example 2b: Updating a row and checking how many rows changed

```yaml
actions:
  - action: mysql_query.execute
    data:
      query: >-
        UPDATE thermostats
        SET target_temperature = 21.5
        WHERE room = 'living_room'
    response_variable: update_result

  - action: notify.persistent_notification
    data:
      message: >-
        {% if update_result.succeeded %}
          Updated {{ update_result.rows_affected }} row(s)
          in {{ update_result.execution_time_ms }} ms.
        {% else %}
          Update failed: {{ update_result.error.message }}
        {% endif %}
```

```rows_affected``` reports what MySQL actually changed. Note that an ```UPDATE``` which sets a column to the value it already had reports ```0``` affected rows even though the statement succeeded — check ```succeeded``` to see whether the statement ran, and ```rows_affected``` to see whether it changed anything.

#### Example 2c: Updating another database with ```db4query```

```yaml
actions:
  - action: mysql_query.execute
    data:
      query: >-
        UPDATE devices
        SET last_seen = NOW()
        WHERE device_id = 'ha-hub-01'
      db4query: inventory
    response_variable: inventory_update
```

The statement runs against the ```inventory``` database on the same server, and the response's ```database``` field confirms which database was used. Writes made through ```db4query``` are committed before the temporary connection is closed.

#### Example 2d: Creating a table (DDL)

DDL statements return no rows, so ```rows_affected``` and ```rows_found``` stay ```null```; ```succeeded``` is what tells you it worked.

```yaml
actions:
  - action: mysql_query.execute
    data:
      query: >-
        CREATE TABLE IF NOT EXISTS ha_measurements (
          id INT AUTO_INCREMENT PRIMARY KEY,
          entity_id VARCHAR(255) NOT NULL,
          value DECIMAL(12,3),
          measured_at DATETIME NOT NULL,
          INDEX idx_entity_measured (entity_id, measured_at)
        )
    response_variable: ddl_result
```

#### Example 2e: Selecting a specific connection (Multi-Instance)

When you have configured more than one connection, pass its config entry id in ```config_entry```. In the UI service editor you can pick the connection from a dropdown; in YAML you need the id itself, which you can read from the URL when you open the integration entry.

```yaml
actions:
  - action: mysql_query.execute
    data:
      query: "SELECT status FROM system_logs ORDER BY created_at DESC LIMIT 1"
      config_entry: "7da8f6..." # The ID of your connection
    response_variable: db_status
```

Omit ```config_entry``` and the first configured connection is used.

### Data types in the result set

Home Assistant serialises service responses to JSON, which has no notion of the
native Python objects the MySQL driver returns. Values are therefore converted
before they reach your automation:

| MySQL column type | Returned as | Example |
| --- | --- | --- |
| `DECIMAL` / `NUMERIC` | Number | `19.99` |
| `DATE` / `YEAR` | ISO 8601 string | `"2026-08-08"` |
| `DATETIME` / `TIMESTAMP` | ISO 8601 string | `"2026-08-08T14:30:05"` |
| `TIME` | String `[-]HH:MM:SS` | `"01:30:00"` |
| `SET` | Sorted list of strings | `["a", "b"]` |
| `JSON` | Object/list, converted recursively | `{"amount": 10.25}` |
| `BLOB` / `BINARY` | `"BLOB"` | `"BLOB"` |
| Large objects | `"LARGE OBJECT"` | `"LARGE OBJECT"` |

`NULL` stays `null`, and values that cannot be represented in JSON (`NaN`,
`Infinity`) are returned as `null`.

### Error handling at a glance

| Situation | ```mysql_query.query``` | ```mysql_query.execute``` |
| :--- | :--- | :--- |
| Statement succeeds | Returns ```result``` | Returns full metadata, ```succeeded: true``` |
| SQL error (syntax, permissions, …) | Raises; the automation stops | Returns ```succeeded: false``` and fills ```error``` |
| Connection dropped | Reconnects automatically, then behaves as above | Reconnects automatically, then behaves as above |
| No connection configured | Raises | Raises |

---

## Related Projects

- [HA MySQL](https://github.com/IAsDoubleYou/ha_mysql) - MySQL sensor component.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a full list of changes per version.

[hacs_shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[latest_release]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest
[releases_shield]: https://img.shields.io/github/release/IAsDoubleYou/homeassistant-mysql_query.svg?style=for-the-badge
[releases]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/
[downloads_total_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/total?style=for-the-badge
[downloads_latest_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/latest/total?style=for-the-badge
[community_forum_shield]: https://img.shields.io/static/v1.svg?label=%20&message=Forum&style=for-the-badge&color=41bdf5&logo=HomeAssistant&logoColor=white
[community_forum]: https://community.home-assistant.io/t/mysql-query/734346
