# MySQL Query Service for Home Assistant

[![HACS Custom][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Community Forum][community_forum_shield]][community_forum]

A Home Assistant custom component that talks to a MySQL or MariaDB database through two ```Responding services```: ```mysql_query.query``` reads with a SELECT and hands you the rows, and ```mysql_query.execute``` writes with an INSERT, UPDATE, DELETE or DDL statement and hands you what it changed. Both return an iterable data structure you can use straight from a template.

> ⚠️ **Upgrading from an earlier version?** v3.0.0 changes what ```query``` and ```execute``` each accept — see [Upgrading to 3.0.0](#upgrading-to-300) before you update.

## Key Features

- **UI Configuration**: Modern setup and management through the Home Assistant Integrations page (Config Flow).
- **Reading and writing are separate**: ```query``` runs only statements that read, ```execute``` only statements that change something. Reach for the wrong one and you get an error naming the right one, instead of a surprise.
- **Parameterized queries**: pass values separately with ```values``` and ```%s``` placeholders, so the database escapes them for you and templates keep their data type.
- **Stability Protection**: Built-in row limiting to prevent Home Assistant from hanging on large result sets.
- Support for all SQL statement types (SELECT, INSERT, UPDATE, DELETE, DDL), split across the two services.
- **Read-only connections**: mark a connection as read-only and ```execute``` is refused on it entirely, so a write aimed at the wrong connection cannot land.
- **One statement per call**: a call carrying several statements separated by a semicolon is refused, because the driver would run all of them while only the first reports a result.
- **Multiple database support**: Configure multiple connections via UI and select them in service calls.
- **Dynamic Overrides**: Query another database on the same server per individual call using ```db4query```.
- **JSON-safe results**: MySQL types such as ```DECIMAL```, ```DATE``` and ```TIME``` are converted automatically.
- **Connection pooling**: every connection keeps a small pool of warm, automatically recycled MySQL connections instead of reconnecting per call.
- **Safe under load**: simultaneous service calls on the same connection are queued, so their statements never interleave on the same MySQL socket.
- Full integration with Home Assistant automations and scripts.
- Support for Service Response Data (introduced in HA 2023.7).

⚠️ **WARNING**: Exercise caution with destructive statements like UPDATE, DELETE, or DROP. The developer takes no responsibility for any data loss.

## Requirements

- Home Assistant version 2025.3.0 or newer. HACS enforces this, so an older installation is not offered the update. The integration releases its shared resources when the last connection is unloaded, which relies on the config entry states introduced in that release.
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
| **Encrypt the connection (TLS)** | ```mysql_use_tls``` | No | ```false``` | Encrypts the traffic between Home Assistant and the database. See [Encrypting the connection](#encrypting-the-connection). |
| **Read-only connection** | ```mysql_readonly``` | No | ```false``` | Refuses ```mysql_query.execute``` on this connection whatever the statement says. See [Read-only connections](#read-only-connections). |

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

### Read-only connections

A connection can be marked **Read-only**, in the setup form and under **Configure**. When it is on, every call to ```mysql_query.execute``` on that connection is refused, no matter what the statement contains.

This is a different kind of protection from the split between the two services. The service split catches reaching for the wrong *verb*: a ```DELETE``` sent to ```query``` is refused because ```query``` does not write. The read-only flag catches reaching for the wrong *connection*: a perfectly well-formed ```DELETE``` sent to ```execute``` is refused because that connection is not supposed to be written to at all. It needs no statement analysis and has no way around it.

It exists for the connection you created to feed dashboards or reports. Mark it read-only and a write meant for your application database cannot land in it by mistake, however the statement is spelled.

**Off by default**, so an existing connection keeps working exactly as it did. Turning it on affects only ```execute```; ```query``` keeps working, which is the entire point.

### Encrypting the connection

By default the connection to the database is **not encrypted**. Turning on **Encrypt the connection (TLS)** makes the integration negotiate TLS when it connects.

**What it does and does not protect.** The traffic is encrypted, so someone watching the network between Home Assistant and the database cannot read your queries, your results, or the password used to log in. The server's certificate is **not verified**, though — neither its signature nor its hostname — because a database on a home network nearly always carries a self signed one, and requiring a verifiable certificate would make this option unusable for most people. So this defends against passive eavesdropping, but not against an attacker who can actively intercept the connection and present a certificate of their own.

**The server has to support it.** If the database has no TLS configured, the connection is refused with a clear message rather than quietly falling back to an unencrypted one. That fallback is what the driver does on its own, and it is exactly what this option exists to prevent. You can check what your server offers with:

```sql
SHOW GLOBAL VARIABLES LIKE 'have_ssl';
```

`YES` means TLS is available. `DISABLED` or `NO` means you need to configure a certificate on the database first, or leave this option off.

**Why the default is off.** Most installations talk to a server with no certificate configured, and defaulting to on would break every one of them on the first restart after an update; see the [changelog](CHANGELOG.md) for when that is expected to change.

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
| ```mysql_query.query``` | Reading only: ```SELECT```, ```WITH```, ```SHOW```, ```DESCRIBE```, ```EXPLAIN```, ```CHECKSUM TABLE```, ```HELP```, and the MySQL 8 ```TABLE```/```VALUES``` shorthands. Refuses anything that changes data or schema. | The rows under ```result```, plus ```succeeded```, ```rows_found```, ```column_names```, ```execution_time_ms``` and ```error```. Raises on a database error unless ```raise_on_error: false```. |
| ```mysql_query.execute``` | Everything that changes something: ```INSERT```, ```UPDATE```, ```DELETE```, DDL, and maintenance statements such as ```ANALYZE TABLE``` or ```OPTIMIZE```. Refuses a read-only statement. | Full metadata: row counts, generated id, timing and errors. Reports a database error in the response instead of raising, unless ```raise_on_error: true```. |

<details>
<summary><strong>Which statements count as read-only</strong> — the exact list, and how <code>EXPLAIN</code> and <code>ANALYZE</code> are handled</summary>

The dividing line is read-only versus read/write, not the word ```SELECT```. ```query``` accepts ```SELECT```, ```WITH```, ```SHOW```, ```DESCRIBE```/```DESC```, ```CHECKSUM TABLE```, ```HELP```, and the MySQL 8 ```TABLE``` and ```VALUES``` shorthands. Everything else belongs to ```execute```, including maintenance statements that look informational but rewrite something: ```ANALYZE TABLE```, ```CHECK```, ```OPTIMIZE``` and ```REPAIR```.

```EXPLAIN``` and ```ANALYZE``` are prefixes in front of another statement, not statements of their own — and they are **not** treated the same way, because they do not do the same thing:

- **```EXPLAIN``` is always read-only**, whatever follows it. It only produces a plan and never runs what it describes, so ```EXPLAIN DELETE``` belongs to ```query``` just as ```EXPLAIN SELECT``` does.
- **```ANALYZE``` takes over the classification of the statement behind it**, because it really runs that statement. ```ANALYZE SELECT``` belongs to ```query```, ```ANALYZE DELETE``` to ```execute```. ```EXPLAIN ANALYZE``` follows this rule too.
- **```ANALYZE TABLE``` is the exception**: not a prefix in front of anything, but the maintenance command that rewrites index statistics, so always a write.

Options such as ```FORMAT=JSON``` in between are skipped.

| Statement | Goes to | Why |
| :--- | :--- | :--- |
| ```EXPLAIN SELECT ...``` | ```query``` | Produces a plan; the wrapped statement is not run. |
| ```EXPLAIN DELETE ...``` | ```query``` | Same: ```EXPLAIN``` never carries out what it describes. |
| ```ANALYZE SELECT ...``` | ```query``` | Runs the wrapped statement, and that statement only reads. |
| ```ANALYZE DELETE ...``` | ```execute``` | Runs the wrapped statement, and that one deletes. |
| ```EXPLAIN ANALYZE DELETE ...``` | ```execute``` | ```EXPLAIN ANALYZE``` runs the statement rather than planning it. |
| ```ANALYZE TABLE t``` | ```execute``` | Not a wrapped statement but the maintenance command; it rewrites index statistics. |

</details>

**One statement per call.** A call carrying several statements separated by a semicolon is refused by both services. The driver has multi-statement support switched on and cannot be told otherwise, so ```SELECT 1; DELETE FROM states``` would run *both* while reporting only the result of the first. A trailing semicolon is fine, and so is a semicolon inside a quoted value.

**What this protection is not.** The check reads the leading keywords of the statement; it is a guard against reaching for the wrong service, not a security boundary. A ```SELECT``` can still write through ```INTO OUTFILE``` or a stored function with side effects, and MySQL 8 accepts a CTE in front of an ```UPDATE```. If a connection must never write, give its database user ```SELECT``` rights only, and consider marking the connection [read-only](#read-only-connections).

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

### Service: ```mysql_query.query```

**Response Format:**
```yaml
result:
  - column1: "value1"
    column2: "value2"
```

If the statement fails, this service **raises an error** and the automation or script stops at that step. Use ```mysql_query.execute``` if you would rather inspect the failure yourself and continue.

#### Example 1a: A standard query, and using its response

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

The response variable is a normal template variable. The rows live under ```result```, so ```recent_states.result[0]``` is the first row and each column is a key on it. Iterating works the same way:

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

```db4query``` works the same way on ```mysql_query.execute```: the statement runs against the named database, the response's ```database``` field confirms which one was used, and a write is committed before the connection is switched back to the default database.

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

### Service: ```mysql_query.execute```

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

#### Example 2c: Creating a table (DDL)

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

#### Example 2d: Selecting a specific connection (Multi-Instance)

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

## Upgrading to 3.0.0

**This release splits reading and writing across the two services.** Before 3.0.0 both services ran anything, and they differed only in what they returned. That meant a service called ```query``` would happily run a ```DELETE```, which is exactly the sort of accident a name should prevent.

From 3.0.0 on, ```mysql_query.query``` runs only statements that read, and ```mysql_query.execute``` runs only statements that change something. Reach for the wrong one and the error tells you which one to use.

The dividing line is read-only versus read/write, not the word ```SELECT```. The [Services](#services) section lists exactly what each one accepts.

**If you use ```query``` for writes**, change the service name to ```mysql_query.execute```. Nothing else changes: the fields ```query```, ```values```, ```db4query``` and ```config_entry``` are identical, and the rows are still under ```result```. One thing to know: ```query``` stops your automation when a statement fails, while ```execute``` reports the failure in its response as ```succeeded: false```. If you were relying on the automation stopping, add ```raise_on_error: true``` to the call.

Both services accept ```raise_on_error```; only the default differs, so a call that does not mention it behaves the way that service always did. ```query``` defaults to ```true``` and ```execute``` to ```false```, and either can be told to do the other.

```yaml
# Before (2.x)
action: mysql_query.query
data:
  query: DELETE FROM readings WHERE logged_at < %s
  values: ["{{ (now() - timedelta(days=30)).isoformat() }}"]

# After (3.0.0)
action: mysql_query.execute
data:
  query: DELETE FROM readings WHERE logged_at < %s
  values: ["{{ (now() - timedelta(days=30)).isoformat() }}"]
  raise_on_error: true   # only if you relied on query aborting on failure
```

**If you use ```execute``` for reads**, change the service name to ```mysql_query.query```. You lose nothing: ```query``` now returns ```succeeded```, ```rows_found```, ```column_names``` and ```execution_time_ms``` alongside ```result```, which are the fields that made ```execute``` worth using for a ```SELECT```.

**If you only read through ```query``` and write through ```execute```**, you are already done; nothing changes for you.

Two further changes apply to both services: a call may now carry only one statement, and the guard has limits worth knowing. Both are described under [Services](#services).

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
