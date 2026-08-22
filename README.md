# MySQL Query Service for Home Assistant

[![HACS Custom][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Community Forum][community_forum_shield]][community_forum]

A Home Assistant custom component that provides ```Responding services``` to execute MySQL database queries. The results are available as an iterable data structure.

## Key Features

- **UI Configuration**: Modern setup and management through the Home Assistant Integrations page (Config Flow).
- **Two Service Modes**: Choose between a simple result list (```query```) or an extended metadata response (```execute```).
- **Parameterized queries**: pass values separately with ```values``` and ```%s``` placeholders, so the database escapes them for you and templates keep their data type.
- **Stability Protection**: Built-in row limiting to prevent Home Assistant from hanging on large result sets.
- Support for all SQL query types (SELECT, INSERT, UPDATE, DELETE, etc.).
- **Multiple database support**: Configure multiple connections via UI and select them in service calls.
- **Dynamic Overrides**: Query another database on the same server per individual call using ```db4query```.
- **JSON-safe results**: MySQL types such as ```DECIMAL```, ```DATE``` and ```TIME``` are converted automatically.
- **Connection pooling**: every connection keeps a small pool of warm, automatically recycled MySQL connections instead of reconnecting per call.
- **Safe under load**: simultaneous service calls on the same connection are queued, so their statements never interleave on the same MySQL socket.
- Full integration with Home Assistant automations and scripts.
- Support for Service Response Data (introduced in HA 2023.7).

⚠️ **WARNING**: Exercise caution with destructive statements like UPDATE, DELETE, or DROP. The developer takes no responsibility for any data loss.

## Requirements

- Home Assistant version 2023.7 or newer (due to Responding services functionality)
- The ```aiomysql``` driver, which Home Assistant installs automatically from ```manifest.json```

## Installation

### Option 1: Using HACS (recommended)

1. Open HACS in your Home Assistant installation.
2. Add this repository as a custom repository: ```https://github.com/IAsDoubleYou/homeassistant-mysql_query```
3. Search for "MySQL Query" in HACS and install.

### Option 2: Manual Installation

1. Navigate to your Home Assistant configuration directory.
2. Create a ```custom_components/mysql_query``` directory.
3. Download ```homeassistant-mysql_query.zip``` from the [latest release](https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest).
4. Extract the contents of the zip directly into ```custom_components/mysql_query```. The archive has no top-level folder, so ```__init__.py```, ```manifest.json``` and the ```translations``` folder must end up straight in that directory:

   ```text
   custom_components/mysql_query/__init__.py
   custom_components/mysql_query/manifest.json
   custom_components/mysql_query/translations/en.json
   ```

   If you end up with ```custom_components/mysql_query/mysql_query/__init__.py```, move the files one level up.
5. Restart Home Assistant.

---

## Upgrading from 1.x to 2.0.0

Version 2.0.0 replaces the database driver and changes how connections are managed. Your existing connections keep working and no reconfiguration is needed, but two things are worth knowing before you upgrade.

**A new dependency is installed.** The integration moved from ```mysql-connector-python``` to ```aiomysql```, so queries now talk to MySQL over asyncio instead of through a worker thread. Home Assistant installs the new requirement on the first start after the upgrade; give that start a little extra time and make sure the instance can reach PyPI.

**```error.sqlstate``` is always ```null```.** The new driver does not expose the SQLSTATE code. If an automation reads ```error.sqlstate``` from a ```mysql_query.execute``` response, switch it to ```error.errno``` or ```error.message```, which are unchanged and carry the same information:

```yaml
# Before (1.x)
value_template: "{{ result.error.sqlstate == '42S02' }}"

# After (2.0.0) - errno 1146 is "table doesn't exist"
value_template: "{{ result.error.errno == 1146 }}"
```

Everything else — the service names, their fields, and the rest of the response format — is unchanged.

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
| **Connect Timeout (seconds)** | ```mysql_timeout``` | No | ```10``` | How long to wait for a connection before giving up, both when opening a new one and when waiting for a free connection from the pool. Raise it for slow or remote servers. |
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

#### Connections and concurrency

Every configured connection owns a small pool of MySQL connections that stay open between service calls, so a query no longer pays for a connection handshake. The pool keeps one connection warm and grows to at most five. Connections are recycled after an hour and pinged before every statement, which means the integration silently recovers when the server drops an idle connection or when the database was restarted.

Service calls on the same connection are handled one at a time. Home Assistant can fire several automations at once, and running their statements simultaneously over one connection would mix up the results, so the integration lets them queue instead. Calls on *different* configured connections do run in parallel — configure a second connection if you want two databases to be queried at the same time.

Because the calls queue, a slow query delays the ones behind it on the same connection. Waiting for a free pooled connection is bounded by **Connect Timeout**: when no connection becomes available within that many seconds, the call fails with an error instead of hanging your automation. These settings are not user-configurable beyond that timeout — the pool is sized for the queueing behaviour described above.

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

Both services accept exactly the same four fields:

