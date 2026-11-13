"""選資料庫、Postgres 建表、設了 DATABASE_URL 卻連不上時的行為。"""

import contextlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import psycopg2

from repositories.auth_repository import AuthRepository
from repositories.database import DatabaseUnavailable, open_database
from repositories.postgres_db import PostgresDatabase
from repositories.sqlite_db import SqliteDatabase
from repositories.storage import StorageRepository
from test_postgres_db import URL, FakeConnector

# 密碼是 pa/ss，/ 沒有編碼成 %2F，網址就拆錯了
MALFORMED_URL = "postgresql://postgres.abc:pa/ss@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STORAGE_TABLES = ("users", "records", "custom_foods", "restaurant_menus", "restaurant_menu_failures")


class RecordingDatabase:
    """只記下建表語法的假資料庫。"""

    dialect = "postgres"

    def __init__(self):
        self.scripts = []

    def executescript(self, sql):
        self.scripts.append(sql)

    def query_all(self, sql, params=()):
        # 啟動時檢查 records 的唯一索引；假資料庫照建表語法回答「有」
        return [{"columns": ["user_id", "client_record_id"]}]


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
                open_database(connect=FakeConnector(failures=3), sleep=lambda seconds: None)

    def test_local_sqlite_works_without_psycopg2_installed(self):
        # 本機只用 SQLite：pull 之後還沒重裝套件（沒有 psycopg2）也要能照常啟動
        code = (
            "import sys\n"
            "sys.modules['psycopg2'] = None\n"
            "from repositories.database import open_database\n"
            "db, label = open_database()\n"
            "print('selected', db.dialect, label)\n"
            "import app\n"
            "print('app imported')\n"
        )
        env = {**os.environ, "DATABASE_PATH": ":memory:", "NUTRILENS_SKIP_LOCAL_ENV": "1", "PYTHONIOENCODING": "utf-8"}
        env.pop("DATABASE_URL", None)
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("selected sqlite SQLite :memory:", result.stdout)
        self.assertIn("app imported", result.stdout)

    def test_malformed_url_raises_without_echoing_the_password(self):
        # 密碼裡有沒編碼的 /：網址拆不開，Python 的錯誤訊息會夾著密碼的片段
        with patch.dict(os.environ, {"DATABASE_URL": MALFORMED_URL}, clear=True):
            with self.assertRaises(DatabaseUnavailable) as ctx:
                open_database(connect=FakeConnector())
        self.assertNotIn("pa/ss", str(ctx.exception))
        self.assertNotIn("pa", str(ctx.exception).replace("Supabase", ""))
        self.assertIsNone(ctx.exception.__cause__)


class AppStartupTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("app", None)

    def test_app_refuses_to_start_when_database_url_is_unreachable(self):
        output = io.StringIO()
        failure = psycopg2.OperationalError(f'invalid dsn: "{URL}"')
        with patch.dict(os.environ, {"DATABASE_URL": URL, "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                patch("repositories.postgres_db.psycopg2.connect", side_effect=failure), \
                patch("repositories.postgres_db.time.sleep"), \
                contextlib.redirect_stdout(output):
            sys.modules.pop("app", None)
            with self.assertRaises(SystemExit) as ctx:
                importlib.import_module("app")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("pooler.supabase.com", output.getvalue())
        self.assertNotIn("s3cr", output.getvalue())

    def test_app_refuses_to_start_when_database_url_is_malformed(self):
        # 先前會掉進「SQLite unavailable」的 except，退回記憶體照常啟動，還印出密碼片段
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_URL": MALFORMED_URL, "NUTRILENS_SKIP_LOCAL_ENV": "1"}),                 patch("repositories.postgres_db.psycopg2.connect") as connect,                 contextlib.redirect_stdout(output):
            sys.modules.pop("app", None)
            with self.assertRaises(SystemExit) as ctx:
                importlib.import_module("app")
        self.assertEqual(ctx.exception.code, 1)
        self.assertNotIn("pa/ss", output.getvalue())
        connect.assert_not_called()

    def _start_app_with_sqlite_file(self, path):
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_PATH": path, "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                contextlib.redirect_stdout(output):
            os.environ.pop("DATABASE_URL", None)
            sys.modules.pop("app", None)
            with self.assertRaises(SystemExit) as ctx:
                importlib.import_module("app")
        return ctx.exception.code, output.getvalue()

    def test_app_refuses_to_start_when_the_sqlite_file_is_not_a_database(self):
        # 先前印一行 WARN 就退回記憶體照常啟動：註冊、記錄看起來都正常，重開後全部消失
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrilens.db")
            with open(path, "w", encoding="utf-8") as broken:
                broken.write("this is not a sqlite database " * 200)
            code, output = self._start_app_with_sqlite_file(path)
        self.assertEqual(code, 1)
        self.assertIn(path, output)
        self.assertIn("備份", output)
        self.assertNotIn("in-memory storage", output)

    def test_app_refuses_to_start_when_the_sqlite_file_is_damaged_inside(self):
        # 檔頭完好、中間的資料頁壞掉：連得上，查到那一頁才會出錯，要在啟動時就發現
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrilens.db")
            db = SqliteDatabase(path)
            db.executescript("PRAGMA journal_mode=DELETE; CREATE TABLE notes (body TEXT);")
            for index in range(400):
                db.execute("INSERT INTO notes (body) VALUES (?)", (f"note {index} " * 20,))
            db.close()
            with open(path, "r+b") as damaged:
                damaged.seek(4096 * 3)
                damaged.write(b"\xff" * 4096)
            code, output = self._start_app_with_sqlite_file(path)
        self.assertEqual(code, 1)
        self.assertIn(path, output)

    def test_app_refuses_to_start_on_a_virtualized_appdata_database(self):
        from repositories import sqlite_db

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrilens.db")
            with patch.object(sqlite_db, "virtualized_appdata_problem", return_value="兩邊各用一個資料庫，請設 DATABASE_PATH"), \
                    patch.dict(os.environ, {"DATABASE_PATH": path, "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                    contextlib.redirect_stdout(output):
                os.environ.pop("DATABASE_URL", None)
                sys.modules.pop("app", None)
                with self.assertRaises(SystemExit) as ctx:
                    importlib.import_module("app")
            self.assertFalse(os.path.exists(path), "不能先建一個空資料庫")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("DATABASE_PATH", output.getvalue())

    def test_an_explicitly_empty_path_still_means_memory_only(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_PATH": "", "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                contextlib.redirect_stdout(output):
            os.environ.pop("DATABASE_URL", None)
            sys.modules.pop("app", None)
            app_module = importlib.import_module("app")
        self.assertIsNone(app_module.sql_db)


if __name__ == "__main__":
    unittest.main()
