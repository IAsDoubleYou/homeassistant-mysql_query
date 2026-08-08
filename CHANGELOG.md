# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.9.0] - 2026-08-08

### Added
- `translations/en.json` and `translations/nl.json`, so Home Assistant actually loads the config-flow titles, field labels, error messages, and service descriptions. Previously only `strings.json` existed, which HA does not read for custom integrations.
- Conversion of MySQL-native column types into JSON-serialisable values before they are returned from the services: `DECIMAL` to `float`, `DATE`/`DATETIME`/`TIME`-of-day to ISO 8601, `TIME` (returned as `timedelta`) to `[-]HH:MM:SS[.ffffff]`, `SET` to a sorted list, and non-finite numbers to `null`. Nested `JSON` column values are converted recursively; unknown objects fall back to their string form.
- Tests for the new value conversion, both as unit tests per type and end to end through the `execute` service response.

### Changed
- The `debugpy` remote-debugger listener has been removed from the production code. Attach a debugger from the Home Assistant side (or the `debugpy` integration) instead of having the component open a port.

### Fixed
- Unloading a config entry no longer calls the blocking `is_connected()` check on the event loop; the connectivity check and the close now run together in the executor.

## [1.8.0] - 2026-08-07

### Added
- Type hints throughout `__init__.py` and `config_flow.py`, including a new `QueryResult` `TypedDict` for the service-call executor payload.
- Optional `debugpy` remote-debugger listener, disabled by default and only started when the `DEBUG` or `HA_DEBUG` environment variable is set to `true`. Falls back gracefully with a log warning if `debugpy` isn't installed, and supports `DEBUG_WAIT_FOR_CLIENT` to block startup until a debugger attaches.
- `tests/` suite (13 tests) covering the config flow, options flow, and both services (`query`/`execute`), with the MySQL driver fully mocked so no live database is required.

### Changed
- Replaced the deprecated `homeassistant.data_entry_flow.FlowResult` with `homeassistant.config_entries.ConfigFlowResult` in the config and options flow.

### Fixed
- An unhandled `UnboundLocalError` on `_cursor` when a query failed before the cursor could be created (e.g. a dropped database connection), which masked the underlying error.

[1.9.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v1.9.0
[1.8.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v1.8.0
