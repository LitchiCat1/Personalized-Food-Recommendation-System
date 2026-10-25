"""本機 SQLite 的備份與還原（scripts/backup_db.py）。"""

import importlib.util
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from repositories.sqlite_db import SqliteDatabase

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "backup_db.py")
spec = importlib.util.spec_from_file_location("backup_db", SCRIPT)
backup_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_db)


def note_bodies(path):
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT body FROM notes ORDER BY rowid")]
    finally:
        conn.close()


class BackupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.path = os.path.join(self.folder, "nutrilens.db")
        self.backups = os.path.join(self.folder, "backups")

    def _database_with(self, *bodies):
        db = SqliteDatabase(self.path)
        db.executescript("CREATE TABLE IF NOT EXISTS notes (body TEXT);")
        for body in bodies:
            db.execute("INSERT INTO notes (body) VALUES (?)", (body,))
        return db

    def test_a_backup_taken_while_the_backend_is_running_has_everything(self):
        # 後端開著時，剛寫的資料還在 -wal 檔裡；直接複製 .db 會漏掉，用 SQLite 的備份功能不會
        db = self._database_with("早餐", "午餐")
        try:
            self.assertGreater(os.path.getsize(self.path + "-wal"), 0, "測試前提：資料還在 -wal 檔裡")
            target = backup_db.backup_database(self.path, self.backups, now=datetime(2026, 10, 25, 9, 30))
        finally:
            db.close()

        self.assertEqual(os.path.basename(target), "nutrilens-20261025-093000.db")
        self.assertEqual(note_bodies(target), ["早餐", "午餐"])
        self.assertEqual(backup_db.check_database(target), "ok")

    def test_restoring_brings_back_the_backup_and_keeps_the_current_file(self):
        self._database_with("早餐").close()
        target = backup_db.backup_database(self.path, self.backups)
        db = self._database_with("晚餐")
        db.close()

        previous = backup_db.restore_database(target, self.path, now=datetime(2026, 10, 25, 10, 0))

        self.assertEqual(note_bodies(self.path), ["早餐"])
        self.assertEqual(previous, f"{self.path}.before-restore-20261025-100000")
        self.assertEqual(note_bodies(previous), ["早餐", "晚餐"])

    def test_a_damaged_backup_is_not_restored(self):
        self._database_with("早餐").close()
        broken = os.path.join(self.folder, "broken.db")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("not a database " * 100)

        with self.assertRaises(backup_db.BackupError):
            backup_db.restore_database(broken, self.path)
        self.assertEqual(note_bodies(self.path), ["早餐"])

    def test_backing_up_a_missing_file_does_not_create_an_empty_one(self):
        with self.assertRaises(backup_db.BackupError):
            backup_db.backup_database(self.path, self.backups)
        self.assertFalse(os.path.exists(self.path))

    @unittest.skipUnless(os.name == "nt", "只有 Windows 會擋下改名開著的檔案")
    def test_restoring_while_the_backend_is_running_is_refused(self):
        self._database_with("早餐").close()
        target = backup_db.backup_database(self.path, self.backups)
        db = self._database_with("晚餐")
        try:
            with self.assertRaises(backup_db.BackupError) as ctx:
                backup_db.restore_database(target, self.path)
        finally:
            db.close()
        self.assertIn("關掉後端", str(ctx.exception))
        self.assertEqual(note_bodies(self.path), ["早餐", "晚餐"])


if __name__ == "__main__":
    unittest.main()
