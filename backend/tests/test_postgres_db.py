"""Render 用的 Postgres 包裝層。

這台電腦沒有 Postgres，這裡用假的連線測包裝層自己的邏輯（佔位符、型別、
交易、重連、不洩漏密碼）；真的 SQL 在 test_postgres_integration.py 對真的資料庫跑。
"""

import unittest
from datetime import datetime, timezone

import psycopg2

from repositories.postgres_db import (
    DatabaseUnavailable,
    PostgresDatabase,
    describe_database_url,
    ssl_mode_for,
    to_pyformat,
)
from repositories.sqlite_db import SqliteDatabase, from_json

# 密碼是 s3cr@t，網址裡編碼成 s3cr%40t
URL = "postgresql://postgres.abc:s3cr%40t@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self.conn.broken:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        self.conn.executed.append((sql, params))
        self._rows = list(self.conn.next_rows)
        self.rowcount = self.conn.next_rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.next_rows = []
        self.next_rowcount = 1
        self.broken = False
        self.closed = False
        self.autocommit = False

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def close(self):
        self.closed = True


class FakeConnector:
    """psycopg2.connect 的替身：記下每次連線的參數，可以指定接下來幾次失敗。"""

    def __init__(self, failures=0, error=None):
        self.failures = failures
        self.error = error or psycopg2.OperationalError("could not connect to server")
        self.calls = []
        self.connections = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.failures:
            self.failures -= 1
            raise self.error
        conn = FakeConnection()
        self.connections.append(conn)
        return conn


def statements(conn):
    return [sql for sql, _ in conn.executed]


