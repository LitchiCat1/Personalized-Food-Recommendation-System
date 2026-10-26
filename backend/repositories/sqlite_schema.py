"""本機 SQLite 資料庫結構的版本號（存在檔頭的 PRAGMA user_version）。

先前全部靠 CREATE TABLE IF NOT EXISTS：資料表已經存在時它什麼都不做，所以之後
加欄位、改索引，舊的資料庫檔都不會跟著改；用舊版程式開到新版程式改過的檔案，
也不會有任何提醒。

storage.py 和 auth_repository.py 裡的 CREATE TABLE 一律寫「最新」的結構，
舊資料庫靠這裡的升級步驟補上差異。要改結構時：
1. 改 CREATE TABLE 成新的樣子
2. SCHEMA_VERSION 加一
3. 在 MIGRATIONS 加上把上一版改成這一版的函式
後端啟動時會先自動備份一份（檔名有 before-v<版本>），再一版一版升上去；
每一版在一個交易裡做完，中途出錯就整版退回。Render 的 Postgres 不走這裡。
"""

from typing import Callable

from repositories.sqlite_db import SqliteDatabase

SCHEMA_VERSION = 1

# 版本 n → 把 n-1 版的資料庫改成 n 版。例：
#   2: lambda sql: sql.execute("ALTER TABLE records ADD COLUMN note TEXT"),
MIGRATIONS: dict[int, Callable[[SqliteDatabase], None]] = {}


class SchemaVersionError(RuntimeError):
    pass


def check_schema_version(sql: SqliteDatabase, latest: int = SCHEMA_VERSION) -> int:
    """資料庫比程式新就停下來：多半是用新版程式開過、又換回舊版程式。"""
    found = sql.user_version()
    if found > latest:
        raise SchemaVersionError(
            f"資料庫 {sql.path} 是第 {found} 版的結構，這個程式只認得到第 {latest} 版："
            "可能是用新版程式開過，又換回舊版程式。請先把程式更新到最新版（git pull）；"
            "用舊版程式繼續寫入，資料可能會錯亂。"
        )
    return found


def upgrade_schema(sql: SqliteDatabase, backup: Callable[[str], object] | None = None,
                   latest: int = SCHEMA_VERSION, migrations=None) -> list[int]:
    """把資料庫升到 latest 版，回傳這次升了哪幾版。backup(label) 會在真的要升級前呼叫。"""
    migrations = MIGRATIONS if migrations is None else migrations
    current = check_schema_version(sql, latest)
    if current == 0:
        # 0 是 SQLite 的預設值：剛建的空檔（CREATE TABLE 建出來的已經是最新結構），
        # 或是加上版本號之前就有的資料庫（那時的結構就是第 1 版）
        current = latest if sql.was_empty else 1
        sql.set_user_version(current)
    pending = list(range(current + 1, latest + 1))
    if not pending:
        return []
    missing = [version for version in pending if version not in migrations]
    if missing:
        raise SchemaVersionError(f"缺少升級到第 {missing[0]} 版的步驟（sqlite_schema.MIGRATIONS）。")
    # 備份失敗就不升級：沒有備份就改結構，出錯時回不去
    if backup is not None:
        backup(f"before-v{latest}")
    for version in pending:
        with sql.transaction():
            migrations[version](sql)
            sql.set_user_version(version)
    return pending
