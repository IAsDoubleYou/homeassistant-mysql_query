# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-08-23

**Breaking:** reading and writing are now split across the two services. `query` runs only SELECT and WITH statements, `execute` runs only statements that change data. See the migration note below; it is a one-word change per call.

### Changed

- **`mysql_query.query` refuses anything that is not a SELECT or a WITH statement**, and the error names `mysql_query.execute` as where the call belongs. Until now both services ran anything and differed only in what they returned, so a service called `query` would happily run a DELETE. That is the accident this release is about. This is breaking for calls that have used `query` for writes since 2.1.0 (commit `eb11f99`, "Support for all SQL query types"), where the original SELECT-only guard was removed.
- **`mysql_query.execute` refuses a SELECT or WITH statement**, and the error names `mysql_query.query`. The split is symmetrical on purpose: each service does one thing, and reaching for the wrong one always tells you which one you wanted.
- **A call carrying more than one statement is refused, on both services.** aiomysql switches on `CLIENT.MULTI_STATEMENTS` unconditionally and offers no way to turn it off through its public API, so `SELECT 1; DELETE FROM states` used to run both statements while only the first reported a result, and the integration reported it as a successful SELECT. A trailing semicolon is still accepted, and so is a semicolon inside a quoted value.
- **`query` now returns the metadata `execute` returned for a SELECT**: `succeeded`, `rows_found`, `column_names`, `execution_time_ms` and `error` travel alongside `result`. Nothing is lost by moving a read from `execute` to `query`, and the shape does not change between a successful and a failed call.

### Added

- **A read-only option per connection.** When it is on, `mysql_query.execute` is refused on that connection whatever the statement contains. This catches the other half of the problem: the service split catches reaching for the wrong verb, this catches reaching for the wrong connection. It needs no statement analysis, so nothing can be phrased around it. Off by default, so an existing connection is unaffected.
- **`raise_on_error` on both services**, with the default that keeps each one behaving as it always did: `true` for `query`, which stops the caller on a database error, and `false` for `execute`, which reports the error in its response as `succeeded: false`. Either can be told to do the other, which is what a call moving between the two services needs.

### Migration

- Using `query` for writes: change the service name to `mysql_query.execute`. The fields `query`, `values`, `db4query` and `config_entry` are identical and the rows stay under `result`. Add `raise_on_error: true` if you relied on a failure stopping your automation.
- Using `execute` for reads: change the service name to `mysql_query.query`. The metadata you used `execute` for comes with it.
- Reading through `query` and writing through `execute` already: nothing to do.
- Sending several statements in one call: split them into separate calls.

### Note on what the guard is not

The check reads the first keyword of the statement after stripping comments; it guards against reaching for the wrong service, not against a determined write. A SELECT can still write through `INTO OUTFILE` or a stored function with side effects, and MySQL 8 accepts a CTE in front of an UPDATE or DELETE. Read-only rights on the database user remain the boundary that actually holds.

## [2.3.0] - 2026-08-22

This release adds an option to encrypt the connection to the database. Read the note about what it does and does not protect against before turning it on.

### Added

- An **Encrypt the connection (TLS)** option on every connection, in the setup form as well as under Configure. It encrypts the traffic to the database, which keeps queries, results and the login from being read off the network.

  The server certificate is deliberately **not** verified, neither its signature nor its hostname: a database on a home network nearly always carries a self signed certificate, and demanding a verifiable one would make the option unusable for most setups. So this defends against passive eavesdropping, not against an attacker who can actively intercept the connection and present a certificate of their own.

  **The option defaults to off**, so an existing connection keeps working exactly as it did. Turning it on against a server that has no TLS configured fails with a message saying so, in the config screens and at startup, instead of quietly connecting unencrypted. That silent fallback is the driver's own behaviour: aiomysql runs the handshake only when the server advertises TLS and otherwise carries on in plain text without reporting it, so the integration checks the session status afterwards and refuses the connection when it turns out not to be encrypted.

  **TODO for a future release: flip the default to on.** That is a breaking change for every installation whose database has no certificate, so it needs its own release and a note in the release notes telling people how to turn it back off. The reminder also sits next to `DEFAULT_USE_TLS` in `const.py`.

## [2.2.0] - 2026-08-22

This release is about the configuration screens telling you what went wrong, and about the connection a service call lands on when it does not name one. It also puts the test suite and the linter in CI, where nothing was running them before.

**Minimum Home Assistant version is now declared as 2025.3.0.** The integration already needed it; see below.

### Added

- The setup screen names the cause of a failed connection instead of reporting everything as "Failed to connect, please check your settings". Wrong credentials, a database that does not exist or is not accessible, and a server that cannot be reached are told apart by the MySQL error code. The causes that do not speak for themselves now carry the driver's own message onto the form, shortened to 255 characters, so a refused connection, a timeout and a rejected charset are no longer indistinguishable. The `invalid_auth` message shipped in every translation but was never used by any code path; it is now.
- **Configure verifies the connection before saving it.** Submitting settings that cannot reach the database used to store them anyway, after which the reload failed and the reason was visible only in the log. The form now reports the problem the same way the initial setup step does, and comes back with the values still filled in rather than reset to the stored settings.
- Service icons: `query` shows a database search icon and `execute` a database edit icon, instead of both falling back to the generic one.
- A `loggers` entry in the manifest, so "enable debug logging" on the integration also turns on the `aiomysql` logger. Without it the driver's own messages were missing from the log around a connection problem.
- Continuous integration for the test suite and the linter. A ruff configuration in `pyproject.toml`, a `Lint` workflow that checks the rules and the formatting, and a `Tests` workflow that installs `requirements_test.txt` on Python 3.14 and runs pytest. Neither was running on a push before.
- `requirements_test.txt`, so reproducing a test run no longer means guessing which packages it needs.