| Field | Required | Description |
| :--- | :--- | :--- |
| ```query``` | Yes | The SQL statement to execute. |
| ```values``` | No | List of values for the ```%s``` placeholders in ```query```, in the order the placeholders appear — see [Parameterized queries](#parameterized-queries-with-values). |
| ```db4query``` | No | Run this single statement against a different database **on the same server**, instead of the configured default database. |
| ```config_entry``` | No | The id of the connection to use when you have configured more than one. If omitted, the first configured connection is used. |

> **Note:** There is no per-call row limit field. The row limit is a property of the connection (```mysql_row_limit```) — see [Example 1c](#example-1c-controlling-how-many-rows-come-back).

### Parameterized queries with ```values```

```values``` is optional. Leave it out and the statement is sent exactly as it always was, so every existing automation keeps working unchanged.

When you do use it, write a ```%s``` placeholder in the statement for each value and list the values in the same order. The values then travel to MySQL separately from the statement, and the driver quotes and escapes each one according to its type. A quote, a semicolon or a stray backslash in your data can no longer change what the statement does:

```yaml
actions:
  - action: mysql_query.execute
    data:
      query: >-
        INSERT INTO ha_measurements (entity_id, value, measured_at)
        VALUES (%s, %s, %s)
      values:
        - sensor.power_consumption
        - "{{ states('sensor.power_consumption') | float(0) }}"
        - "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
    response_variable: insert_result
```

Note that the placeholders are **not** quoted in the SQL: writing ```VALUES ('%s')``` is wrong, because the driver adds the quotes where they are needed.

```mysql_query.query``` takes the same field, which is the tidiest way to filter a SELECT on something that changes:

```yaml
actions:
  - action: mysql_query.query
    data:
      query: >-
        SELECT entity_id, state, last_updated
        FROM states
        WHERE entity_id = %s AND last_updated > %s
        ORDER BY last_updated DESC
      values:
        - sensor.outside_temperature
        - "{{ (now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S') }}"
    response_variable: recent_states
```

#### Templates keep their data type

Every value is rendered through the Home Assistant template engine with native typing, so a template that produces a number arrives as a number and not as text. That matters for numeric and boolean columns, and it is the only way to store a real ```NULL```:

| Value in ```values``` | Bound as | Python type |
| :--- | :--- | :--- |
| ```"{{ states('sensor.temperature') \| float }}"``` | ```21.5``` | ```float``` |
| ```"{{ now().year }}"``` | ```2026``` | ```int``` |
| ```"{{ is_state('light.kitchen', 'on') }}"``` | ```1``` | ```bool``` |
| ```"{{ none }}"``` | ```NULL``` | ```None``` |
| ```"sensor.kitchen"``` | ```'sensor.kitchen'``` | ```str``` |
| ```42``` | ```42``` | ```int``` |

A plain value without ```{{ ... }}``` is passed through untouched and is never reinterpreted: ```"42"``` stays the string ```"42"``` and a phone number like ```"0612345678"``` keeps its leading zero.

#### One placeholder, one value

A ```%s``` always stands for exactly one value, never for a list. So ```WHERE id IN (%s)``` with a list does not work — write one placeholder per value instead:

```yaml
      query: "SELECT name FROM devices WHERE id IN (%s, %s, %s)"
      values: [1, 2, 3]
```

Only values can be parameterized, not identifiers. Table names, column names and SQL keywords must stay in the statement itself; ```SELECT %s FROM %s``` is not valid SQL. To switch database, use ```db4query```.

The number of placeholders and the number of values must match. If they do not, MySQL rejects the statement and you get a normal query error back.

#### Percent signs in a parameterized statement

As soon as you pass ```values```, the ```%``` character becomes special in the statement. A literal percent sign then has to be doubled:

```yaml
      # Wrong: the % of the LIKE pattern is read as a placeholder
      query: "SELECT * FROM devices WHERE name LIKE '%kitchen%' AND active = %s"

      # Correct: double the literal percent signs
      query: "SELECT * FROM devices WHERE name LIKE '%%kitchen%%' AND active = %s"

      # Better: pass the whole pattern as a value
      query: "SELECT * FROM devices WHERE name LIKE %s AND active = %s"
      values: ["%kitchen%", 1]
```

This only applies when ```values``` is present. Without it, nothing in the statement is interpreted and ```LIKE '%kitchen%'``` works as it always did.

#### Errors in a value

A template that fails (a division by zero, a filter on a value that is not there) is treated like any other failure of the call: ```mysql_query.query``` raises and stops the automation, while ```mysql_query.execute``` returns ```succeeded: false``` with the details in ```error```. The statement is not sent to the database in that case.

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

```db4query``` temporarily points the statement at a different database on the same server, using the same host, port and credentials as the configured connection. The integration switches a pooled connection to that database for the duration of the statement and switches it back afterwards, so the next call again runs against your configured default database.

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
      message: |-
        Current temperatures:
        {%- for row in readings.result %}
        - {{ row.room }}: {{ row.temperature }}°C
        {%- endfor %}
```

#### Example 1e: Reusing a query through a script (end-to-end)

When several automations need the same query, put it in a script once and let the script hand the rows back to whoever called it. This takes two pieces: the script that fetches and returns the data, and the automation that calls it and works with the result.

Two things to keep in mind while reading the example:

- **```mysql_query.query``` always returns a list of rows under the key ```result```** — even when the query matches a single row, or none at all. So the rows are always at ```<your_response_variable>.result```, and each row is a mapping whose keys are the column names of your SELECT.
- **The ```stop``` action is a script's return statement.** A script has no ```return```; instead you end it with ```stop```, and the variable you name in ```response_variable``` is what the caller receives. The text after ```stop:``` is only a log message explaining why the script ended.

##### Step 1: Define the script

Add this to ```configuration.yaml``` (or to ```scripts.yaml``` if you keep your scripts in a separate file, in which case you omit the top-level ```script:``` key).

```yaml
script:
  get_daily_energy_report:
    alias: Get daily energy report
    sequence:
      # Fetch today's rows and capture them in a local variable.
      - action: mysql_query.query
        data:
          query: >-
            SELECT sensor_id, kwh
            FROM energy_log
            WHERE day = CURDATE()
            ORDER BY kwh DESC
        response_variable: query_output

      # Hand that variable back to the caller. This is the script's return value.
      - stop: "Energy report retrieved"
        response_variable: query_output
    mode: single
```

The script now returns the untouched service response, so the caller receives ```{"result": [ ... ]}```.

##### Step 2: Call the script and loop through the results

Call the script by its own entity id (```script.get_daily_energy_report```) and capture what it returns in ```response_variable```. Note that ```script.turn_on``` does **not** work here: it fires the script and returns immediately, without a response.

The rows are then a normal list you can walk with a Jinja2 for-loop:

```jinja2
{% for row in energy_data.result %}
  - {{ row.sensor_id }}: {{ row.kwh }} kWh
{% endfor %}
```

Put together into a complete automation:

```yaml
alias: Daily energy report
triggers:
  - trigger: time
    at: "23:55:00"
conditions: []
actions:
  # Run the script and store its return value in 'energy_data'.
  - action: script.get_daily_energy_report
    response_variable: energy_data

  # Skip the notification when the query returned no rows at all.
  - condition: template
    value_template: "{{ energy_data.result | count > 0 }}"

  # Loop over every row and build one message out of it.
  - action: notify.persistent_notification
    data:
      title: Daily energy report
      message: |-
        Energy usage for today:
        {%- for row in energy_data.result %}
        - {{ row.sensor_id }}: {{ row.kwh }} kWh
        {%- endfor %}

        Total: {{ energy_data.result | map(attribute='kwh') | sum | round(2) }} kWh
mode: single
```

Which produces a notification like:

```text
Energy usage for today:
- solar_inverter: 18.42 kWh
- heat_pump: 7.15 kWh
- washing_machine: 1.08 kWh

Total: 26.65 kWh
```

> **Tip:** the ```-``` in ```{%- for ... %}``` and ```{%- endfor %}``` strips the surrounding newlines, so each row lands on its own line instead of leaving a blank line between them. Use a literal block (```|-```) rather than a folded one (```>-```) for multi-line output, because a folded block joins every line into one.

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
  sqlstate: null           # String: reserved, always null since 2.0.0
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
        VALUES (%s, %s, %s)
      values:
        - sensor.power_consumption
        - "{{ states('sensor.power_consumption') | float(0) }}"
        - "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
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

⚠️ **Templating and SQL injection**: prefer ```values``` over building the statement with templates, as shown above. A value passed through ```values``` is escaped by the driver, so a single quote in free-form text (a device name, a note, an attribute a user can edit) cannot break or alter your statement. When you do interpolate a template straight into the ```query``` string, only do so with values you control, and cast to a number (```| float(0)```, ```| int(0)```) where possible.

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

The statement runs against the ```inventory``` database on the same server, and the response's ```database``` field confirms which database was used. Writes made through ```db4query``` are committed before the connection is switched back to the default database.

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
| Failing template in ```values``` | Raises; the statement is not sent | Returns ```succeeded: false```; the statement is not sent |
| Connection dropped | Reconnects automatically, then behaves as above | Reconnects automatically, then behaves as above |
| No free pooled connection within the connect timeout | Raises | Returns ```succeeded: false``` and fills ```error``` |
| No connection configured | Raises | Raises |

---

## Related Projects

- [HA MySQL](https://github.com/IAsDoubleYou/ha_mysql) - MySQL sensor component.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a full list of changes per version.

[hacs_shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square
[hacs]: https://github.com/hacs/integration
[latest_release]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest
[releases_shield]: https://img.shields.io/github/v/release/IAsDoubleYou/homeassistant-mysql_query?style=flat-square
[releases]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/
[downloads_total_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/total?style=flat-square
[community_forum_shield]: https://img.shields.io/static/v1.svg?label=%20&message=Forum&style=flat-square&color=41bdf5&logo=HomeAssistant&logoColor=white
[community_forum]: https://community.home-assistant.io/t/mysql-query/734346
