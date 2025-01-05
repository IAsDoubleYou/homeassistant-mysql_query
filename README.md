# MySQL Query for Home Assistant

[![HACS Custom][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Community Forum][community_forum_shield]][community_forum]

A Home Assistant custom component that provides a *ResponseData service* to execute MySQL database queries. The results are available as an iterable data structure.

## Key Features

- Support for all SQL query types (since V1.4.0)
- SELECT and WITH statements for data retrieval
- INSERT, UPDATE, and DELETE statements for data manipulation
- Multiple database support
- Full integration with Home Assistant automations

⚠️ **WARNING**: Exercise caution with destructive statements like UPDATE, DELETE, or DROP. The developer takes no responsibility for any data loss.

## Requirements

- Home Assistant version 2023.7 or newer (due to Responding services functionality)

## Installation

### Option 1: Using HACS (recommended)

1. Open HACS in your Home Assistant installation
2. Add this repository as a custom repository: `https://github.com/IAsDoubleYou/homeassistant-mysql_query`
3. Search for "MySQL Query" in HACS and install

### Option 2: Manual Installation

1. Navigate to your Home Assistant configuration directory (where `configuration.yaml` is located)
2. Create a `custom_components` directory if it doesn't exist
3. Create a new directory called `mysql_query` in `custom_components`
4. Download all files from the `custom_components/mysql_query/` directory of this repository
5. Place the downloaded files in the new directory
6. Restart Home Assistant
7. Add the configuration (see below)
8. Restart Home Assistant again

## Configuration

Add the following configuration to your `configuration.yaml`:

```yaml
mysql_query:
  mysql_host: <mysqldb host ip address>  # Required
  mysql_username: <mysqldb username>      # Required
  mysql_password: <mysqldb password>      # Required
  mysql_db: <mysqldb databasename>        # Required
  mysql_port: <mysql port>                # Optional, defaults to 3306
  mysql_autocommit: <true|false>          # Optional, defaults to true
  mysql_charset: <characterset>           # Optional
  mysql_collation: <collation>            # Optional
```

### Character Set and Collation

Optionally, you can configure a specific character set and collation:

```yaml
mysql_charset: utf8mb4
mysql_collation: utf8mb4_unicode_ci
```

### Autocommit

- `mysql_autocommit: true` (default): Each statement is committed immediately
- `mysql_autocommit: false`: Transactions must be explicitly committed or rolled back using COMMIT or ROLLBACK statements

## Usage

### Basic Query Service

```yaml
service: mysql_query.query
data:
  query: "SELECT * FROM contacts WHERE phonenumber='1234567890'"
```

### Query with Alternative Database

```yaml
service: mysql_query.query
data:
  query: "SELECT * FROM contacts"
  db4query: alternative_db
```

### Response Format

The service returns results in YAML format:

```yaml
result:
  - phonenumber: "0111111111"
    announcement: "Announcement for phonenumber 0111111111"
    language: "en"
  - phonenumber: "0222222222"
    announcement: "Announcement for phonenumber 0222222222"
    language: "en"
```

### Automation Example

```yaml
alias: mysql_query test
description: "Example of MySQL Query in automation"
trigger: []
condition: []
action:
  - variables:
      response: null
  - service: mysql_query.query
    data:
      query: "SELECT * FROM contacts"
    response_variable: response
  - service: notify.your_gmail_com
    data:
      message: |-
        Response from MySQL Query Service:
        {% for item in response.result %}
            {{ item.phonenumber }}
            {{ item.announcement }}
            {{ item.language }}
        {% endfor %}
      title: "Test of MySQL Query Service"
      target: youraccount@gmail.com
mode: single
```

## Related Projects

Also check out:
- [HA MySQL](https://github.com/IAsDoubleYou/ha_mysql) component for a MySQL *sensor* component.
- [coinbase_crypto_monitor](https://github.com/IAsDoubleYou/coinbase_crypto_monitor) component for a coinbase monitor sensor component.

[hacs_shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[latest_release]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/latest
[releases_shield]: https://img.shields.io/github/release/IAsDoubleYou/homeassistant-mysql_query.svg?style=for-the-badge
[releases]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/
[downloads_total_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/homeassistant-mysql_query/total?style=for-the-badge
[community_forum_shield]: https://img.shields.io/static/v1.svg?label=%20&message=Forum&style=for-the-badge&color=41bdf5&logo=HomeAssistant&logoColor=white
[community_forum]: https://community.home-assistant.io/t/mysql-query/734346
