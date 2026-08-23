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
        # Read-only but not SELECT or WITH, so it counts as a write here.
        ("SHOW TABLES", False),
    ],
)
def test_is_read_only(statement: str, expected: bool) -> None:
    """Only SELECT and WITH count as reading."""
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
