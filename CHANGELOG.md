# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - 2026-08-10

### Fixed
- `hacs.json` now sets `zip_release`, so HACS actually uses the release zip asset. Without that key HACS ignores `filename` altogether (`if self.repository_manifest.zip_release and self.repository_manifest.filename:`) and falls back to fetching every file of the integration separately through the GitHub API, which is slower and burns through the anonymous API rate limit faster.

### Added
- A `hacs` workflow running the official `hacs/action` validation, alongside the existing hassfest validation. This checks the repository the same way HACS itself does, so a mistake in `hacs.json` fails CI instead of surfacing after a release. The `brands` check is ignored for now: it only matters for inclusion in the HACS default store, not for installing this repository as a custom repository.
- A `LICENSE` file (MIT). The repository had no license, which formally left everyone without permission to use or redistribute the integration.

## [2.0.0] - 2026-08-09

### Added
- An `aiomysql` connection pool per config entry. Connections stay open between service calls instead of being opened and closed per query, are recycled after an hour, and are checked with a ping before every statement so a connection the server dropped while idle is transparently rebuilt.
- An `asyncio.Lock` per config entry. Concurrent `mysql_query.query` and `mysql_query.execute` calls on the same connection are now handled one after another, so their statements can no longer interleave on the same MySQL socket. Calls on different config entries still run in parallel.
- A timeout on waiting for a free pooled connection, using the configured **Connect Timeout**. It surfaces as a raised error for `query` and as an `error` payload for `execute` instead of hanging the call.
- Reloading of a config entry when its settings change, so an edit through the Options Flow rebuilds the pool instead of leaving the old settings in place until a restart.
- `db.py`, holding the connection settings, pool creation and connection test shared by the integration and the config flow.
- Tests for the pool (creation settings, reuse, ping, teardown) and for the lock (serialised calls, independence between entries, unload waiting for a running call).

### Changed
- **Breaking:** the driver moved from `mysql-connector-python` to `aiomysql`, so queries talk to MySQL over asyncio instead of through a worker thread. Home Assistant installs the new requirement automatically.
- `db4query` no longer opens a short-lived second connection. The pooled connection is switched to the requested database for the statement and switched back afterwards; a connection that cannot be switched back is dropped from the pool instead of being reused.
- The services are registered once for the domain instead of being re-registered by every config entry, and they are removed again when the last entry is unloaded.
- The warning logged when a result set exceeds the row limit is now in English, like the rest of the log output.
- Unloading a config entry waits for a service call that is still running before it closes the pool.

### Removed
- **Breaking:** `error.sqlstate` in the `execute` response is always `null`. The new driver does not expose the SQLSTATE code; `error.errno` and `error.message` are unchanged.

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

[2.0.1]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v2.0.1
[2.0.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v2.0.0
[1.9.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v1.9.0
[1.8.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v1.8.0
