# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.8.0] - 2026-08-07

### Added
- Type hints throughout `__init__.py` and `config_flow.py`, including a new `QueryResult` `TypedDict` for the service-call executor payload.
- Optional `debugpy` remote-debugger listener, disabled by default and only started when the `DEBUG` or `HA_DEBUG` environment variable is set to `true`. Falls back gracefully with a log warning if `debugpy` isn't installed, and supports `DEBUG_WAIT_FOR_CLIENT` to block startup until a debugger attaches.
- `tests/` suite (13 tests) covering the config flow, options flow, and both services (`query`/`execute`), with the MySQL driver fully mocked so no live database is required.

### Changed
- Replaced the deprecated `homeassistant.data_entry_flow.FlowResult` with `homeassistant.config_entries.ConfigFlowResult` in the config and options flow.

### Fixed
- An unhandled `UnboundLocalError` on `_cursor` when a query failed before the cursor could be created (e.g. a dropped database connection), which masked the underlying error.

[1.8.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v1.8.0
