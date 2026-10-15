"""Render 上用的資料庫：Supabase 的 Postgres。

介面跟 SqliteDatabase 一樣，storage.py 和 auth_repository.py 不用知道底下是哪一種。
本機不設 DATABASE_URL，就照舊用 SQLite（見 database.py）。

上層的 SQL 照 SQLite 的寫法用 ? 當佔位符，這裡換成 psycopg2 的 %s。
jsonb 讀回來已經是 dict，時間讀回來是 datetime；時間轉回跟 SQLite 版一樣的
utc_iso() 字串，JSON 交給 from_json() 原樣放行。

整個後端只開一條連線，用鎖排隊，跟 SQLite 版一樣。Render 休眠醒來、或 Supabase
關掉閒置連線時，第一句會失敗；這時重連一次再試同一句。
"""

from contextlib import contextmanager
from datetime import datetime
import threading
from urllib.parse import unquote, urlsplit

import psycopg2
import psycopg2.extras

from repositories.sqlite_db import utc_iso

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
CONNECTION_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)


class DatabaseUnavailable(Exception):
    """設了 DATABASE_URL 卻連不上。訊息裡不會有密碼。"""


def describe_database_url(url: str) -> str:
    """給 log 看的「主機:埠/資料庫」，不含帳號密碼。"""
    parts = urlsplit(url)
    port = f":{parts.port}" if parts.port else ""
    name = parts.path.lstrip("/") or "postgres"
    return f"{parts.hostname or '?'}{port}/{name}"


def ssl_mode_for(url: str) -> str | None:
    """網址自己寫了 sslmode 就回 None（照網址的）；本機 prefer，其他一律 require。"""
    if "sslmode=" in url:
        return None
    host = (urlsplit(url).hostname or "").lower()
    return "prefer" if host in LOCAL_HOSTS else "require"


def to_pyformat(sql: str) -> str:
    """SQLite 的 ? 換成 psycopg2 的 %s；SQL 裡本來的 % 要寫成 %%。"""
    return sql.replace("%", "%%").replace("?", "%s")


def _normalize_row(row) -> dict:
    return {key: utc_iso(value) if isinstance(value, datetime) else value for key, value in row.items()}


class PostgresDatabase:
    dialect = "postgres"

    def __init__(self, url: str, connect=None):
        self.url = url
        self.label = describe_database_url(url)
        self._connect = connect or psycopg2.connect
        self._lock = threading.RLock()
        self._in_transaction = False
        self._conn = self._open()

    def _redact(self, text: str) -> str:
        password = urlsplit(self.url).password
        if password:
            for secret in {password, unquote(password)}:
                text = text.replace(secret, "***")
        return text

    def _open(self):
        kwargs = {"connect_timeout": 10}
        sslmode = ssl_mode_for(self.url)
        if sslmode:
            kwargs["sslmode"] = sslmode
        try:
            conn = self._connect(self.url, **kwargs)
        except psycopg2.Error as error:
            # from None：原本的例外訊息可能帶著整串連線字串
            raise DatabaseUnavailable(
                f"連不上 Postgres（{self.label}）：{self._redact(str(error)).strip()}"
            ) from None
        conn.autocommit = True
        return conn

    def _reconnect(self) -> None:
        try:
            self._conn.close()
        except psycopg2.Error:
            pass
        self._conn = self._open()

    def _run_once(self, sql: str, params, fetch: str | None):
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            if params:
                cursor.execute(to_pyformat(sql), tuple(params))
            else:
                # 沒有參數時 psycopg2 不處理 %，SQL 要原樣送出
                cursor.execute(sql)
            if fetch == "one":
                row = cursor.fetchone()
                return _normalize_row(row) if row else None
            if fetch == "all":
                return [_normalize_row(row) for row in cursor.fetchall()]
            return cursor.rowcount

    def _run(self, sql: str, params=(), fetch: str | None = None):
        with self._lock:
            try:
                return self._run_once(sql, params, fetch)
            except CONNECTION_ERRORS:
                # 交易做到一半斷線不能重試：重連後只會做到後半段
                if self._in_transaction:
                    raise
                self._reconnect()
                return self._run_once(sql, params, fetch)

    def execute(self, sql: str, params=()) -> int:
        """回傳受影響的筆數。"""
        return self._run(sql, params)

    def executescript(self, sql: str) -> None:
        self._run(sql)

    def query_one(self, sql: str, params=()) -> dict | None:
        return self._run(sql, params, "one")

    def query_all(self, sql: str, params=()) -> list[dict]:
        return self._run(sql, params, "all")

    def column_names(self, table: str) -> list[str]:
        rows = self.query_all(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ?
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row["column_name"] for row in rows]

    def _rollback_quietly(self) -> None:
        try:
            self._run_once("ROLLBACK", (), None)
        except psycopg2.Error:
            pass

    @contextmanager
    def transaction(self):
        """裡面的每一句要嘛全部成功、要嘛全部不算。"""
        with self._lock:
            self.execute("BEGIN")
            self._in_transaction = True
            try:
                yield self
                self.execute("COMMIT")
            except BaseException:
                self._rollback_quietly()
                raise
            finally:
                self._in_transaction = False

    def close(self) -> None:
        with self._lock:
            self._conn.close()
