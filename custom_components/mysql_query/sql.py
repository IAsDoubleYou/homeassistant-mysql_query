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

# WITH opens a statement without being one: it names common table expressions
# and then hands over to the statement that uses them, which MySQL 8 and
# MariaDB let be a SELECT but also an UPDATE or a DELETE. So it is not on the
# list above; the statement behind the CTE list decides (see is_read_only).
_WITH_KEYWORD: Final = "with"

# What the statement behind a CTE list may be to still only read.
_CTE_READ_ONLY_KEYWORDS: Final = frozenset({"select", "table", "values"})

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

# MySQL runs the text inside /*! ... */ (and MariaDB inside /*M! ... */), with
# an optional version number after the marker. It looks like a comment and
# executes like code, so it is read as code here.
_EXECUTABLE_COMMENT_RE: Final = re.compile(r"/\*M?!(?:\d+)?")

# Writes a file on the database server, whatever the statement around it is.
_INTO_FILE_RE: Final = re.compile(r"\binto\s+(?:outfile|dumpfile)\b", re.IGNORECASE)

_CTE_NAME_RE: Final = re.compile(r"\s*(?:`(?:[^`]|``)+`|[A-Za-z0-9_$\u0080-\uffff]+)")
_AS_RE: Final = re.compile(r"\s*as\b", re.IGNORECASE)
_WITH_RE: Final = re.compile(r"[(\s]*with\b(\s+recursive\b)?", re.IGNORECASE)


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

    The exception is the executable comment, "/*! ... */" and "/*M! ... */":
    the server runs what is inside, so its text is kept and only the markers
    go. Dropping it would let "SELECT 1 /*! INTO OUTFILE '/tmp/x' */" read as
    a plain SELECT.
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
            stop = length if end == -1 else end
            marker = _EXECUTABLE_COMMENT_RE.match(statement, index)
            if marker is not None:
                out.append(" " + statement[marker.end() : stop] + " ")
            else:
                out.append(" ")
            index = length if end == -1 else end + 2
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


def _mask_quoted(text: str) -> str:
    """Return the text with everything inside quotes blanked out.

    Lets a keyword search run over the statement without matching the same
    words inside a string or an identifier: "SELECT 'into outfile'" is only
    text.
    """
    out: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char in _QUOTES:
            end = _skip_quoted(text, index, char)
            out.append(" " * (end - index))
            index = end
            continue
        out.append(char)
        index += 1

    return "".join(out)


def _skip_balanced(text: str, start: int) -> int | None:
    """Return the index just past the bracket pair that opens at ``start``.

    Quoted sections are skipped, so a bracket inside a string does not count.
    None when the brackets never balance.
    """
    depth = 0
    index = start
    length = len(text)

    while index < length:
        char = text[index]
        if char in _QUOTES:
            index = _skip_quoted(text, index, char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1

    return None


def statement_after_ctes(statement: str) -> str | None:
    """Return the statement a WITH clause hands over to.

    Walks "WITH [RECURSIVE] name [(columns)] AS (...) [, ...]" and returns
    what follows it, or None when the clause is not shaped like that. A caller
    that gets None must not assume the statement only reads.
    """
    match = _WITH_RE.match(statement)
    if match is None:
        return None

    position = match.end()
    while True:
        name = _CTE_NAME_RE.match(statement, position)
        if name is None:
            return None
        position = name.end()

        # The optional list of column names.
        while position < len(statement) and statement[position].isspace():
            position += 1
        if statement.startswith("(", position):
            end = _skip_balanced(statement, position)
            if end is None:
                return None
            position = end

        keyword = _AS_RE.match(statement, position)
        if keyword is None:
            return None
        position = keyword.end()

        while position < len(statement) and statement[position].isspace():
            position += 1
        if not statement.startswith("(", position):
            return None
        end = _skip_balanced(statement, position)
        if end is None:
            return None
        position = end

        while position < len(statement) and statement[position].isspace():
            position += 1
        if statement.startswith(",", position):
            position += 1
            continue
        return statement[position:]


def is_read_only(statement: str) -> bool:
    """Return whether a single statement only reads.

    A statement counts as reading when it starts with a keyword that never
    changes anything, and:

    - for WITH, the statement behind the CTE list is a SELECT, TABLE or
      VALUES. MySQL 8 and MariaDB also accept an UPDATE or a DELETE there, and
      a list that cannot be read is treated as a write;
    - it does not write a file on the server (INTO OUTFILE, INTO DUMPFILE),
      which a SELECT is otherwise allowed to do. What is inside quotes and
      comments does not count, but the content of an executable comment does.

    This is a guard against reaching for the wrong service, not a permission
    system. It cannot see what a stored function does, so the integration
    also runs everything it lets through query inside a read-only
    transaction. What a call can really do is decided by the rights of the
    database user.
    """
    inner, runs = unwrap_prefixes(statement)

    # Planned but never carried out, so whatever it wraps cannot write.
    if not runs:
        return True

    text = strip_comments(inner)

    if first_keyword(text) == _WITH_KEYWORD:
        text = statement_after_ctes(text) or ""
        if first_keyword(text) not in _CTE_READ_ONLY_KEYWORDS:
            return False
    elif first_keyword(text) not in READ_ONLY_KEYWORDS:
        return False

    return _INTO_FILE_RE.search(_mask_quoted(text)) is None
