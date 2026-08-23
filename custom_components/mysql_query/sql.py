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
        "checksum",  # CHECKSUM TABLE only reads to compute the checksum.
        "help",
        # MySQL 8 shorthands: TABLE t is SELECT * FROM t, and VALUES builds a
        # result set out of literal rows. Neither has a writing form.
        "table",
        "values",
    }
)

# EXPLAIN and ANALYZE are not statements of their own, they wrap one. Which of
# the two it is decides whether the wrapped statement is only planned or
# actually run, so they are peeled off and what is left is classified instead.
#
# Measured against MariaDB 10.11 on a three-row table: "EXPLAIN DELETE FROM t"
# left all three rows, "ANALYZE DELETE FROM t" left none.
_PLANNING_PREFIX: Final = "explain"
_EXECUTING_PREFIX: Final = "analyze"

# Options that may sit between the prefix and the statement it wraps, such as
# EXPLAIN FORMAT=JSON SELECT ... or EXPLAIN EXTENDED SELECT ...
_PREFIX_OPTION_RE: Final = re.compile(
    r"\s*(?:extended|partitions|format\s*=\s*[A-Za-z_]+)\b", re.IGNORECASE
)

# The keyword may be preceded by brackets, as in (SELECT ...).
_FIRST_WORD_RE: Final = re.compile(r"[(\s]*([A-Za-z_]+)")
_WORD_RE: Final = re.compile(r"[(\s]*([A-Za-z_]+)")

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


def unwrap_prefixes(statement: str) -> tuple[str, bool]:
    """Peel EXPLAIN and ANALYZE off a statement.

    Returns what they wrap, and whether that wrapped statement is actually
    run. EXPLAIN only produces a plan, so what it wraps never happens;
    ANALYZE runs the statement and reports what it did, so what it wraps
    happens for real. "EXPLAIN ANALYZE" is the second kind.

    ANALYZE TABLE is not a wrapped statement but the maintenance command,
    which rewrites index statistics, so it is left alone to be classified as
    a write on its own.
    """
    text = strip_comments(statement).strip()
    runs = True

    while (match := _WORD_RE.match(text)) is not None:
        word = match.group(1).lower()

        if word == _PLANNING_PREFIX:
            runs = False
        elif word == _EXECUTING_PREFIX:
            rest = text[match.end() :]
            if (following := _WORD_RE.match(rest)) is not None and following.group(
                1
            ).lower() == "table":
                # ANALYZE TABLE, the maintenance command.
                return text, True
            runs = True
        else:
            break

        text = text[match.end() :]
        text = _PREFIX_OPTION_RE.sub("", text, count=0).lstrip()

    return text, runs


def is_read_only(statement: str) -> bool:
    """Return whether a single statement only reads.

    This is a guard against reaching for the wrong service, not a security
    boundary. A SELECT can still write through INTO OUTFILE or a stored
    function with side effects, and MySQL 8 accepts a CTE in front of an
    UPDATE or a DELETE. Read-only rights on the database user are what
    actually stops a write.
    """
    inner, runs = unwrap_prefixes(statement)

    # Planned but never carried out, so whatever it wraps cannot write.
    if not runs:
        return True

    return first_keyword(inner) in READ_ONLY_KEYWORDS
