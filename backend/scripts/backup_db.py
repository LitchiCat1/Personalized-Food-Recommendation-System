"""備份或還原本機的 SQLite 資料庫。

在專案根目錄執行：

    python backend/scripts/backup_db.py                     # 備份（後端開著也可以）
    python backend/scripts/backup_db.py --list              # 列出現有的備份
    python backend/scripts/backup_db.py --restore 備份檔名  # 還原（要先關掉後端）

備份放在資料庫旁邊的 backups 資料夾（預設 %LOCALAPPDATA%\\NutriLens\\backups），
檔名帶日期時間。用 SQLite 自己的備份功能複製：後端開著時剛寫的資料還在 -wal 檔裡，
直接複製 .db 檔會漏掉那些資料，這個方式不會。

還原前先檢查備份檔沒有損毀，再把目前的檔案改名留著（nutrilens.db.before-restore-日期時間），
不會刪掉任何檔案。只處理本機的 SQLite；Render 上的 Supabase 請用 Supabase 後台的備份。
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from repositories.sqlite_db import resolve_database_path  # noqa: E402
from services.env_service import load_local_env  # noqa: E402


class BackupError(Exception):
    pass


def check_database(path: str) -> str:
    """PRAGMA quick_check 的結果：完好是 "ok"，其他就是哪裡壞了。"""
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as error:
        return str(error)
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as error:
        return str(error)
    finally:
        conn.close()


def _stamp(now: datetime | None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def backup_database(source: str, backup_dir: str, now: datetime | None = None) -> str:
    """把 source 完整複製一份到 backup_dir，回傳備份檔的路徑。"""
    # sqlite3.connect 遇到不存在的檔案會建一個空的，所以先檢查
    if not os.path.isfile(source):
        raise BackupError(f"找不到資料庫檔案：{source}")
    os.makedirs(backup_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(source))[0]
    target = os.path.join(backup_dir, f"{name}-{_stamp(now)}.db")

    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    result = check_database(target)
    if result != "ok":
        raise BackupError(f"備份檔檢查沒通過（{result}），原本的資料庫可能已經損毀：{target}")
    return target


def restore_database(backup: str, target: str, now: datetime | None = None) -> str | None:
    """用 backup 取代 target。回傳目前檔案改名後的路徑（沒有目前檔案就回 None）。"""
    if not os.path.isfile(backup):
        raise BackupError(f"找不到備份檔：{backup}")
    result = check_database(backup)
    if result != "ok":
        raise BackupError(f"備份檔有問題（{result}），沒有還原。")

    previous = None
    if os.path.exists(target):
        previous = f"{target}.before-restore-{_stamp(now)}"
        try:
            os.rename(target, previous)
        except PermissionError:
            # Windows 不讓別的程式改名開著的檔案：後端還在用這個資料庫
            raise BackupError("資料庫檔案正在被使用，請先關掉後端再還原。") from None
        # 後端沒有正常關閉時會留下 -wal / -shm，它們屬於舊檔，跟著一起搬走
        for suffix in ("-wal", "-shm"):
            if os.path.exists(target + suffix):
                os.rename(target + suffix, previous + suffix)

    shutil.copy2(backup, target)
    return previous


def _list_backups(backup_dir: str) -> list[str]:
    if not os.path.isdir(backup_dir):
        return []
    return sorted(
        os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if name.endswith(".db")
    )


def main() -> int:
    load_local_env()
    parser = argparse.ArgumentParser(description="備份或還原本機的 SQLite 資料庫")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="列出現有的備份")
    action.add_argument("--restore", metavar="備份檔", help="用這個備份取代目前的資料庫（要先關掉後端）")
    args = parser.parse_args()

    if os.environ.get("DATABASE_URL", "").strip():
        print("設了 DATABASE_URL（Supabase）：這個腳本只處理本機的 SQLite，請用 Supabase 後台的備份。")
        return 1
    database_path = resolve_database_path()
    if not database_path or database_path == ":memory:":
        print("DATABASE_PATH 設成只用記憶體，沒有資料庫檔案可以備份。")
        return 1
    backup_dir = os.path.join(os.path.dirname(database_path), "backups")

    try:
        if args.list:
            backups = _list_backups(backup_dir)
            print(f"備份資料夾：{backup_dir}")
            for path in backups:
                print(f"  {os.path.basename(path)}（{os.path.getsize(path) / 1024:.0f} KB）")
            if not backups:
                print("  （還沒有備份）")
            return 0

        if args.restore:
            backup = args.restore if os.path.isfile(args.restore) else os.path.join(backup_dir, args.restore)
            previous = restore_database(backup, database_path)
            print(f"已用 {backup} 還原 {database_path}")
            if previous:
                print(f"原本的檔案改名留在：{previous}")
            return 0

        target = backup_database(database_path, backup_dir)
        print(f"已備份到：{target}")
        return 0
    except BackupError as error:
        print(error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
