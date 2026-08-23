"""Classification of the SQL a service call carries.

The driver decides nothing here: aiomysql turns on CLIENT.MULTI_STATEMENTS
unconditionally and offers no way to turn it off, so "one call, one statement"
has to be established before the statement is handed over. Everything in this
module works on the text alone and never touches a connection.
"""

from __future__ import annotations

import re
from typing import Final

# Statements that never change data or schema. Anything else counts as a
# write, which is what decides whether a call belongs to query or to execute.
#
# Deliberately left out, because they do change something despite looking
# informational: ANALYZE (MariaDB runs "ANALYZE <statement>" for real, and
# ANALYZE TABLE rewrites index statistics), CHECK and REPAIR and OPTIMIZE
# (they can rewrite a table), FLUSH, SET and USE (server or session state,
# and USE would leave a pooled connection pointing at another database), DO
# and CALL (they evaluate code that can write), HANDLER, LOCK and UNLOCK, the
# transaction statements, and PREPARE/EXECUTE/DEALLOCATE, which can carry any
# statement at all.
READ_ONLY_KEYWORDS: Final = frozenset(
    {
        "select",
        "with",
        "show",
        "describe",
        "desc",
        "explain",
        "checksum",  # CHECKSUM TABLE only reads to compute the checksum.
        "help",
        # MySQL 8 shorthands: TABLE t is SELECT * FROM t, and VALUES builds a
        # result set out of literal rows. Neither has a writing form.
        "table",
        "values",
    }
)

# "EXPLAIN ANALYZE <statement>" does not plan the statement, it runs it. The
# bare EXPLAIN form only plans, which is why EXPLAIN itself is allowed above.
_EXECUTING_EXPLAIN: Final = ("explain", "analyze")

# The keyword may be preceded by brackets, as in (SELECT ...).
_FIRST_WORD_RE: Final = re.compile(r"[(\s]*([A-Za-z_]+)")
_LEADING_WORDS_RE: Final = re.compile(r"[(\s]*([A-Za-z_]+)(?:\s+([A-Za-z_]+))?")

_QUOTES: Final = ("'", '"', "`")


def _skip_quoted(statement: str, start: int, quote: str) -> int:
    """Return the index just past a quoted section that opens at ``start``.

    Both escape styles MySQL accepts are handled: a backslash before the
    character, and the quote character doubled. Backticks quote identifiers and
    know only the doubling form.
    """
    index = start + 1
    length = len(statement)
    while index < length:
        char = statement[index]
        if char == "\\" and quote != "`" and index + 1 < length:
            index += 2
            continue
        if char == quote:
            if index + 1 < length and statement[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return length


def strip_comments(statement: str) -> str:
    """Return the statement with its comments replaced by a space.

    A comment can hide the keyword that decides where a call belongs, so
    "/* note */ DELETE FROM x" has to read as a delete rather than as
    something that starts with a slash. Quoted sections are left alone: a
    "--" inside a string is data, not a comment.
    """
    out: list[str] = []
    index = 0
    length = len(statement)

    while index < length:
        char = statement[index]

        if char in _QUOTES:
            end = _skip_quoted(statement, index, char)
            out.append(statement[index:end])
            index = end
            continue

        if statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            index = length if end == -1 else end + 2
            out.append(" ")
            continue

        # MySQL wants whitespace after "--", but treating "--x" as a comment
        # too only ever exposes more of the statement to the keyword check.
        if statement.startswith("--", index) or char == "#":
            end = statement.find("\n", index)
            index = length if end == -1 else end
            out.append(" ")
            continue

        out.append(char)
        index += 1

    return "".join(out)


def split_statements(statement: str) -> list[str]:
    """Return the separate statements in ``statement``.

    Splitting happens on semicolons outside quotes and comments, so
    "SELECT 'a;b'" is one statement and a trailing semicolon does not make a
    second, empty one.
    """
    cleaned = strip_comments(statement)
    parts: list[str] = []
    current: list[str] = []
    index = 0
    length = len(cleaned)

    while index < length:
        char = cleaned[index]

        if char in _QUOTES:
            end = _skip_quoted(cleaned, index, char)
            current.append(cleaned[index:end])
            index = end
            continue

        if char == ";":
            parts.append("".join(current))
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def first_keyword(statement: str) -> str:
    """Return the opening keyword of a single statement, lowercased."""
    match = _FIRST_WORD_RE.match(strip_comments(statement))
    return match.group(1).lower() if match else ""


def is_read_only(statement: str) -> bool:
    """Return whether a single statement only reads.

    This is a guard against reaching for the wrong service, not a security
    boundary. A SELECT can still write through INTO OUTFILE or a stored
    function with side effects, and MySQL 8 accepts a CTE in front of an
    UPDATE or a DELETE. Read-only rights on the database user are what
    actually stops a write.
    """
    match = _LEADING_WORDS_RE.match(strip_comments(statement))
    if match is None:
        return False

    first = match.group(1).lower()
    if first not in READ_ONLY_KEYWORDS:
        return False

    second = (match.group(2) or "").lower()
    return (first, second) != _EXECUTING_EXPLAIN
