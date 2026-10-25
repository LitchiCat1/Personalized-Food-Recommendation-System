"""本機的 SQLite 資料庫：帳號、健康檔案、飲食紀錄、店家菜單都存在同一個檔案。

SQLite 是 Python 內建的，不用另外安裝資料庫伺服器。

整個後端只開一個連線，用鎖排隊。waitress 有 8 個執行緒，而 SQLite 同一時間
只能有一個人寫；排隊比各自開連線再互相等檔案鎖單純，資料量也小到不會慢。
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import glob
import json
import os
import sqlite3
import tempfile
import threading

# GetCurrentPackageFullName 在程式沒有套件身分時回這個錯誤碼
_APPMODEL_ERROR_NO_PACKAGE = 15700


def default_database_path() -> str:
    # 不放在專案資料夾：專案在 OneDrive 裡，同步中的 SQLite 檔可能被鎖住或寫壞
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "NutriLens", "nutrilens.db")


def resolve_database_path() -> str | None:
    """沒設 DATABASE_PATH 就用預設位置；設成空字串表示不用資料庫（只存記憶體）。"""
    configured = os.environ.get("DATABASE_PATH")
    if configured is None:
        return default_database_path()
    configured = configured.strip()
    if not configured:
        return None
    if configured == ":memory:":
        return configured
    return os.path.abspath(os.path.expanduser(os.path.expandvars(configured)))


def running_in_windows_package() -> bool:
    """這個程式是不是在 Windows 的 MSIX 套件裡執行（例如從 Claude 桌面版啟動的）。"""
    if os.name != "nt":
        return False
    try:
        import ctypes

        length = ctypes.c_uint32(0)
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != _APPMODEL_ERROR_NO_PACKAGE
    except (AttributeError, OSError):
        return False


def _is_under(path: str, folder: str | None) -> bool:
    if not folder:
        return False
    path = os.path.normcase(os.path.abspath(path))
    folder = os.path.normcase(os.path.abspath(folder)).rstrip("\\/")
    return path == folder or path.startswith(folder + os.sep)


def _redirected_copies(path: str) -> list[str]:
    """%LOCALAPPDATA%\\Packages\\*\\LocalCache 底下，這個資料庫資料夾的導向副本。"""
    folder = os.path.dirname(path)
    local = os.environ.get("LOCALAPPDATA")
    copies = []
    for env_name, cache_name in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming")):
        root = os.environ.get(env_name)
        if local and _is_under(folder, root):
            relative = os.path.relpath(folder, root)
            copies += glob.glob(os.path.join(local, "Packages", "*", "LocalCache", cache_name, relative))
    return copies


def virtualized_appdata_problem(path: str | None) -> str | None:
    """資料庫會不會被 Windows 分成兩份；會的話回說明，不會回 None。

    MSIX 套件（例如 Claude 桌面版）啟動的程式寫 AppData 時，Windows 會把檔案導到
    %LOCALAPPDATA%\\Packages\\<套件>\\LocalCache；工作排程器或一般終端機啟動的程式看到
    的是真正的 AppData。2026-10-25 就這樣變成兩個資料庫：排程工作的後端建了一個空的，
    之後從 Claude 執行的備份又把空的那份寫回有資料的那份。

    從 Claude 啟動的程式不一定查得到自己的套件身分，所以也直接找導向副本：
    兩邊都看得到 Packages 資料夾，有副本就代表這個位置已經被拆成兩份。
    """
    if not path or path == ":memory:":
        return None
    # 暫存資料夾不會被導向，測試開在那裡的資料庫用完就刪
    if _is_under(path, tempfile.gettempdir()):
        return None
    if not any(_is_under(path, os.environ.get(name)) for name in ("LOCALAPPDATA", "APPDATA")):
        return None
    copies = _redirected_copies(path)
    if not copies and not running_in_windows_package():
        return None
    where = f"（導向副本：{copies[0]}）" if copies else ""
    return (
        f"資料庫 {path} 在 AppData 底下，而 Windows 會把 MSIX 套件（例如 Claude 桌面版）啟動的程式"
        f"寫進 AppData 的檔案導到套件自己的資料夾{where}：從 Claude 啟動的後端和工作排程器或一般"
        "終端機啟動的後端看到的是不同的資料庫，兩邊的資料會分開，甚至互相覆蓋。請在 backend/.env.local "
        r"把 DATABASE_PATH 設到 AppData 以外，例如 C:\Users\<你的帳號>\NutriLensData\nutrilens.db。"
    )


def utc_iso(moment: datetime | None = None) -> str:
    """固定寬度的 UTC 時間字串。

    SQLite 沒有時間型別，時間存成字串、用字串比大小。isoformat() 在微秒剛好
    是 0 時會少印一段，長度不一就比不準，所以自己固定格式。
    """
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def from_json(text):
    """SQLite 存的是 JSON 字串；Postgres 的 jsonb 讀回來已經是 dict / list，原樣回傳。"""
    if text is None or text == "":
        return None
    if not isinstance(text, (str, bytes, bytearray)):
        return text
    return json.loads(text)


class SqliteDatabase:
    dialect = "sqlite"

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.RLock()
        # isolation_level=None：每句自己提交，要多句一起成功時用 transaction()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10)
        self._conn.row_factory = sqlite3.Row
        try:
            with self._lock:
                # WAL：寫入時讀取不會被擋，斷電時也比較不容易壞檔
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA foreign_keys=ON")
                # 檔頭完好、中間的資料頁壞掉時，連線照樣成功，要等查到那一頁才出錯。
                # 開檔時整份檢查一次（資料量小，不到一秒），壞了就不要開始收資料。
                result = self._conn.execute("PRAGMA quick_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(f"資料庫檔案損毀：{result}")
        except Exception:
            # 不關的話檔案一直被鎖著，連要搬走或還原都不行
            self._conn.close()
            raise

    def execute(self, sql: str, params=()) -> int:
        """回傳受影響的筆數。"""
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)

    def query_one(self, sql: str, params=()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def query_all(self, sql: str, params=()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def column_names(self, table: str) -> list[str]:
        with self._lock:
            return [row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()]

    @contextmanager
    def transaction(self):
        """裡面的每一句要嘛全部成功、要嘛全部不算。"""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
