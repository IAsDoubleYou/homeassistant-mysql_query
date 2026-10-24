# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.2.1] - 2026-10-24

HACS installs from the release zip again. Nothing changes for a connection, an automation or a script.

### Changed

- **`zip_release` and `filename` are back in `hacs.json`.** GitHub has shrunk the headers of its release-download redirect, so HACS can download the release zip again (see [hacs/integration#5643](https://github.com/hacs/integration/issues/5643)). This undoes the workaround of 4.2.0, and the downloads badge counts the installs through HACS again.

## [4.2.0] - 2026-10-24

Diagnostics for the connection, and HACS installs the integration file by file for now. Nothing changes for a connection, an automation or a script.

### Added

- **Download diagnostics** from the menu of the connection. The file holds the settings of the connection, the size of the connection pool and the state of the entry. The host, port, username, password and database name are masked, and so are the title and the unique ID of the connection. The integration keeps no statements and no rows, so none are included.

### Changed

- **HACS no longer installs from the release zip, for now.** GitHub currently answers release downloads with a redirect whose headers are too large for the HTTP client of Home Assistant, so HACS fails with `Got more than 8190 bytes when reading` for every integration that installs from a release zip (see [hacs/integration#5643](https://github.com/hacs/integration/issues/5643)). `zip_release` and `filename` are therefore removed from `hacs.json`, and HACS fetches the files of `custom_components/mysql_query/` one by one instead. The zip is still attached to every release for a manual install. Both keys can return once the problem is solved.

## [4.1.0] - 2026-10-24

The integration moves to the validation library Home Assistant itself switched to, and the code is now fully type checked. Nothing changes for a connection, an automation or a script.

### Changed

- **Home Assistant 2026.9.0 or newer is now required**, declared in `hacs.json` (previously 2026.3.0). Home Assistant replaced voluptuous with probatio in that release, and the forms and actions of this integration now use probatio directly. HACS keeps a Home Assistant older than 2026.9.0 on version 4.0.1.
- The whole integration passes `mypy --strict`, and ships a `py.typed` marker. This is checked in CI from now on.

## [4.0.1] - 2026-10-18

A clean-up release. Nothing changes for automations, scripts or dashboards; two messages are clearer.

### Changed

- **The setup forms and the connection itself read a failed connection the same way.** Both now use one shared classification. A refusal that waiting does not fix, such as a host the account may not connect from, a locked account, an expired password or an unknown collation, used to show "Failed to connect to the server. Check the host, the port and your firewall" on the form, while setup reported it as a refusal. The form now says the server refused the connection, with the reason from the server, just like setup.
- **A `config_entry` id of another integration is no longer shown by that integration's title.** A call that named the id of, say, a light, said that connection was not loaded and named the light. It names the id now.
- **A stored row limit below 1 is replaced with the default once, when the connection is loaded** (config entry minor version 2). The forms never store one, but an import from YAML could; until now it was replaced on every call. The result is the same: such a connection kept returning up to 1000 rows. Going back to 4.0.0 still works.
- Internal: the response of a successful call is built by the same helper as that of a failed one, an unload no longer checks for runtime data that a loaded entry always has, and a redundant empty-string check is gone.

## [4.0.0] - 2026-10-18

**Major release.** This release brings the integration in line with the latest Home Assistant and HACS quality and security requirements, in preparation for its inclusion in the default HACS repository. For most setups updating needs no changes: connections are converted automatically, `query` calls keep working for every user, and so do `execute` calls from automations and administrators. The Breaking section lists what behaves differently, and the Migration section says what to do when one of those applies to you. Version 3.3.0 was never released and is part of this one.

### Breaking

- **`mysql_query.execute` is for administrators.** A call made on behalf of a logged-in user who is not an administrator is refused. Calls that carry no user, such as an automation started by a trigger, are not affected. `mysql_query.query` stays open to every user. Until now any logged-in user could run arbitrary SQL writes through the API, with the credentials stored in the connection.
- **YAML configuration is gone.** A `mysql_query:` section in `configuration.yaml` used to be imported once, while Home Assistant reported the same section as unsupported. It is not imported any more; Home Assistant reports it and nothing else happens.
- **Connection settings and query behaviour are stored apart.** Host, port, credentials, database, connect timeout, charset, collation and TLS stay in the entry data and are changed with the new **Reconfigure** action. The query timeout, row limit, autocommit and read-only switch moved to the entry options and are changed under **Configure**. Existing connections are migrated automatically (config entry version 1 to 2).
- **Going back to 3.x is not possible without re-creating the connection.** The entry version is a major one on purpose: 3.x would look for the moved settings in the entry data and silently run with its defaults, for instance without the read-only switch. Home Assistant refuses to load an entry that is newer than the integration instead.
- **The minimum Home Assistant version is now 2026.3.0**, declared in `hacs.json` (previously 2025.3.0). Home Assistant moved to Python 3.14 with that release and the code uses Python 3.14 syntax; the brand images in `brand/` are also only read from the integration folder from that release on. HACS refuses to download this version on an older Home Assistant, which stays on the previous release.
- **A row limit, a connect timeout or a query timeout below 1, and a port outside 1-65535, are rejected by the forms.** A row limit below 1 used to be replaced by the default without a word.
- **Templates in `values` are rendered once, by Home Assistant, and no longer by the integration as well.** Automations, scripts and the developer tools are not affected: Home Assistant renders their templates before the call, with the same native types. A call that does not go through Home Assistant's script engine, such as a dashboard button that calls the action directly or a call through the API, has a template in `values` bound as text now. The `invalid_template` error is gone with it: a template that fails in an automation was always stopped by Home Assistant before the call, whatever `raise_on_error` said.

### Security

- **`query` could be used to write.** The check for reading looked at the first keyword only and counted `WITH` as reading, but MySQL 8 accepts `WITH ... UPDATE` and `WITH ... DELETE`, so those ran through `query`. That bypassed the split between the two actions, the administrator restriction on `execute` and the read-only connection switch. A `SELECT ... INTO OUTFILE` could write a file on the server through `query` as well, also when hidden in an executable comment (`/*! ... */`, `/*M! ... */`), which the server runs.
- **`WITH` is judged by the statement behind its CTE list**, which must be a `SELECT`, `TABLE` or `VALUES`; a list that cannot be read counts as a write. `INTO OUTFILE` and `INTO DUMPFILE` count as writes, outside quotes and comments. The text of an executable comment is read as the code it is, so a semicolon inside one is a second statement.
- **`query` runs inside a read-only transaction, as an extra layer of protection.** Every statement sent through `query` now runs inside `START TRANSACTION READ ONLY` and is always rolled back. For an ordinary statement the server then refuses to change a table (error 1792), also through a stored function. This needs MySQL 5.6.5 or MariaDB 10.0 or newer. It does not stop a file write, which the text check covers. `execute` is not affected. Neither the transaction nor the text check is a permission system: a statement written to slip its own `COMMIT` past the text check ends the transaction early. What a `query` call can really do is decided by the rights of the database user; the README now has a Security best practice section that recommends a `SELECT`-only user for a connection that non-administrators use.
- **A value could be run as a template twice.** Home Assistant renders the templates in `values` before the call, and the integration rendered the result again. Text that came out of a template and read like one itself, such as a sensor state, a media title or a note anyone can edit that says `{{ ... }}`, was evaluated instead of stored. The values are now bound as they arrive.
- **Database messages are kept out of the log.** A failure that is only reported in the response used to be logged at error level with the database message, which can carry data from the row it is about, such as the value in `Duplicate entry`. The log now gets a warning with the kind of failure and the errno; the whole message stays in the response.

### Added

- **Reconfigure** for the connection settings. The new settings are tried before they are saved, the unique id and the generated title follow a changed host or database, a collision with another connection is refused, and the connection reloads.
- **A sign-in flow when the credentials are refused.** Home Assistant starts it by itself when the database rejects the username or password, at startup, and during a call when a fresh login with the stored credentials is refused as well; it updates the existing connection. A call that gets "Access denied" for another reason, such as `LOAD DATA INFILE` without the `FILE` privilege, does not start it.
- **The connection is retried when the database cannot be reached while Home Assistant starts.** Setup used to log an error and stay failed until the entry was reloaded by hand. Only a server that cannot be reached, a lost connection, and a server that is full or shutting down are retried. Credentials that are refused, a database that does not exist or is off limits, a TLS connection that was asked for but not offered, and any other refusal by the server, such as a host the account may not connect from, a locked account or an expired password, each fail with their own message instead of being retried forever.

### Changed

- **The password field is masked** in the setup, reconfigure and sign-in forms. The edit form used to be prefilled with the stored password, which put it in the form definition and on screen. It is never prefilled now: leave the field empty to keep the current password.
- **`mysql_query.execute` can be called without a `response_variable`.** Its response is optional now; `query` still requires one. A failing call without one raises, because there is no response to report the failure in, unless it sets `raise_on_error: false`. A call with one reports the failure in its response, as before.
- **The services are registered once, with the integration**, and stay listed while no connection is loaded. A call then says why it cannot run (no connection loaded, or the chosen one is not) instead of the action having disappeared.
- **Errors are raised as the kind Home Assistant expects.** A call the caller got wrong raises `ServiceValidationError`, whatever `raise_on_error` says: no usable connection, an empty statement, several statements, the wrong service for the statement, a read-only connection. A failure of the database, a timeout and anything unexpected raise `HomeAssistantError`. All carry a translation key. `raise_on_error` keeps its meaning and defaults.
- **A failure that is raised is no longer also logged as an error.** One that is only reported in the response is logged as a warning, without the database message (see Security).
- **A connection that fails in the setup, reconfigure or sign-in form is no longer logged as an error.** The form shows the reason, and the debug log has the details. An unexpected exception is still logged with its traceback.
- **`iot_class` is `local_polling`** instead of `local_push`: nothing is pushed, a query runs when an action asks for it.
- **The TLS context comes from Home Assistant.** `ssl.create_default_context()` loads the CA bundle from disk, and it was called on the event loop. Home Assistant's cached context is used instead. The server certificate is still not verified.
- `services.yaml` and the strings now carry the same names and descriptions. The `db4query` field was called "Database Override" in one and "Database for query" in the other; it is "Database override" in both.
- The raw brand artwork moved from the repository root to `scripts/brand_sources/`, and `scripts/build_brands.py` reads it from there.
- The README describes all of this, including who may call `execute` and how to let a non-administrator cause a write through an automation.

### Removed

- The unused `cannot_connect` abort reason from the translations.

### Fixed

- **A cancelled call no longer hands a busy connection back to the pool.** When the automation that made a call was stopped, or Home Assistant shut down, while the statement ran, the connection went back to the pool with the statement still in flight, and the next call on it could read the leftovers. It is dropped now, as after a timeout.
- **A call that is cancelled or times out frees its place in the pool.** Its connection was closed but never handed back, so it kept one of the five places for good. After five such calls every call waited until its timeout, and unloading the connection hung.

### Migration

- **Writing through `query`:** a `WITH ... UPDATE`, a `WITH ... DELETE` or a `SELECT ... INTO OUTFILE` sent to `query` is refused now. Send it to `execute`.
- **Using `execute` from a dashboard as a user who is not an administrator:** the call is refused now. Put the write in an automation and let the dashboard trigger that, for instance through an `input_button` helper. The README has the details.
- **Still have a `mysql_query:` section in `configuration.yaml`:** add the connection in the UI and remove the section. Connections that were imported earlier are config entries already and are not affected.
- **Changing a setting:** host, port, credentials, database, charset, collation and TLS are under **Reconfigure** (the menu of the connection); the query timeout, row limit, autocommit and read-only switch are under **Configure**.
- **Running Home Assistant older than 2026.3.0:** stay on 3.2.0. HACS will not install this version there.
- **A dashboard button or an API call with a template in `values`:** the template is stored as text now. Let the button run a script that makes the call; Home Assistant renders the template there. Automations and scripts need no change.

## [3.2.0] - 2026-09-26

### Added

- **Query Timeout (seconds)** (`mysql_query_timeout`, default `30`), a new
  connection setting that bounds a whole service call — waiting for a free
  pooled connection, reconnecting it if needed, and running the statement —
  instead of only the wait for a free connection. A call still running when
  it elapses fails with an error instead of hanging, and its connection is
  dropped instead of being handed back for the next call to reuse.

### Fixed

- `manifest.json` now reports `3.2.0`; the previous release (v3.1.0, the
  automated release-zip workflow) had shipped with the version field still
  reading `3.0.0`.

## [3.1.0] - 2026-09-26

Releases ship a `homeassistant-mysql_query.zip` asset again, built and attached automatically instead of by hand.

### Added

- `.github/workflows/release.yaml`, which builds `custom_components/mysql_query/` into `homeassistant-mysql_query.zip` and attaches it to a release when it is published. `zip_release` and `filename` are back in `hacs.json`, so HACS installs from that asset instead of fetching every file separately through the GitHub API, and the per-release downloads badge in the README works again.

## [3.0.0] - 2026-08-23

**Breaking:** reading and writing are now split across the two services. `query` runs only statements that read, `execute` only statements that change something. The Migration section further down in this entry has the details; it is a one-word change per call.

### Changed

- **`mysql_query.query` refuses any statement that is not read-only**, and the error names `mysql_query.execute` as where the call belongs. Until now both services ran anything and differed only in what they returned, so a service called `query` would happily run a DELETE. That is the accident this release is about. This is breaking for calls that have used `query` for writes since v1.4.0 (2025-01-05, commit `eb11f99`, "Support for all SQL query types"), where the original SELECT-only guard was removed.
- **`mysql_query.execute` refuses a read-only statement**, and the error names `mysql_query.query`. The split is symmetrical on purpose: each service does one thing, and reaching for the wrong one always tells you which one you wanted.
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

### What counts as read-only

`query` accepts `SELECT`, `WITH`, `SHOW`, `DESCRIBE`/`DESC`, `CHECKSUM TABLE`, `HELP`, and the MySQL 8 `TABLE` and `VALUES` shorthands. Everything else goes to `execute`.

Statements that look informational but change something are deliberately not on that list: `ANALYZE TABLE` (it rewrites index statistics), `CHECK`, `OPTIMIZE` and `REPAIR` (they can rewrite a table), `FLUSH`, `SET` and `USE` (server or session state, and `USE` would leave a pooled connection pointing at another database), `DO` and `CALL` (they evaluate code that can write), and `PREPARE`/`EXECUTE`/`DEALLOCATE`, which can carry any statement at all.

`EXPLAIN` and `ANALYZE` are prefixes in front of another statement rather than statements of their own, and they are **not** handled the same way, because they do not do the same thing.

- **`EXPLAIN` is always read-only**, whatever follows it. It only produces a plan and never carries out what it describes, so `EXPLAIN DELETE FROM t` goes to `query` just as `EXPLAIN SELECT` does. The classification of the wrapped statement does not affect the outcome.
- **`ANALYZE` takes over the classification of the statement behind it**, because it really runs that statement and reports what it did. So `ANALYZE SELECT` goes to `query` and `ANALYZE DELETE` to `execute`, exactly as the bare statements would. `EXPLAIN ANALYZE` is the running kind and follows this rule too.
- **`ANALYZE TABLE` is the exception**: it is not a prefix in front of anything but the maintenance command, and it rewrites index statistics, so it always counts as a write.

Options such as `FORMAT=JSON` between the prefix and the statement are skipped. Measured against MariaDB 10.11: on a three-row table, `EXPLAIN DELETE` left three rows and `ANALYZE DELETE` left none.

### Note on what the guard is not

The check strips comments and reads the leading keywords of the statement, resolving an `EXPLAIN` or `ANALYZE` prefix as described above; it guards against reaching for the wrong service, not against a determined write. A SELECT can still write through `INTO OUTFILE` or a stored function with side effects, and MySQL 8 accepts a CTE in front of an UPDATE or DELETE. Read-only rights on the database user remain the boundary that actually holds.

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
