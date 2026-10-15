"""選資料庫、Postgres 建表、設了 DATABASE_URL 卻連不上時的行為。"""

import contextlib
import importlib
import io
import os
import sys
import unittest
from unittest.mock import patch

import psycopg2

from repositories.auth_repository import AuthRepository
from repositories.database import DatabaseUnavailable, open_database
from repositories.postgres_db import PostgresDatabase
from repositories.sqlite_db import SqliteDatabase
from repositories.storage import StorageRepository
from test_postgres_db import URL, FakeConnector

STORAGE_TABLES = ("users", "records", "custom_foods", "restaurant_menus", "restaurant_menu_failures")


class RecordingDatabase:
    """只記下建表語法的假資料庫。"""

    dialect = "postgres"

    def __init__(self):
        self.scripts = []

    def executescript(self, sql):
        self.scripts.append(sql)


class PostgresTableTests(unittest.TestCase):
    def test_storage_tables_match_supabase_types_and_enable_rls(self):
        db = RecordingDatabase()
        StorageRepository(None, False, {}, [], [], sql=db)
        script = "\n".join(db.scripts)
        self.assertIn("JSONB", script)
        self.assertIn("BIGSERIAL", script)
        self.assertIn("TIMESTAMPTZ", script)
        self.assertNotIn("AUTOINCREMENT", script)
        for table in STORAGE_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", script)
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;", script)

    def test_auth_tables_enable_rls_so_the_public_api_cannot_read_hashes(self):
        db = RecordingDatabase()
        AuthRepository(db)
        script = "\n".join(db.scripts)
        self.assertIn("expires_at TIMESTAMPTZ NOT NULL", script)
        for table in ("auth_users", "auth_sessions"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", script)
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;", script)


class OpenDatabaseTests(unittest.TestCase):
    def test_database_url_selects_postgres(self):
        with patch.dict(os.environ, {"DATABASE_URL": URL, "DATABASE_PATH": ""}, clear=True):
            db, label = open_database(connect=FakeConnector())
        self.assertIsInstance(db, PostgresDatabase)
        self.assertEqual(label, "Postgres aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres")

    def test_without_database_url_uses_sqlite(self):
        with patch.dict(os.environ, {"DATABASE_PATH": ":memory:"}, clear=True):
            db, label = open_database()
        self.assertIsInstance(db, SqliteDatabase)
        self.assertEqual(label, "SQLite :memory:")

    def test_blank_database_url_is_ignored(self):
        with patch.dict(os.environ, {"DATABASE_URL": "   ", "DATABASE_PATH": ""}, clear=True):
            self.assertEqual(open_database(), (None, "memory"))

    def test_unreachable_postgres_raises_instead_of_falling_back(self):
        with patch.dict(os.environ, {"DATABASE_URL": URL}, clear=True):
            with self.assertRaises(DatabaseUnavailable):
                open_database(connect=FakeConnector(failures=1))


class AppStartupTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("app", None)

    def test_app_refuses_to_start_when_database_url_is_unreachable(self):
        output = io.StringIO()
        failure = psycopg2.OperationalError(f'invalid dsn: "{URL}"')
        with patch.dict(os.environ, {"DATABASE_URL": URL, "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                patch("repositories.postgres_db.psycopg2.connect", side_effect=failure), \
                contextlib.redirect_stdout(output):
            sys.modules.pop("app", None)
            with self.assertRaises(SystemExit) as ctx:
                importlib.import_module("app")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("pooler.supabase.com", output.getvalue())
        self.assertNotIn("s3cr", output.getvalue())


if __name__ == "__main__":
    unittest.main()
