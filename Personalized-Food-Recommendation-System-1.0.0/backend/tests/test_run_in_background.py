"""背景啟動後端（scripts/run_in_background.py）的 log 檔處理。"""

import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "run_in_background.py")
spec = importlib.util.spec_from_file_location("run_in_background", SCRIPT)
run_in_background = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_in_background)


class BackgroundLogTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name

    def test_the_log_sits_next_to_the_default_database(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": self.folder}):
            os.environ.pop("DATABASE_PATH", None)
            self.assertEqual(
                run_in_background.log_path(),
                os.path.join(self.folder, "NutriLens", "logs", "backend.log"),
            )

    def test_the_log_follows_a_configured_database_path(self):
        # 資料庫搬到 AppData 以外時，log 也跟著搬，不要留在會被 Windows 導向的 AppData
        database = os.path.join(self.folder, "NutriLensData", "nutrilens.db")
        with patch.dict(os.environ, {"DATABASE_PATH": database}):
            self.assertEqual(run_in_background.log_path(), os.path.join(self.folder, "NutriLensData", "logs", "backend.log"))

    def test_the_backend_env_file_is_read_before_the_log_path_is_chosen(self):
        # 排程工作的環境裡沒有 DATABASE_PATH，它寫在 backend/.env.local
        with patch.object(run_in_background, "load_local_env") as load, \
             patch.object(run_in_background, "open_log", side_effect=RuntimeError("stop here")):
            with self.assertRaises(RuntimeError):
                run_in_background.main()
        load.assert_called_once()

    def test_a_new_log_folder_is_created_and_lines_are_appended(self):
        path = os.path.join(self.folder, "logs", "backend.log")
        for line in ("第一次啟動", "第二次啟動"):
            log = run_in_background.open_log(path)
            print(line, file=log)
            log.close()
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read().splitlines(), ["第一次啟動", "第二次啟動"])

    def test_an_oversized_log_is_moved_aside_instead_of_growing_forever(self):
        path = os.path.join(self.folder, "backend.log")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x" * (run_in_background.MAX_LOG_BYTES + 1))

        run_in_background.open_log(path).close()

        self.assertEqual(os.path.getsize(path), 0)
        self.assertGreater(os.path.getsize(path + ".1"), run_in_background.MAX_LOG_BYTES)


if __name__ == "__main__":
    unittest.main()
