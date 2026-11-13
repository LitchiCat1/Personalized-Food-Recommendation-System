"""Render 上用的資料庫：Supabase 的 Postgres。

介面跟 SqliteDatabase 一樣，storage.py 和 auth_repository.py 不用知道底下是哪一種。
本機不設 DATABASE_URL，就照舊用 SQLite（見 database.py）。

上層的 SQL 照 SQLite 的寫法用 ? 當佔位符，這裡換成 psycopg2 的 %s。
jsonb 讀回來已經是 dict，時間讀回來是 datetime；時間轉回跟 SQLite 版一樣的
utc_iso() 字串，JSON 交給 from_json() 原樣放行。

整個後端只開一條連線，用鎖排隊，跟 SQLite 版一樣。Supabase 關掉閒置連線時，
第一句會失敗；這時重連一次再試同一句。Render 免費方案休眠醒來是整個重新啟動，
所以第一次連線失敗會隔幾秒再試，不會一失敗就結束。
"""

from contextlib import contextmanager
from datetime import datetime
import threading
import time
from urllib.parse import unquote, urlsplit

import psycopg2
import psycopg2.extras
from psycopg2.extensions import parse_dsn

from repositories.database import MALFORMED_URL_MESSAGE, DatabaseUnavailable
from repositories.sqlite_db import utc_iso

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
# 閒置的連線被中間的網路設備默默丟掉時，下一句不會卡好幾分鐘（還佔著全後端共用的鎖）
KEEPALIVES = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}
# 第一次連線失敗後隔幾秒再試：共試 3 次
CONNECT_RETRY_DELAYS = (2, 5)


def parse_database_url(url: str) -> dict:
    """用 libpq 自己的拆法（psycopg2 的 parse_dsn，不會連線）拆連線字串。

    網址和 host=... 這種寫法都可以。密碼裡有沒編碼的 @ 或 / 時，libpq 拆出來的主機、
    埠、資料庫名稱會跟看起來的不一樣（例如密碼的後半段變成主機名稱），連不上的錯誤
    訊息就會印出密碼的片段，所以直接拒絕。
    """
    try:
        parts = parse_dsn(url)
    except psycopg2.Error:
        raise DatabaseUnavailable(MALFORMED_URL_MESSAGE) from None
    host = parts.get("host") or ""
    port = parts.get("port") or ""
    dbname = parts.get("dbname") or ""
    if "@" in host or "@" in dbname or "/" in dbname or (port and not port.isdigit()):
        raise DatabaseUnavailable(MALFORMED_URL_MESSAGE)
    return parts


def _describe(parts: dict) -> str:
    port = f":{parts['port']}" if parts.get("port") else ""
    return f"{parts.get('host') or '?'}{port}/{parts.get('dbname') or 'postgres'}"


def describe_database_url(url: str) -> str:
    """給 log 看的「主機:埠/資料庫」，不含帳號密碼。"""
    return _describe(parse_database_url(url))


def _ssl_mode(parts: dict) -> str | None:
    if parts.get("sslmode"):
        return None
    return "prefer" if (parts.get("host") or "").lower() in LOCAL_HOSTS else "require"


def ssl_mode_for(url: str) -> str | None:
    """自己寫了 sslmode 就回 None（照寫的）；本機 prefer，其他一律 require。"""
    return _ssl_mode(parse_database_url(url))


def to_pyformat(sql: str) -> str:
    """SQLite 的 ? 換成 psycopg2 的 %s；SQL 裡本來的 % 要寫成 %%。"""
    return sql.replace("%", "%%").replace("?", "%s")


def _normalize_row(row) -> dict:
    return {key: utc_iso(value) if isinstance(value, datetime) else value for key, value in row.items()}


class PostgresDatabase:
    dialect = "postgres"

    def __init__(self, url: str, connect=None, sleep=None):
        self.url = url
        self._parts = parse_database_url(url)
        self.label = _describe(self._parts)
        self._connect = connect or psycopg2.connect
        self._sleep = sleep or time.sleep
        self._lock = threading.RLock()
        self._in_transaction = False
        self._conn = self._open_with_retries()

    def _redact(self, text: str) -> str:
        # libpq 拆出來的密碼（已解碼）和網址裡原本的寫法（可能還是 %40 這種編碼）都要遮
        raw = urlsplit(self.url).password if "://" in self.url else None
        for secret in {self._parts.get("password"), raw, unquote(raw) if raw else None}:
            if secret:
                text = text.replace(secret, "***")
        return text

    def _open_with_retries(self):
        for delay in (*CONNECT_RETRY_DELAYS, None):
            try:
                return self._open()
            except DatabaseUnavailable:
                if delay is None:
                    raise
                self._sleep(delay)

    def _open(self):
        kwargs: dict[str, object] = {"connect_timeout": 10, **KEEPALIVES}
        sslmode = _ssl_mode(self._parts)
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
            except psycopg2.Error:
                # 只有連線真的斷了才重連再試（psycopg2 會把 closed 設成非 0）。逾時、死結
                # 這類錯誤連線還好好的，重跑只會再做一次，照常往外丟。
                # 交易做到一半斷線也不能重試：重連後只會做到後半段。
                if self._in_transaction or not self._conn.closed:
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
