"""Tests for the statement classifier behind the query/execute split."""

from __future__ import annotations

import pytest

from custom_components.mysql_query.sql import (
    first_keyword,
    is_read_only,
    split_statements,
    strip_comments,
)


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("SELECT 1", True),
        ("SHOW TABLES", True),
        ("SHOW CREATE TABLE t", True),
        ("DESCRIBE t", True),
        ("DESC t", True),
        ("EXPLAIN SELECT * FROM t", True),
        # EXPLAIN only plans; it does not run the statement it describes.
        ("EXPLAIN DELETE FROM t", True),
        ("CHECKSUM TABLE t", True),
        ("HELP 'contents'", True),
        ("TABLE t", True),
        ("VALUES ROW(1, 2)", True),
        ("select 1", True),
        ("  SeLeCt 1  ", True),
        ("WITH c AS (SELECT 1) SELECT * FROM c", True),
        ("(SELECT 1)", True),
        ("INSERT INTO t VALUES (1)", False),
        ("UPDATE t SET a = 1", False),
        ("DELETE FROM t", False),
        ("DROP TABLE t", False),
        ("TRUNCATE TABLE t", False),
        ("CREATE TABLE t (id INT)", False),
        ("REPLACE INTO t VALUES (1)", False),
        # Runs the statement it is put in front of instead of planning it,
        # measured against MariaDB 10.11: ANALYZE DELETE emptied the table.
        ("ANALYZE DELETE FROM t", False),
        ("ANALYZE SELECT * FROM t", False),
        # Rewrites index statistics.
        ("ANALYZE TABLE t", False),
        # Can rewrite a table depending on the engine.
        ("CHECK TABLE t", False),
        ("OPTIMIZE TABLE t", False),
        ("REPAIR TABLE t", False),
        # Session or server state rather than data, but still not a read, and
        # USE would leave a pooled connection pointing somewhere else.
        ("USE other_db", False),
        ("SET GLOBAL x = 1", False),
        ("FLUSH TABLES", False),
        # Carry code that can do anything.
        ("CALL do_something()", False),
        ("DO SLEEP(1)", False),
        ("EXECUTE stmt", False),
    ],
)
def test_is_read_only(statement: str, expected: bool) -> None:
    """Statements that never change data or schema count as reading."""
    assert is_read_only(statement) is expected


@pytest.mark.parametrize(
    ("statement", "keyword"),
    [
        ("/* note */ SELECT 1", "select"),
        ("/* note */ DELETE FROM t", "delete"),
        ("-- note\nDELETE FROM t", "delete"),
        ("#note\nUPDATE t SET a = 1", "update"),
        ("/* a */ /* b */ SELECT 1", "select"),
    ],
)
def test_a_comment_does_not_hide_the_keyword(statement: str, keyword: str) -> None:
    """A leading comment must not decide what a statement counts as.

    Both directions matter: a commented SELECT has to stay allowed on query,
    and a commented DELETE must not slip past as something unrecognised.
    """
    assert first_keyword(statement) == keyword


def test_comments_inside_a_string_are_left_alone() -> None:
    """A comment marker inside a string literal is data, not a comment."""
    assert strip_comments("SELECT '-- not a comment'") == "SELECT '-- not a comment'"
    assert strip_comments("SELECT '/* nor this */'") == "SELECT '/* nor this */'"


@pytest.mark.parametrize(
    ("statement", "count"),
    [
        ("SELECT 1", 1),
        # A trailing semicolon is habit, not a second statement.
        ("SELECT 1;", 1),
        ("SELECT 1 ;   ", 1),
        ("SELECT 1; -- done", 1),
        # Semicolons inside quotes belong to the value.
        ("SELECT 'a;b' AS v", 1),
        ("SELECT `we;ird` FROM t", 1),
        ("DELETE FROM t WHERE s = 'a;b'", 1),
        ("SELECT 'it''s;' AS v", 1),
        # The case the driver would happily run in full.
        ("SELECT 1; DELETE FROM t", 2),
        ("INSERT INTO t VALUES (1); INSERT INTO t VALUES (2)", 2),
        ("", 0),
        ("   ", 0),
        (";", 0),
        ("-- only a comment", 0),
    ],
)
def test_split_statements(statement: str, count: int) -> None:
    """Statements are separated on semicolons outside quotes and comments."""
    assert len(split_statements(statement)) == count


def test_split_keeps_the_statement_text() -> None:
    """The parts come back stripped but otherwise unchanged."""
    assert split_statements("  SELECT 1 ;  ") == ["SELECT 1"]
    assert split_statements("SELECT 1; DELETE FROM t") == ["SELECT 1", "DELETE FROM t"]


@pytest.mark.parametrize(
    "statement",
    [
        "EXPLAIN ANALYZE SELECT * FROM t",
        "EXPLAIN ANALYZE DELETE FROM t",
        "explain   analyze   update t SET a = 1",
        "/* note */ EXPLAIN ANALYZE DELETE FROM t",
    ],
)
def test_explain_analyze_is_not_read_only(statement: str) -> None:
    """EXPLAIN ANALYZE runs the statement instead of planning it.

    Plain EXPLAIN only produces the plan, which is why EXPLAIN is allowed,
    but MySQL 8 runs the statement when ANALYZE follows. MariaDB 10.11
    rejects the syntax outright, so the server cannot be relied on to stop it.
    """
    assert is_read_only(statement) is False


def test_explain_without_analyze_stays_read_only() -> None:
    """The word analyze only matters directly after EXPLAIN."""
    assert is_read_only("EXPLAIN SELECT analyze_column FROM t") is True
