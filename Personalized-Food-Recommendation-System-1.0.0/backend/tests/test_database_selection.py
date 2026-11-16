"""SQLite-only database selection and startup safety tests."""

import contextlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from repositories.database import DatabaseUnavailable, open_database
from repositories.sqlite_db import SqliteDatabase

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OpenDatabaseTests(unittest.TestCase):
    def test_without_database_url_uses_sqlite(self):
        with patch.dict(os.environ, {"DATABASE_PATH": ":memory:"}, clear=True):
            db, label = open_database()
        self.assertIsInstance(db, SqliteDatabase)
        self.assertEqual(label, "SQLite :memory:")
        db.close()

    def test_database_url_is_rejected_without_echoing_secrets(self):
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://private-user:private-password@example.invalid/app",
            "DATABASE_PATH": "",
        }, clear=True):
            with self.assertRaises(DatabaseUnavailable) as ctx:
                open_database()
        self.assertIn("僅支援 SQLite", str(ctx.exception))
        self.assertNotIn("private-password", str(ctx.exception))

    def test_blank_database_url_is_ignored(self):
        with patch.dict(os.environ, {"DATABASE_URL": "   ", "DATABASE_PATH": ""}, clear=True):
            self.assertEqual(open_database(), (None, "memory"))

    def test_sqlite_works_without_the_legacy_postgres_driver(self):
        code = (
            "import sys\n"
            "sys.modules['psycopg2'] = None\n"
            "from repositories.database import open_database\n"
            "db, label = open_database()\n"
            "print('selected', db.dialect, label)\n"
            "import app\n"
            "print('app imported')\n"
        )
        env = {
            **os.environ,
            "DATABASE_PATH": ":memory:",
            "NUTRILENS_SKIP_LOCAL_ENV": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env.pop("DATABASE_URL", None)
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("selected sqlite SQLite :memory:", result.stdout)
        self.assertIn("app imported", result.stdout)


class AppStartupTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("app", None)

    def test_app_rejects_database_url_before_creating_sqlite_file(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "must-not-be-created.db")
            env = {
                "DATABASE_URL": "postgresql://private-user:private-password@example.invalid/app",
                "DATABASE_PATH": path,
                "NUTRILENS_SKIP_LOCAL_ENV": "1",
            }
            with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(output):
                sys.modules.pop("app", None)
                with self.assertRaises(SystemExit) as ctx:
                    importlib.import_module("app")
            self.assertFalse(os.path.exists(path))
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("僅支援 SQLite", output.getvalue())
        self.assertNotIn("private-password", output.getvalue())

    def _start_app_with_sqlite_file(self, path):
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_PATH": path, "NUTRILENS_SKIP_LOCAL_ENV": "1"}, clear=True), \
                contextlib.redirect_stdout(output):
            sys.modules.pop("app", None)
            with self.assertRaises(SystemExit) as ctx:
                importlib.import_module("app")
        return ctx.exception.code, output.getvalue()

    def test_app_refuses_to_start_when_the_sqlite_file_is_not_a_database(self):
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
                    patch.dict(os.environ, {"DATABASE_PATH": path, "NUTRILENS_SKIP_LOCAL_ENV": "1"}, clear=True), \
                    contextlib.redirect_stdout(output):
                sys.modules.pop("app", None)
                with self.assertRaises(SystemExit) as ctx:
                    importlib.import_module("app")
            self.assertFalse(os.path.exists(path), "不能先建一個空資料庫")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("DATABASE_PATH", output.getvalue())

    def test_an_explicitly_empty_path_still_means_memory_only(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_PATH": "", "NUTRILENS_SKIP_LOCAL_ENV": "1"}, clear=True), \
                contextlib.redirect_stdout(output):
            sys.modules.pop("app", None)
            app_module = importlib.import_module("app")
        self.assertIsNone(app_module.sql_db)


if __name__ == "__main__":
    unittest.main()
