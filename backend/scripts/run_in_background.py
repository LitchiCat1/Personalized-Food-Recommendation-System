"""在背景執行後端，輸出寫到 log 檔。給 Windows 排程工作用：

    pythonw backend/scripts/run_in_background.py

pythonw 沒有視窗，後端印的訊息和錯誤原本會直接消失，所以全部導到
資料庫旁邊的 logs\\backend.log（DATABASE_PATH 所在的資料夾；沒設就是
%LOCALAPPDATA%\\NutriLens\\logs\\backend.log）。
超過 5 MB 就把舊的改名成 backend.log.1 再重新開始，只留一份舊的。
"""

import logging
import os
import runpy
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from repositories.sqlite_db import default_database_path, resolve_database_path  # noqa: E402
from services.env_service import load_local_env  # noqa: E402

MAX_LOG_BYTES = 5 * 1024 * 1024


def log_path() -> str:
    database = resolve_database_path()
    if not database or database == ":memory:":
        database = default_database_path()
    return os.path.join(os.path.dirname(database), "logs", "backend.log")


def open_log(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
        os.replace(path, path + ".1")
    # 一行寫一次，後端當掉時最後幾行也已經在檔案裡
    return open(path, "a", encoding="utf-8", buffering=1)


def main() -> None:
    # 排程工作的環境裡沒有 DATABASE_PATH，要先讀 backend/.env.local 才知道 log 放哪
    load_local_env()
    log = open_log(log_path())
    sys.stdout = sys.stderr = log
    # waitress 用 logging 報錯；沒設 handler 的話只會寫到原本的 stderr，pythonw 底下那是空的
    logging.basicConfig(stream=log, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    print(f"===== {datetime.now().isoformat(timespec='seconds')} 背景啟動 =====")
    os.chdir(BACKEND_DIR)
    sys.argv = [os.path.join(BACKEND_DIR, "app.py")]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
