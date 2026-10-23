# MySQL Query Service for Home Assistant

[![HACS Default][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub Downloads (latest Release)][downloads_latest_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Community Forum][community_forum_shield]][community_forum]
[![GitHub Stars](https://img.shields.io/github/stars/IAsDoubleYou/homeassistant-mysql_query?style=social)](https://github.com/IAsDoubleYou/homeassistant-mysql_query/stargazers)

> **Looking for continuous sensors instead of actions you trigger on demand?** See [HA MySQL](https://github.com/IAsDoubleYou/ha_mysql), a sibling integration built for that — full comparison at the [bottom of this README](#ha-mysql-or-mysql-query).

A Home Assistant custom component that talks to a MySQL or MariaDB database through two actions: ```mysql_query.query``` reads with a SELECT and hands you the rows, and ```mysql_query.execute``` writes with an INSERT, UPDATE, DELETE or DDL statement and hands you what it changed. Both can return their result as response data you can use straight from a template.

> **Upgrading from 3.x?** For most setups nothing needs to change. See [Breaking changes in v4.0](#breaking-changes-in-v40).

## Key Features

- **UI configuration**: add a connection, change it later from the menu of the connection, and sign in again from a prompt when the database refuses the credentials.
- **Reading and writing are separate**: ```query``` runs only statements that read, ```execute``` only statements that change something. The wrong one gives an error naming the right one.
- **Parameterized queries**: pass values separately with ```values``` and ```%s``` placeholders, so the database escapes them for you.
- **Guard rails**: a row limit, a query timeout, one statement per call, optional read-only connections, writes for administrators only, and optional TLS.
- **Multiple databases**: configure several connections and pick one per call, or use ```db4query``` for another database on the same server.
- **Robust**: pooled connections, calls on one connection queue instead of interleaving, and a connection that cannot be reached at startup is retried by itself.
- **JSON-safe results**: MySQL types such as ```DECIMAL```, ```DATE``` and ```TIME``` are converted automatically.

⚠️ **WARNING**: Exercise caution with destructive statements like UPDATE, DELETE, or DROP. The developer takes no responsibility for any data loss.

## Requirements

- Home Assistant 2026.9.0 or newer (it validates with probatio, which Home Assistant uses since that release). HACS will not install it on anything older.
- MySQL 5.6.5 or newer, or MariaDB 10.0 or newer: ```query``` relies on read-only transactions.
- The ```aiomysql``` driver, which Home Assistant installs automatically.

Note: This integration closely follows the latest Home Assistant releases. Keeping Home Assistant up-to-date is recommended to receive the newest updates and features of this component.

## Installation

### Using HACS (recommended)

Open HACS, search for "MySQL Query", open **MySQL Query Service**, select **Download** and restart Home Assistant.

### Manual installation

Download ```homeassistant-mysql_query.zip``` from the [latest release](https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest).
Extract it straight into ```custom_components/mysql_query``` (the archive has no top-level folder) and restart Home Assistant.

---

## Configuration

### Adding a connection

1. Go to **Settings** > **Devices & Services**, select **Add Integration** and search for **MySQL Query Service**.
2. Fill in the connection details below and submit. The connection is tested first; if it fails, the form shows why instead of creating a broken entry.

Add the integration as often as you like to connect to **multiple servers or databases**. A host/database combination can be added once.

### Settings

- **Host** and **Port** of the server (default port ```3306```)
- **Database**: the default database, unless a call overrides it with ```db4query```
- **Username** and **Password**: grant that user only the privileges you need. The password is masked and never shown again; leave the field empty to keep it.
- **Connect timeout**, and optionally **Charset** and **Collation**
- **Query timeout** (default 30 seconds): bounds a whole call, so a slow query fails instead of hanging your automation
- **Row limit** (default 1000): the most rows a SELECT hands to Home Assistant
- **Autocommit**: on by default
- **Read-only switch**: refuses ```execute``` on this connection, see [Read-only connections](#read-only-connections)
- **TLS**: see [Encrypting the connection](#encrypting-the-connection)

You can change all of them later from the menu (**⋮**) of the connection.

### When the database refuses or cannot be reached

- **Not reachable** (down, still starting): Home Assistant retries by itself, so the connection comes up once the database does.
- **Credentials refused**: Home Assistant asks you to sign in again and updates the existing connection.
- **Unknown database, a refused host, a locked account, TLS asked for but not offered**: the connection stops with the reason from the server. Waiting does not fix these; correct the cause and reload.

### Row limit, timeout and concurrency

- **Row limit.** A result with more rows than the limit is cut off and a warning is logged. The lower of the limit and your own SQL ```LIMIT``` wins. ```rows_found``` is what the query matched; compare it with ```rows_returned``` to see whether the limit cut your result. To get more rows, raise the limit on the connection, or add a second connection with a higher one. Raise it with care: large results cost memory.
- **Query timeout.** Bounds a whole call. When it elapses the call fails and its connection is dropped instead of reused.
- **Concurrency.** Each connection keeps a small pool (one to five connections), recycled hourly and checked before every statement, so a restarted database is picked up silently. Calls on the same connection run one at a time, so a slow query delays the ones behind it; calls on different connections run in parallel.

### Read-only connections

Switch on **Read-only** and every ```execute``` on that connection is refused, whatever the statement says. Use it for a connection that feeds dashboards or reports, so a write meant for another database cannot land there by mistake. ```query``` keeps working. For a connection that must never write, also give its database user ```SELECT``` rights only, see [Security best practice](#security-best-practice).

### Encrypting the connection

TLS is off by default. Switch on **Encrypt the connection (TLS)** and the traffic between Home Assistant and the database, including the password, can no longer be read on the network. The server's certificate is **not verified**, because home databases nearly always use a self-signed one, so this protects against eavesdropping but not against someone who actively intercepts the connection.

The server must support TLS: if it does not, the connection is refused with a message instead of quietly falling back to plain text. Check with ```SHOW GLOBAL VARIABLES LIKE 'have_ssl';``` (```YES``` means available). It is off by default because turning it on would break every setup without a certificate; see the [changelog](CHANGELOG.md) for when that is expected to change.

### YAML is not supported

Connections are config entries only. A ```mysql_query:``` section in ```configuration.yaml``` is reported by Home Assistant as unsupported and nothing is imported: add the connection in the UI and remove the section.

---

## Services

The integration registers two actions. ```query``` always returns a response, so it needs a ```response_variable```. ```execute``` can respond too, but does not have to; without a ```response_variable``` a failing write stops the automation, because there is no response to report it in.

| Service | Use it for | Returns |
| :--- | :--- | :--- |
| ```mysql_query.query``` | Reading only: ```SELECT```, ```WITH``` (followed by a ```SELECT```), ```SHOW```, ```DESCRIBE```, ```EXPLAIN```, ```CHECKSUM TABLE```, ```HELP```, and the MySQL 8 ```TABLE```/```VALUES``` shorthands. Refuses anything that changes data or schema. | The rows under ```result```, plus ```succeeded```, ```rows_found```, ```column_names```, ```execution_time_ms``` and ```error```. Raises on a database error unless ```raise_on_error: false```. |
| ```mysql_query.execute``` | Everything that changes something: ```INSERT```, ```UPDATE```, ```DELETE```, DDL, and maintenance statements such as ```ANALYZE TABLE``` or ```OPTIMIZE```. Refuses a read-only statement. | Row counts, generated id, timing and errors, when you ask for the response. Reports a database error in that response unless ```raise_on_error: true```. |

A call may carry **one statement**; several separated by a semicolon are refused (a trailing semicolon is fine).

<details>
<summary><strong>Which statements count as read-only</strong></summary>

The dividing line is read versus write, not the word ```SELECT```. A ```WITH``` reads only when the statement behind its common table expressions is a ```SELECT```, ```TABLE``` or ```VALUES```; ```INTO OUTFILE``` and ```INTO DUMPFILE``` count as writes. Maintenance statements that look informational but rewrite something (```ANALYZE TABLE```, ```CHECK```, ```OPTIMIZE```, ```REPAIR```) belong to ```execute```.

```EXPLAIN``` is always read-only, because it never runs what it describes. ```ANALYZE``` takes over the classification of the statement behind it, because it really runs it: ```ANALYZE SELECT``` belongs to ```query```, ```ANALYZE DELETE``` and ```EXPLAIN ANALYZE DELETE``` to ```execute```.

</details>

Both services accept the same fields:

| Field | Required | Description |
| :--- | :--- | :--- |
| ```query``` | Yes | The SQL statement. |
| ```values``` | No | Values for the ```%s``` placeholders, in order, see [Parameterized queries](#parameterized-queries-with-values). |
| ```db4query``` | No | Run this statement against another database **on the same server**. |
| ```config_entry``` | No | The connection to use when you have more than one. Defaults to the first loaded one. |
| ```raise_on_error``` | No | Stop the caller on a failing statement (```true```) or report it in the response (```false```). See [Error handling](#error-handling-at-a-glance). |

### Security best practice

```query``` runs every statement inside a read-only transaction that is rolled back, and its text is checked so a write goes to the right service. These are extra layers against mistakes, not a permission system: a statement written to slip a ```COMMIT``` past the check ends the transaction early. What a call can really do is decided by the rights of the database user, and ```query``` is open to every Home Assistant user. So:

- **Give each connection a database user with only the rights it needs.** For dashboards or non-administrators use a user with ```SELECT``` rights only, and add a second connection with its own user for ```execute```.
- **Do not grant the ```FILE``` privilege.** ```LOAD_FILE()``` and ```INTO OUTFILE``` need it.
- **Mark a connection that should never write as [read-only](#read-only-connections).**

### Who may call what

```query``` only reads and is open to every user. ```execute``` changes data with the credentials stored in the connection, so it is **for administrators**: a call made on behalf of a logged-in user who is not an administrator (a dashboard button, the developer tools, the API) is refused. A call that carries no user, such as an automation started by a trigger, is not affected.

To let a non-administrator cause a write, put the write in an automation and let the dashboard trigger it, for instance through an ```input_button``` helper. The statement is then fixed in the automation instead of typed by whoever is at the dashboard.

### Parameterized queries with ```values```

Put a ```%s``` placeholder in the query for each value and pass the values in order with ```values```. The driver escapes them, so a quote or semicolon in your data cannot change the statement.

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

Do not put quotes around a placeholder, use one placeholder per value (```IN (%s, %s)``` for two), and double a literal ```%``` in the statement (```LIKE '%%kitchen%%'```) once you pass ```values```.

⚠️ Prefer ```values``` over building the statement with templates, which invites SQL injection.

### Service: ```mysql_query.query```

**Response Format:**
```yaml
result:                    # List: the rows, one mapping per row
  - column1: "value1"
    column2: "value2"
succeeded: true            # Boolean: True if execution was successful
execution_time_ms: 12.5    # Float: Time taken in milliseconds
rows_found: 257761         # Integer: Total rows found by SQL, before the Row Limit
column_names: []           # List: List of column names
error:
  message: null            # String: Human-readable error message
  errno: null              # Integer: MySQL error number
  sqlstate: null           # String: reserved, always null since 2.0.0
```

These fields are always present, whether the call succeeded or not, so a template can read the same keys either way.

By default a failing statement **raises an error** here and the automation or script stops at that step. Set ```raise_on_error: false``` on the call if you would rather inspect ```succeeded``` and ```error``` yourself and carry on.

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

#### Example 1b: Another database, and how many rows

```db4query``` points one statement at another database on the same server, with the same credentials; the next call runs against the default database again. The user needs access to that database. For a different *server*, add a second connection and select it with ```config_entry```. It works on ```execute``` too.

The row limit is a safety net, not a per-call setting: put a ```LIMIT``` in the SQL to limit a single query.

```yaml
actions:
  - action: mysql_query.query
    data:
      query: "SELECT id, name FROM customers WHERE active = 1 LIMIT 25"
      db4query: reporting
    response_variable: active_customers
```

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

By default a failing statement does **not** raise here when the call has a ```response_variable```: the call returns ```succeeded: false``` with the details in ```error```, so your automation keeps running and can decide what to do. Set ```raise_on_error: true``` on the call to have it stop the automation instead, which is how ```mysql_query.query``` behaves by default. A call **without** a ```response_variable``` raises on a failure, since nobody would see the response that reports it; set ```raise_on_error: false``` if that step may fail without stopping anything.

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

#### Example 2c: DDL and several connections

DDL statements return no rows, so ```rows_affected``` and ```rows_found``` stay ```null```; ```succeeded``` tells you it worked. With more than one connection, pass its id in ```config_entry``` (pick it from the dropdown in the UI editor; in YAML read the id from the URL of the integration entry). Omit it and the first loaded connection is used.

```yaml
actions:
  - action: mysql_query.execute
    data:
      query: "CREATE TABLE IF NOT EXISTS ha_log (id INT AUTO_INCREMENT PRIMARY KEY, note VARCHAR(255))"
      config_entry: "7da8f6..." # The ID of your connection
    response_variable: ddl_result
```

### Data types in the result set

Values are converted so the response is JSON-safe: ```DECIMAL``` becomes a number, dates and times become ISO 8601 strings, ```SET``` a sorted list, ```JSON``` an object, ```BLOB``` the text ```"BLOB"```, and ```NULL``` stays ```null```.

### Error handling at a glance

```raise_on_error``` decides whether a failure stops your automation or comes back in the response. ```query``` defaults to ```true``` (it raises); ```execute``` defaults to ```false``` (it reports), except without a ```response_variable```, where it raises because there is nowhere to report. Set the flag explicitly and that is what you get.

With ```false```, a SQL error (syntax, permissions, …), a statement that runs past the query timeout and a pool with no free connection come back as ```succeeded: false``` with the details in ```error```. A dropped connection is reconnected automatically first.

Refusals to run always raise, on both services, as a validation error: no connection is loaded, the statement belongs to the other service or carries several statements, ```execute``` on a [read-only connection](#read-only-connections), or ```execute``` by a user who is not an [administrator](#who-may-call-what). The actions stay listed while no connection is loaded, so a call can tell you why it cannot run.

---

## Breaking changes in v4.0

Updating from 3.x needs no changes for most setups: connections are converted automatically and ```query``` calls keep working for every user. Check these four:

- **Setup is UI only.** A ```mysql_query:``` section in ```configuration.yaml``` is no longer imported; add the connection in the UI. Connections imported earlier keep working. The conversion is one way, so make a backup if you may want to go back to 3.x.
- **```execute``` is for administrators.** A call from a user who is not an administrator, such as a dashboard button, is refused. Let the button trigger an automation that makes the write, see [Who may call what](#who-may-call-what).
- **```query``` runs in a read-only transaction** (an extra layer, see [Security best practice](#security-best-practice)). A ```WITH ... UPDATE```, ```WITH ... DELETE``` or ```SELECT ... INTO OUTFILE``` sent to ```query``` is refused now; send it to ```execute```.
- **Home Assistant renders the templates in ```values```.** Automations, scripts and the developer tools are not affected; a dashboard button or API call with a template directly in ```values``` now passes it as text. Let it run a script instead.

Looking for the migration steps of older versions? They are in the [changelog](CHANGELOG.md).

---

## HA MySQL or MySQL Query?

[HA MySQL](https://github.com/IAsDoubleYou/ha_mysql) creates sensors that follow a query on an interval, `SELECT` only. MySQL Query (this repository) runs a query only when you call the action, can write as well, and returns the result as response data. They can be installed side by side.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a full list of changes per version, including the migration steps of older releases, and the [GitHub releases](https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases) for the release notes.

## Support

If you enjoy using this integration, please consider giving it a ⭐ on [GitHub](https://github.com/IAsDoubleYou/homeassistant-mysql_query)! It costs nothing, shows your appreciation, and helps other Home Assistant users find this integration more easily.

[hacs_shield]: https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=flat-square
[hacs]: https://github.com/hacs/integration
[latest_release]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest
[releases_shield]: https://img.shields.io/github/v/release/IAsDoubleYou/homeassistant-mysql_query?style=flat-square
[releases]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/
[downloads_total_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/total?style=flat-square
[downloads_latest_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/latest/total?style=flat-square
[community_forum_shield]: https://img.shields.io/static/v1.svg?label=%20&message=Forum&style=flat-square&color=41bdf5&logo=HomeAssistant&logoColor=white
[community_forum]: https://community.home-assistant.io/t/mysql-query/734346
