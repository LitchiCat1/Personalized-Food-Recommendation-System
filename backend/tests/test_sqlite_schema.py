"""本機 SQLite 的結構版本號與升級步驟（repositories/sqlite_schema.py）。"""

import contextlib
import importlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from repositories.sqlite_db import SqliteDatabase
from repositories.sqlite_schema import SCHEMA_VERSION, SchemaVersionError, upgrade_schema


def add_note_column(sql):
    sql.execute("ALTER TABLE records ADD COLUMN note TEXT")


def add_note_index(sql):
    sql.execute("CREATE INDEX idx_records_note ON records (note)")


def must_not_run(sql):
    raise AssertionError("剛建的空資料庫已經是最新結構，不該再升級")


class SchemaUpgradeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "nutrilens.db")
        self.backups = []

    def _open(self):
        db = SqliteDatabase(self.path)
        self.addCleanup(db.close)
        return db

    def _version_one_database(self, version=0):
        """加上版本號之前的資料庫：有資料表、有資料，user_version 還是 0。"""
        db = SqliteDatabase(self.path)
        db.executescript("CREATE TABLE records (id INTEGER PRIMARY KEY, foods TEXT);")
        db.execute("INSERT INTO records (foods) VALUES ('雞腿便當')")
        db.set_user_version(version)
        db.close()

    def _upgrade(self, db, latest, migrations):
        return upgrade_schema(db, backup=self.backups.append, latest=latest, migrations=migrations)

    def test_a_new_database_starts_at_the_latest_version_without_upgrading(self):
        db = self._open()
        self.assertTrue(db.was_empty)
        db.executescript("CREATE TABLE records (id INTEGER PRIMARY KEY, foods TEXT, note TEXT);")
        self.assertEqual(self._upgrade(db, 3, {2: must_not_run, 3: must_not_run}), [])
        self.assertEqual(db.user_version(), 3)
        self.assertEqual(self.backups, [])

    def test_a_database_from_before_version_numbers_counts_as_version_one(self):
        self._version_one_database()
        db = self._open()
        self.assertFalse(db.was_empty)
        self.assertEqual(self._upgrade(db, 1, {}), [])
        self.assertEqual(db.user_version(), 1)
        self.assertEqual(self.backups, [], "沒有要改結構就不用備份")

    def test_an_old_database_is_backed_up_then_upgraded_one_version_at_a_time(self):
        self._version_one_database()
        db = self._open()
        upgraded = self._upgrade(db, 3, {2: add_note_column, 3: add_note_index})
        self.assertEqual(upgraded, [2, 3])
        self.assertEqual(db.user_version(), 3)
        self.assertIn("note", db.column_names("records"))
        self.assertEqual(self.backups, ["before-v3"])
        self.assertEqual(db.query_one("SELECT foods FROM records")["foods"], "雞腿便當")

    def test_a_failed_step_is_rolled_back_and_the_version_stays_at_the_last_good_one(self):
        self._version_one_database()

        def half_done(sql):
            sql.execute("ALTER TABLE records ADD COLUMN extra TEXT")
            raise sqlite3.OperationalError("磁碟滿了")

        db = self._open()
        with self.assertRaises(sqlite3.OperationalError):
            self._upgrade(db, 3, {2: add_note_column, 3: half_done})
        self.assertEqual(db.user_version(), 2)
        self.assertIn("note", db.column_names("records"))
        self.assertNotIn("extra", db.column_names("records"))

    def test_no_upgrade_happens_when_the_backup_fails(self):
        self._version_one_database()

        def broken_backup(label):
            raise OSError("硬碟滿了")

        db = self._open()
        with self.assertRaises(OSError):
            upgrade_schema(db, backup=broken_backup, latest=2, migrations={2: add_note_column})
        self.assertNotIn("note", db.column_names("records"))
        self.assertEqual(db.user_version(), 1)

    def test_a_missing_step_is_caught_before_anything_changes(self):
        self._version_one_database()
        db = self._open()
        with self.assertRaises(SchemaVersionError):
            self._upgrade(db, 3, {2: add_note_column})
        self.assertNotIn("note", db.column_names("records"))
        self.assertEqual(self.backups, [])

    def test_a_database_newer_than_the_program_is_refused(self):
        self._version_one_database(version=SCHEMA_VERSION + 1)
        db = self._open()
        with self.assertRaises(SchemaVersionError) as ctx:
            upgrade_schema(db)
        self.assertIn("git pull", str(ctx.exception))
        self.assertEqual(db.user_version(), SCHEMA_VERSION + 1)


class AppStartupSchemaTests(unittest.TestCase):
    def _import_app(self, path):
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_PATH": path, "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                contextlib.redirect_stdout(output):
            os.environ.pop("DATABASE_URL", None)
            sys.modules.pop("app", None)
            module = importlib.import_module("app")
        self.addCleanup(module.sql_db.close)
        return module, output.getvalue()

    def test_the_backend_stamps_the_current_version_on_its_database(self):
        with tempfile.TemporaryDirectory() as folder:
            module, _ = self._import_app(os.path.join(folder, "nutrilens.db"))
            self.assertEqual(module.sql_db.user_version(), SCHEMA_VERSION)
            module.sql_db.close()

    def test_the_backend_will_not_start_on_a_newer_database_and_creates_no_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrilens.db")
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE future_records (id INTEGER PRIMARY KEY)")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
            conn.commit()
            conn.close()

            output = io.StringIO()
            with patch.dict(os.environ, {"DATABASE_PATH": path, "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                    contextlib.redirect_stdout(output):
                os.environ.pop("DATABASE_URL", None)
                sys.modules.pop("app", None)
                with self.assertRaises(SystemExit) as ctx:
                    importlib.import_module("app")
            self.assertEqual(ctx.exception.code, 1)
            self.assertIn(f"第 {SCHEMA_VERSION + 1} 版", output.getvalue())
            conn = sqlite3.connect(path)
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            conn.close()
        self.assertEqual(tables, ["future_records"])


if __name__ == "__main__":
    unittest.main()
