"""Tests for the statement classifier behind the query/execute split."""

from __future__ import annotations

import pytest

from custom_components.mysql_query.sql import (
    first_keyword,
    is_read_only,
    split_statements,
    strip_comments,
    unwrap_prefixes,
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
        # Rewrites index statistics, so not a wrapped statement but the
        # maintenance command.
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
    ("statement", "expected"),
    [
        # ANALYZE runs what it wraps, so the wrapped statement decides.
        # Measured against MariaDB 10.11 on a three-row table.
        ("ANALYZE SELECT * FROM t", True),
        ("ANALYZE FORMAT=JSON SELECT * FROM t", True),
        ("ANALYZE DELETE FROM t", False),
        ("ANALYZE UPDATE t SET a = 1", False),
        ("ANALYZE INSERT INTO t VALUES (1)", False),
        ("ANALYZE FORMAT=JSON DELETE FROM t", False),
        # EXPLAIN only produces a plan, so nothing it wraps is carried out.
        ("EXPLAIN SELECT * FROM t", True),
        ("EXPLAIN DELETE FROM t", True),
        ("EXPLAIN UPDATE t SET a = 1", True),
        ("EXPLAIN INSERT INTO t VALUES (1)", True),
        ("EXPLAIN FORMAT=JSON DELETE FROM t", True),
        ("EXPLAIN EXTENDED SELECT 1", True),
        # EXPLAIN ANALYZE is the running kind again, so the wrapped
        # statement decides once more.
        ("EXPLAIN ANALYZE SELECT * FROM t", True),
        ("EXPLAIN ANALYZE DELETE FROM t", False),
        ("EXPLAIN ANALYZE FORMAT=TREE UPDATE t SET a = 1", False),
        ("explain analyze insert into t values (1)", False),
        ("/* note */ ANALYZE DELETE FROM t", False),
        ("/* note */ ANALYZE SELECT 1", True),
    ],
)
def test_prefix_is_classified_by_what_it_wraps(statement: str, expected: bool) -> None:
    """EXPLAIN and ANALYZE are not statements of their own.

    Treating them as keywords made ANALYZE SELECT a write and ANALYZE DELETE
    a read, both wrong. What they wrap is what decides, together with whether
    the prefix runs it or only plans it.
    """
    assert is_read_only(statement) is expected


@pytest.mark.parametrize(
    ("statement", "inner", "runs"),
    [
        ("SELECT 1", "SELECT 1", True),
        ("EXPLAIN SELECT 1", "SELECT 1", False),
        ("ANALYZE SELECT 1", "SELECT 1", True),
        ("EXPLAIN ANALYZE SELECT 1", "SELECT 1", True),
        ("EXPLAIN FORMAT=JSON SELECT 1", "SELECT 1", False),
        ("ANALYZE FORMAT = JSON SELECT 1", "SELECT 1", True),
        # Not a wrapped statement: the maintenance command comes back whole.
        ("ANALYZE TABLE t", "ANALYZE TABLE t", True),
    ],
)
def test_unwrap_prefixes(statement: str, inner: str, runs: bool) -> None:
    """The prefix and its options are peeled off, the statement stays."""
    assert unwrap_prefixes(statement) == (inner, runs)
