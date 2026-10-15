"""本機的 SQLite 資料庫：帳號、健康檔案、飲食紀錄、店家菜單都存在同一個檔案。

SQLite 是 Python 內建的，不用另外安裝資料庫伺服器。

整個後端只開一個連線，用鎖排隊。waitress 有 8 個執行緒，而 SQLite 同一時間
只能有一個人寫；排隊比各自開連線再互相等檔案鎖單純，資料量也小到不會慢。
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import sqlite3
import threading


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
        with self._lock:
            # WAL：寫入時讀取不會被擋，斷電時也比較不容易壞檔
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")

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
