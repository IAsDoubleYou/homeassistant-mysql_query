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


@pytest.mark.parametrize(
    "statement",
    [
        # MySQL 8 and MariaDB accept a write behind a CTE list.
        "WITH c AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT * FROM c)",
        "WITH c AS (SELECT id FROM t) UPDATE t JOIN c USING (id) SET x = 1",
        "with recursive c(n) as (select 1) delete from t",
        "WITH a AS (SELECT 1), b AS (SELECT 2) UPDATE t SET x = 1",
        "WITH `my cte` (x) AS (SELECT ')') DELETE FROM t",
        "WITH c AS (SELECT 1) /* note */ DELETE FROM t",
        "WITH c AS (SELECT 1) -- note\nDELETE FROM t",
        "ANALYZE WITH c AS (SELECT 1) DELETE FROM t",
        # A CTE list that cannot be read is never assumed to read.
        "WITH c AS (SELECT 1)",
        "WITH c AS SELECT 1 SELECT 1",
        "WITH c AS (SELECT 1",
        "WITH",
        # A SELECT can write a file on the server.
        "SELECT * FROM t INTO OUTFILE '/tmp/x'",
        "SELECT * FROM t INTO DUMPFILE '/tmp/x'",
        "select * from t into   outfile '/tmp/x'",
        "SELECT * FROM t INTO /* gap */ OUTFILE '/tmp/x'",
        "TABLE t INTO OUTFILE '/tmp/x'",
        "WITH c AS (SELECT 1) SELECT * FROM c INTO OUTFILE '/tmp/x'",
        "SELECT * FROM (SELECT 1) AS d INTO OUTFILE '/tmp/x'",
        # The server runs what an executable comment holds.
        "SELECT 1 /*! INTO OUTFILE '/tmp/x' */",
        "SELECT 1 /*!50000 INTO OUTFILE '/tmp/x' */",
        "SELECT 1 /*M!100000 INTO DUMPFILE '/tmp/x' */",
        "/*! DELETE FROM t */",
    ],
)
def test_a_write_does_not_pass_as_reading(statement: str) -> None:
    """Statements that write behind a read-looking start are not reading.

    Each of these starts like something harmless, or hides the part that
    writes, and would reach the database through query if only the first
    keyword counted.
    """
    assert is_read_only(statement) is False


@pytest.mark.parametrize(
    "statement",
    [
        "WITH c AS (SELECT 1) SELECT * FROM c",
        (
            "WITH RECURSIVE c(n) AS "
            "(SELECT 1 UNION ALL SELECT n + 1 FROM c WHERE n < 3) SELECT * FROM c"
        ),
        "WITH a AS (SELECT 1), b AS (SELECT 2) SELECT * FROM a, b",
        "WITH `my cte` (x) AS (SELECT ')') SELECT * FROM `my cte`",
        "WITH c AS (SELECT 1) (SELECT * FROM c)",
        "WITH c AS (SELECT 1) TABLE c",
        "WITH c AS (SELECT 1) VALUES ROW(1)",
        "WITH c AS (SELECT 1) /* note */ SELECT * FROM c",
        "EXPLAIN WITH c AS (SELECT 1) DELETE FROM t",
        # Only text, not a file write.
        "SELECT 'into outfile' AS x",
        'SELECT "into dumpfile" AS x',
        "SELECT `outfile` FROM t",
        "SELECT * FROM t -- INTO OUTFILE '/tmp/x'",
        "SELECT * FROM t /* INTO OUTFILE '/tmp/x' */",
        "SELECT * FROM t WHERE note = 'x INTO OUTFILE y'",
        # Into a variable is session state, not a write to the database.
        "SELECT 1 INTO @v",
        "SELECT /*! 1 */ 2",
    ],
)
def test_reading_stays_reading(statement: str) -> None:
    """The statements that only read, written in the ways that look risky."""
    assert is_read_only(statement) is True


def test_an_executable_comment_is_read_as_code() -> None:
    """Its text is kept, so the keyword check sees what the server will run."""
    assert strip_comments("SELECT 1 /*!50000 , 2 */").split() == [
        "SELECT",
        "1",
        ",",
        "2",
    ]
    assert first_keyword("/*! DELETE FROM t */") == "delete"


def test_a_statement_hidden_in_an_executable_comment_counts_as_a_second_one() -> None:
    """The server splits on a semicolon inside it, so the splitter has to as well."""
    assert len(split_statements("SELECT 1 /*! ; DELETE FROM t */")) == 2