class PlaceholderTests(unittest.TestCase):
    def test_question_marks_become_pyformat(self):
        self.assertEqual(
            to_pyformat("SELECT doc FROM t WHERE k IN (?, ?, ?) AND name LIKE ?"),
            "SELECT doc FROM t WHERE k IN (%s, %s, %s) AND name LIKE %s",
        )

    def test_literal_percent_is_escaped(self):
        self.assertEqual(to_pyformat("SELECT '100%' WHERE a = ?"), "SELECT '100%%' WHERE a = %s")

    def test_params_are_sent_as_a_tuple(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        db.query_all("SELECT doc FROM custom_foods WHERE user_id = ?", ["user-a"])
        self.assertEqual(
            connector.connections[0].executed[-1],
            ("SELECT doc FROM custom_foods WHERE user_id = %s", ("user-a",)),
        )

    def test_statements_without_params_are_sent_untouched(self):
        # 沒有參數時 psycopg2 不處理 %，所以不能把 % 變成 %%
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        db.execute("SELECT '100%'")
        self.assertEqual(connector.connections[0].executed[-1], ("SELECT '100%'", None))


class RowTests(unittest.TestCase):
    def test_datetimes_come_back_as_utc_iso_strings_and_json_as_is(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].next_rows = [{
            "failed_until": datetime(2026, 10, 15, 1, 2, 3, tzinfo=timezone.utc),
            "doc": {"name": "滷肉飯"},
        }]
        row = db.query_one("SELECT failed_until, doc FROM t WHERE venue_key = ?", ("k",))
        self.assertEqual(row["failed_until"], "2026-10-15T01:02:03.000000+00:00")
        self.assertEqual(row["doc"], {"name": "滷肉飯"})

    def test_query_one_returns_none_when_nothing_matches(self):
        db = PostgresDatabase(URL, connect=FakeConnector())
        self.assertIsNone(db.query_one("SELECT doc FROM users WHERE user_id = ?", ("nobody",)))

    def test_execute_returns_the_rowcount(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].next_rowcount = 0
        self.assertEqual(db.execute("INSERT INTO auth_users (id) VALUES (?) ON CONFLICT DO NOTHING", ("a",)), 0)

    def test_from_json_accepts_values_postgres_already_decoded(self):
        self.assertEqual(from_json({"a": 1}), {"a": 1})
        self.assertEqual(from_json([1, 2]), [1, 2])
        self.assertEqual(from_json('{"a": 1}'), {"a": 1})
        self.assertIsNone(from_json(None))
        self.assertIsNone(from_json(""))

    def test_column_names_read_information_schema(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].next_rows = [{"column_name": "user_id"}, {"column_name": "doc"}]
        self.assertEqual(db.column_names("users"), ["user_id", "doc"])
        sql, params = connector.connections[0].executed[-1]
        self.assertIn("information_schema.columns", sql)
        self.assertEqual(params, ("users",))

    def test_dialects(self):
        self.assertEqual(PostgresDatabase.dialect, "postgres")
        self.assertEqual(SqliteDatabase(":memory:").dialect, "sqlite")


class ConnectionTests(unittest.TestCase):
    def test_cloud_hosts_require_ssl_and_local_hosts_prefer_it(self):
        self.assertEqual(ssl_mode_for(URL), "require")
        self.assertEqual(ssl_mode_for("postgresql://u:p@localhost:5432/db"), "prefer")
        self.assertEqual(ssl_mode_for("postgresql://u:p@127.0.0.1:5432/db"), "prefer")
        self.assertIsNone(ssl_mode_for(URL + "?sslmode=disable"))

    def test_connects_with_autocommit_timeout_and_ssl(self):
        connector = FakeConnector()
        PostgresDatabase(URL, connect=connector)
        self.assertEqual(connector.calls[0], (URL, {"connect_timeout": 10, "sslmode": "require"}))
        self.assertTrue(connector.connections[0].autocommit)

    def test_url_with_its_own_sslmode_is_left_alone(self):
        connector = FakeConnector()
        PostgresDatabase(URL + "?sslmode=disable", connect=connector)
        self.assertEqual(connector.calls[0][1], {"connect_timeout": 10})

    def test_label_has_host_and_database_but_no_password(self):
        self.assertEqual(describe_database_url(URL), "aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres")
        self.assertEqual(PostgresDatabase(URL, connect=FakeConnector()).label, describe_database_url(URL))

    def test_unreachable_database_never_shows_the_password(self):
        # 連線字串寫錯時 psycopg2 會把整串連線字串放進錯誤訊息
        error = psycopg2.OperationalError(f'invalid dsn: missing "=" after "{URL}" (password s3cr@t)')
        with self.assertRaises(DatabaseUnavailable) as ctx:
            PostgresDatabase(URL, connect=FakeConnector(failures=1, error=error))
        message = str(ctx.exception)
        self.assertNotIn("s3cr%40t", message)
        self.assertNotIn("s3cr@t", message)
        self.assertIn("aws-0-ap-southeast-2.pooler.supabase.com", message)
        self.assertIsNone(ctx.exception.__cause__)

    def test_reconnects_once_after_the_connection_drops(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].broken = True
        self.assertEqual(db.query_all("SELECT doc FROM users WHERE user_id = ?", ("a",)), [])
        self.assertEqual(len(connector.connections), 2)
        self.assertTrue(connector.connections[0].closed)
        self.assertEqual(statements(connector.connections[1]), ["SELECT doc FROM users WHERE user_id = %s"])

    def test_gives_up_when_reconnecting_fails_too(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].broken = True
        connector.failures = 1
        with self.assertRaises(DatabaseUnavailable):
            db.query_all("SELECT 1 WHERE 1 = ?", (1,))


class TransactionTests(unittest.TestCase):
    def test_commits_when_everything_succeeds(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with db.transaction():
            db.execute("UPDATE records SET meal_type = ? WHERE user_id = ?", ("早餐", "a"))
        self.assertEqual(
            statements(connector.connections[0]),
            ["BEGIN", "UPDATE records SET meal_type = %s WHERE user_id = %s", "COMMIT"],
        )

    def test_rolls_back_and_reraises_on_error(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with self.assertRaises(ValueError):
            with db.transaction():
                db.execute("DELETE FROM records WHERE user_id = ?", ("a",))
                raise ValueError("boom")
        self.assertEqual(
            statements(connector.connections[0]),
            ["BEGIN", "DELETE FROM records WHERE user_id = %s", "ROLLBACK"],
        )

    def test_does_not_retry_inside_a_transaction(self):
        # 交易做到一半斷線，重連後只會做到後半段，所以直接丟錯
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with self.assertRaises(psycopg2.OperationalError):
            with db.transaction():
                connector.connections[0].broken = True
                db.execute("DELETE FROM auth_sessions WHERE user_id = ?", ("a",))
        self.assertEqual(len(connector.connections), 1)

    def test_next_query_after_a_failed_transaction_reconnects(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with self.assertRaises(psycopg2.OperationalError):
            with db.transaction():
                connector.connections[0].broken = True
                db.execute("DELETE FROM auth_sessions WHERE user_id = ?", ("a",))
        db.query_all("SELECT 1 WHERE 1 = ?", (1,))
        self.assertEqual(len(connector.connections), 2)


if __name__ == "__main__":
    unittest.main()
