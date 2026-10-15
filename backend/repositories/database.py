"""後端要用哪個資料庫。

- 有設 DATABASE_URL（Render）：Supabase 的 Postgres。
- 沒設（本機）：SQLite 檔，位置見 sqlite_db.py；DATABASE_PATH 設成空字串就不用資料庫。

app.py 和 scripts/reset_password.py 共用這裡，兩邊選到的一定是同一個。
"""

import os

from repositories.postgres_db import DatabaseUnavailable, PostgresDatabase
from repositories.sqlite_db import SqliteDatabase, resolve_database_path

__all__ = ["DatabaseUnavailable", "open_database"]


def open_database(connect=None):
    """回傳 (資料庫物件或 None, 說明文字)。說明文字給啟動訊息用，不含密碼。

    設了 DATABASE_URL 卻連不上時丟 DatabaseUnavailable，不退回別的資料庫：
    退回記憶體的話一切看起來正常，資料其實沒存。
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        try:
            db = PostgresDatabase(url, connect=connect)
        except DatabaseUnavailable:
            raise
        except Exception:
            # 網址本身拆不開（例如密碼裡有沒編碼的 / 或 #）。Python 的錯誤訊息會夾著
            # 密碼的片段，所以不印原本的訊息；也不能往外丟成別的例外，不然 app.py 會
            # 當成 SQLite 出錯、退回記憶體照常啟動。
            raise DatabaseUnavailable(
                "DATABASE_URL 的格式不對：請到 Supabase 重新複製 Session pooler 的連線字串"
                "（密碼裡的特殊字元要經過網址編碼）。"
            ) from None
        return db, f"Postgres {db.label}"
    path = resolve_database_path()
    if not path:
        return None, "memory"
    return SqliteDatabase(path), f"SQLite {path}"
