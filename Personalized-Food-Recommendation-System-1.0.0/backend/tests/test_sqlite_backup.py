"""後端開著時的自動備份（repositories/sqlite_backup.py）。"""

import contextlib
import io
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from repositories import sqlite_backup
from repositories.sqlite_backup import AutoBackup, auto_backup_from_env, auto_backups, backup_database
from repositories.sqlite_db import SqliteDatabase
from test_api_routes import ApiTestBase

NOON = datetime(2026, 10, 26, 12, 0, 0)


def note_bodies(path):
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT body FROM notes ORDER BY rowid")]
    finally:
        conn.close()


class AutoBackupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.path = os.path.join(self.folder, "nutrilens.db")
        self.backups = os.path.join(self.folder, "backups")
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def _open_database_with(self, *bodies):
        db = SqliteDatabase(self.path)
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE IF NOT EXISTS notes (body TEXT);")
        for body in bodies:
            db.execute("INSERT INTO notes (body) VALUES (?)", (body,))
        return db

    def _auto(self, now=NOON, **options):
        return AutoBackup(self.path, self.backups, clock=lambda: now, **options)

    def _files(self, folder=None):
        return sorted(os.listdir(folder or self.backups))

    def test_a_backup_while_the_backend_is_running_has_everything(self):
        self._open_database_with("早餐", "午餐")
        target = self._auto().run_once()
        self.assertEqual(os.path.basename(target), "nutrilens-auto-20261026-120000.db")
        self.assertEqual(note_bodies(target), ["早餐", "午餐"])

    def test_a_backup_is_one_self_contained_file(self):
        # WAL 模式的檔案連唯讀打開都會在旁邊多出 -wal、-shm；備份要能單獨搬走
        self._open_database_with("早餐")
        target = self._auto().run_once()
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(conn.execute("SELECT body FROM notes").fetchall(), [("早餐",)])
        finally:
            conn.close()
        self.assertEqual(self._files(), [os.path.basename(target)])

    def test_only_the_newest_automatic_backups_are_kept(self):
        self._open_database_with("早餐")
        manual = backup_database(self.path, self.backups, now=NOON - timedelta(days=30))
        before_upgrade = backup_database(self.path, self.backups, now=NOON - timedelta(days=29), label="before-v2")
        for day in range(5):
            self._auto(now=NOON + timedelta(days=day), keep=3).run_once()

        kept = [os.path.basename(path) for _, path in auto_backups(self.path, self.backups)]
        self.assertEqual(kept, [
            "nutrilens-auto-20261028-120000.db",
            "nutrilens-auto-20261029-120000.db",
            "nutrilens-auto-20261030-120000.db",
        ])
        # 手動備份和升級前的備份不會被清掉
        self.assertTrue(os.path.exists(manual))
        self.assertTrue(os.path.exists(before_upgrade))

    def test_two_backups_in_the_same_second_do_not_overwrite_each_other(self):
        self._open_database_with("早餐")
        first = self._auto().run_once()
        second = self._auto().run_once()
        self.assertNotEqual(first, second)
        self.assertEqual(len(auto_backups(self.path, self.backups)), 2)

    def test_the_next_backup_is_due_one_interval_after_the_newest(self):
        self._open_database_with("早餐")
        self.assertEqual(self._auto().seconds_until_due(), 0)
        self._auto().run_once()
        self.assertEqual(self._auto(now=NOON + timedelta(hours=20)).seconds_until_due(), 4 * 3600)
        self.assertEqual(self._auto(now=NOON + timedelta(hours=30)).seconds_until_due(), 0)
        # 電腦時間被往回調：最多只等一個週期
        self.assertEqual(self._auto(now=NOON - timedelta(days=3)).seconds_until_due(), 24 * 3600)

    def test_the_time_comes_from_the_file_name_not_the_modified_time(self):
        # 搬資料夾時檔案的修改時間會變成搬的那一刻（2026-10-25 搬到 NutriLensData 就是這樣）
        self._open_database_with("早餐")
        target = self._auto(now=NOON - timedelta(days=2)).run_once()
        os.utime(target, None)
        self.assertEqual(self._auto().seconds_until_due(), 0)

    def test_a_failed_backup_is_reported_and_leaves_no_half_written_file(self):
        self.assertIsNone(self._auto().run_once())
        self.assertIn("自動備份失敗", self.output.getvalue())
        self.assertFalse(os.path.exists(self.path), "不能為了備份建一個空資料庫")

    def test_a_damaged_database_does_not_produce_a_backup_that_looks_usable(self):
        db = SqliteDatabase(self.path)
        db.executescript("PRAGMA journal_mode=DELETE; CREATE TABLE notes (body TEXT);")
        for index in range(400):
            db.execute("INSERT INTO notes (body) VALUES (?)", (f"note {index} " * 20,))
        db.close()
        with open(self.path, "r+b") as damaged:
            damaged.seek(4096 * 3)
            damaged.write(b"\xff" * 4096)

        self.assertIsNone(self._auto().run_once())
        self.assertIn("損毀", self.output.getvalue())
        self.assertEqual(self._files(), [])

    def test_a_copy_goes_to_the_second_folder_and_a_missing_drive_is_only_a_warning(self):
        self._open_database_with("早餐")
        elsewhere = os.path.join(self.folder, "usb")
        target = self._auto(copy_dir=elsewhere).run_once()
        self.assertEqual(note_bodies(os.path.join(elsewhere, os.path.basename(target))), ["早餐"])

        not_a_folder = os.path.join(self.folder, "a-file")
        with open(not_a_folder, "w", encoding="utf-8") as handle:
            handle.write("x")
        later = self._auto(now=NOON + timedelta(days=1), copy_dir=not_a_folder).run_once()
        self.assertTrue(os.path.exists(later), "本機那份照樣要備好")
        self.assertIn("[WARN]", self.output.getvalue())

    def test_the_background_thread_backs_up_soon_after_starting(self):
        self._open_database_with("早餐")
        auto = AutoBackup(self.path, self.backups)
        auto.start()
        try:
            deadline = time.monotonic() + 10
            while not auto_backups(self.path, self.backups) and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            auto.stop()
        self.assertEqual(len(auto_backups(self.path, self.backups)), 1)

    def test_a_backup_is_taken_when_the_wall_clock_says_so_even_after_sleep(self):
        # Windows 的等待倒數在睡眠時會暫停；一天後要不要備份，要看時鐘，不是看等了多久
        self._open_database_with("早餐")
        now = [NOON]
        auto = AutoBackup(self.path, self.backups, clock=lambda: now[0])
        with patch.object(sqlite_backup, "CHECK_SECONDS", 0.02):
            auto.start()
            try:
                self._wait_for_backups(1)
                now[0] = NOON + timedelta(hours=25)
                self._wait_for_backups(2)
            finally:
                auto.stop()
        self.assertEqual(len(auto_backups(self.path, self.backups)), 2)

    def test_a_failed_backup_is_retried_an_hour_later_not_in_a_tight_loop(self):
        now = [NOON]
        auto = AutoBackup(self.path, self.backups, clock=lambda: now[0])
        with patch.object(sqlite_backup, "CHECK_SECONDS", 0.02), \
                patch.object(auto, "run_once", wraps=auto.run_once) as attempts:
            auto.start()
            try:
                time.sleep(0.3)
                self.assertEqual(attempts.call_count, 1, "資料庫不存在：試一次就等")
                now[0] = NOON + timedelta(hours=1, seconds=1)
                deadline = time.monotonic() + 5
                while attempts.call_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.02)
            finally:
                auto.stop()
        self.assertEqual(attempts.call_count, 2)

    def _wait_for_backups(self, count):
        deadline = time.monotonic() + 10
        while len(auto_backups(self.path, self.backups)) < count and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(auto_backups(self.path, self.backups)), count)


