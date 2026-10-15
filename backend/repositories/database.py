"""後端要用哪個資料庫。

- 有設 DATABASE_URL（Render）：Supabase 的 Postgres。
- 沒設（本機）：SQLite 檔，位置見 sqlite_db.py；DATABASE_PATH 設成空字串就不用資料庫。

app.py 和 scripts/reset_password.py 共用這裡，兩邊選到的一定是同一個。

這個檔案刻意不在開頭 import psycopg2：本機只用 SQLite，pull 之後還沒重裝套件
（沒有 psycopg2）也要能照常啟動。
"""

import os

from repositories.sqlite_db import SqliteDatabase, resolve_database_path

__all__ = ["DatabaseUnavailable", "MALFORMED_URL_MESSAGE", "open_database"]

MALFORMED_URL_MESSAGE = (
    "DATABASE_URL 的格式不對：請到 Supabase 重新複製 Session pooler 的連線字串"
    "（密碼裡的特殊字元要經過網址編碼）。"
)


class DatabaseUnavailable(Exception):
    """設了 DATABASE_URL 卻用不了（格式不對、沒裝 psycopg2 或連不上）。訊息裡不會有密碼。"""


def open_database(connect=None, sleep=None):
    """回傳 (資料庫物件或 None, 說明文字)。說明文字給啟動訊息用，不含密碼。

    設了 DATABASE_URL 卻用不了時丟 DatabaseUnavailable，不退回別的資料庫：
    退回記憶體的話一切看起來正常，資料其實沒存。
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        try:
            from repositories.postgres_db import PostgresDatabase
        except ImportError:
            raise DatabaseUnavailable(
                "設了 DATABASE_URL，但沒有安裝 psycopg2：請先執行 pip install -r backend/requirements.txt。"
            ) from None
        try:
            db = PostgresDatabase(url, connect=connect, sleep=sleep)
        except DatabaseUnavailable:
            raise
        except Exception:
            # 網址本身拆不開時 Python 的錯誤訊息會夾著密碼的片段，所以不印原本的訊息；
            # 也不能往外丟成別的例外，不然 app.py 會當成 SQLite 出錯、退回記憶體照常啟動。
            raise DatabaseUnavailable(MALFORMED_URL_MESSAGE) from None
        return db, f"Postgres {db.label}"
    path = resolve_database_path()
    if not path:
        return None, "memory"
    return SqliteDatabase(path), f"SQLite {path}"