### Changed

- A `query` or `execute` call that does not name a `config_entry` now runs on the first connection in the config entry registry, an order that stays the same across reloads. It used to run on whichever connection was set up first, which meant that reloading that connection silently moved later calls to another one. This only matters with two or more connections configured and calls that leave `config_entry` empty; with a single connection nothing changes.
- `hacs.json` declares a minimum Home Assistant version of 2025.3.0. The integration already needed it: releasing the shared services when the last connection is unloaded reads `async_loaded_entries()` from inside `async_unload_entry`, which only leaves out the entry being unloaded since the config entry state that release introduced. Without the declaration HACS offered the update to installations where that cleanup would silently not run.
- Internal: the pool, its lock and the entry settings live on the config entry's `runtime_data` instead of in a dict under `hass.data`, typed through a `MySQLQueryConfigEntry` alias. The options flow reads the entry from the `config_entry` property Home Assistant provides rather than being handed it and keeping a copy. Constants are marked `Final`. None of this changes what the integration does.
- Internal: the remaining Dutch comments are in English, matching the rest of the repository.

### Fixed

- The HACS validation workflow ran on an empty workspace because it never checked out the repository, so it validated nothing at all. Both validation workflows now check out the repository, use `actions/checkout@v5`, and no longer carry a nightly schedule that GitHub disables after 60 days of inactivity.
- The README claimed Home Assistant 2023.7 or newer, dating from when the response-data services were the newest thing used. It now matches the declared minimum.
- The fallback error raised by a `query` call is chained to the error it came from, like the two handlers next to it already were.

### Security

- The `aiomysql` requirement moves from 0.2.0 to 0.3.2, which fixes [CVE-2025-62611](https://github.com/advisories/GHSA-r397-ff8c-wv2g) (high, CVSS 8.2). MySQL lets a server ask the client for a local file through `LOAD DATA LOCAL INFILE`, and the client is supposed to refuse when `local_infile` is off. Up to and including 0.2.0 aiomysql never made that check, so a rogue or compromised database server could ask for any file the Home Assistant process can read, including `secrets.yaml` and the tokens under `.storage/`. This integration never enables `local_infile` and never issues such a statement, but that is not what protects against it: the setting was ignored, and the request comes from the server without anything being asked of it. The fix is in the driver, which now refuses the request, so upgrading the requirement is the whole remedy. Home Assistant installs the new version on the first start after the upgrade.

## [2.1.1] - 2026-08-18

### Added
- Brand images shipped with the integration, in `custom_components/mysql_query/brand/`: `icon.png` (256x256), `icon@2x.png` (512x512), `logo.png` (256x64) and `logo@2x.png` (512x128). Home Assistant 2026.3.0 and later read these directly and give them priority over the brands CDN, so the integration now shows its own icon and logo in the UI. Older Home Assistant versions ignore the folder and are unaffected.
- `scripts/build_brands.py`, which generates those images from the raw artwork. It keys out the background with a flood fill from the image border, so dark elements inside the artwork are preserved, and typesets the wordmark.

### Changed
- Releases no longer ship a `homeassistant-mysql_query.zip` asset. `zip_release` and `filename` are gone from `hacs.json`, so HACS installs the integration from `custom_components/mysql_query/` through the GitHub API. Existing installations update normally; no action is required.

### Removed
- The per-release downloads badge in the README. Without a release asset its count would always read zero; the all-releases badge remains.

## [2.1.0] - 2026-08-12

### Added
- An optional `values` field on both `mysql_query.query` and `mysql_query.execute`, for parameterized queries. Write a `%s` placeholder in the statement for every value and pass the values as a list; they are handed to the driver separately from the statement, which quotes and escapes each one according to its type. A quote, a semicolon or a backslash in the data can no longer change what the statement does. One placeholder always stands for exactly one value: lists are not expanded, and identifiers (table and column names) still cannot be parameterized.
- Native template rendering of the values. Each item is rendered with `parse_result=True`, so a template that yields a number, a boolean or none is bound as a Python `int`, `float`, `bool` or `None` (MySQL `NULL`) instead of as text. Literal values without `{{ ... }}` are passed through untouched, so `"42"` stays the string `"42"` and a leading zero is never lost.
- Documentation for `values` in the README: a section covering the data-type behaviour, the one-placeholder-one-value rule, the handling of literal percent signs, and worked examples for both services.
- Tests covering the new field: native types per item, literal values left alone, a single value accepted without a list, the schema refusing non-scalars, failing templates on both services, and the statement staying untouched when `values` is absent or empty.

### Changed
- The service schemas accept `values` as an optional list of scalars (`str`, `int`, `float`, `bool`, `None`). A single value is wrapped in a list automatically. Nested lists and mappings are refused, because MySQL binds one value per placeholder.
- The README no longer states that the integration has no bound parameters, and the INSERT example now uses `values` instead of interpolating templates into the SQL string.

### Notes
- Fully backward compatible: without `values` the statement is sent exactly as before. Nothing in it is interpreted, so an existing query containing a literal percent sign (`LIKE '%text%'`) keeps working unchanged. When `values` *is* passed, a literal percent sign in the statement has to be doubled (`'%%text%%'`) or, better, passed as a value.

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

[2.1.1]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v2.1.1
[2.1.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v2.1.0
[2.0.1]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v2.0.1
[2.0.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v2.0.0
[1.9.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v1.9.0
[1.8.0]: https://github.com/IAsDoubleYou/homeassistant-mysql_query/releases/tag/v1.8.0