class AutoBackupSettingsTests(unittest.TestCase):
    PATH = os.path.join(tempfile.gettempdir(), "data", "nutrilens.db")

    def settings(self, **environ):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            auto = auto_backup_from_env(self.PATH, environ)
        return auto, output.getvalue()

    def test_defaults_are_daily_and_thirty_copies_next_to_the_database(self):
        auto, _ = self.settings()
        self.assertEqual(auto.interval, timedelta(hours=24))
        self.assertEqual(auto.keep, 30)
        self.assertEqual(auto.backup_dir, os.path.join(os.path.dirname(self.PATH), "backups"))
        self.assertIsNone(auto.copy_dir)

    def test_zero_hours_turns_it_off(self):
        for value in ("0", "0.0", "-5"):
            with self.subTest(value=value):
                self.assertIsNone(self.settings(AUTO_BACKUP_HOURS=value)[0])

    def test_bad_values_fall_back_with_a_warning(self):
        auto, output = self.settings(AUTO_BACKUP_HOURS="每天", AUTO_BACKUP_KEEP="0")
        self.assertEqual(auto.interval, timedelta(hours=24))
        self.assertEqual(auto.keep, 1)
        self.assertIn("AUTO_BACKUP_HOURS", output)
        # 太密的話一天就是幾百份
        self.assertEqual(self.settings(AUTO_BACKUP_HOURS="0.01")[0].interval, timedelta(hours=1))

    def test_the_copy_folder_is_made_absolute(self):
        auto, _ = self.settings(AUTO_BACKUP_COPY_DIR="  ~/NutriLensBackups  ")
        self.assertEqual(auto.copy_dir, os.path.abspath(os.path.expanduser("~/NutriLensBackups")))


class BackendStartsAutoBackupTests(ApiTestBase):
    def test_memory_only_and_postgres_have_nothing_to_back_up(self):
        for path in (None, ":memory:"):
            with self.subTest(path=path), patch.object(self.app_module, "database_path", path):
                self.assertIsNone(self.app_module.start_auto_backup())

    def test_a_local_database_file_is_backed_up_in_the_background(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrilens.db")
            SqliteDatabase(path).close()
            output = io.StringIO()
            with patch.object(self.app_module, "database_path", path), \
                    patch.dict(os.environ, {"AUTO_BACKUP_HOURS": "24"}), \
                    contextlib.redirect_stdout(output):
                auto = self.app_module.start_auto_backup()
                try:
                    deadline = time.monotonic() + 10
                    while not auto_backups(path, auto.backup_dir) and time.monotonic() < deadline:
                        time.sleep(0.05)
                finally:
                    auto.stop()
            self.assertEqual(len(auto_backups(path, auto.backup_dir)), 1)
            self.assertIn("自動備份：每 24 小時一次", output.getvalue())

    def test_it_can_be_turned_off(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(self.app_module, "database_path", os.path.join(folder, "nutrilens.db")), \
                patch.dict(os.environ, {"AUTO_BACKUP_HOURS": "0"}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(self.app_module.start_auto_backup())
        self.assertIn("自動備份已關閉", output.getvalue())


if __name__ == "__main__":
    unittest.main()
