# Render 用 Supabase、本機用 SQLite：實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 後端在設了 `DATABASE_URL` 時改用 Supabase 的 Postgres，沒設時照舊用本機 SQLite，登入方式不變。

**Architecture:** 新增 `PostgresDatabase`，介面和現有的 `SqliteDatabase` 一樣（`execute` / `executescript` / `query_one` / `query_all` / `column_names` / `transaction` / `close`，多一個 `dialect` 屬性）。`StorageRepository` 和 `AuthRepository` 的 SQL 不改，只有建表依 `dialect` 分兩份。`repositories/database.py` 的 `open_database()` 依環境變數選資料庫，`app.py` 和 `scripts/reset_password.py` 共用。

**Tech Stack:** Python 3.12、Flask、psycopg2-binary 2.9、bcrypt、unittest。

**Spec:** `docs/superpowers/specs/2026-10-15-render-supabase-design.md`

## Global Constraints

- 設了 `DATABASE_URL`（去掉空白後不是空字串）→ Postgres；沒設 → 照舊 `resolve_database_path()` 的 SQLite；兩者都沒有 → 照舊 MongoDB 或記憶體。
- 設了 `DATABASE_URL` 卻連不上：印出錯誤後 `sys.exit(1)`，不退回記憶體。
- 連線字串裡的密碼不能出現在任何錯誤訊息、log、`/health` 回應裡。
- 後端在 Postgres 建的每張表都要 `ENABLE ROW LEVEL SECURITY`。
- 登入照舊是暱稱＋密碼（bcrypt）＋後端發的 token；前端不改，不裝 `@supabase/supabase-js`。
- 不讀 `MENU_DATABASE_URL`；不碰 Supabase 專案 `NutriLens-Zhuang`。
- 新依賴只有 `psycopg2-binary`（加進 `backend/requirements.txt`，和其他套件一樣不鎖版本）。
- 本機 SQLite 的行為、`/health` 對 SQLite 回傳的值都不能變。
- 寫入正式資料庫（搬帳號的 SQL）和 push 之前都要先問使用者。push 一律用 `git push origin refs/heads/v0.0.9:refs/heads/v0.0.9`（有同名 tag）。
- 測試指令：在 `backend/` 裡執行 `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests`。只跑一個檔：加 `-p "test_postgres_db.py"`。目前基準是 294 個測試全部通過。

## Review Focus

1. **Render 休眠醒來、或 Supabase 關掉閒置連線後的第一個請求**：使用者預期它正常成功（自動重連一次），不是 500。→ Task 1 `test_reconnects_once_after_the_connection_drops`。
2. **密碼含 `@`、`%` 這類字元的 `DATABASE_URL` 連不上時**：使用者預期 log 只看到主機名稱，看不到密碼（包含網址編碼前後兩種寫法）。→ Task 1 `test_unreachable_database_never_shows_the_password`、Task 3 `test_app_refuses_to_start_when_database_url_is_unreachable`。
3. **只差大小寫的暱稱（`Amy` 和 `amy`）在 Postgres 上註冊**：使用者預期被當成同一個帳號（409），不會多出一個。→ Task 4 `test_nickname_is_case_insensitive`。
4. **登入 token 的到期時間存在 `timestamptz`、拿 `utc_iso()` 字串比較**：使用者預期過期的 token 被拒絕、沒過期的照常可用。→ Task 4 `test_expired_session_is_rejected`。
5. **從 Supabase Auth 搬過來的舊帳號（`$2a$` 開頭的 bcrypt、Email 超過 30 個字）**：使用者預期用原本的 Email 和密碼就能登入。→ Task 4 `test_migrated_supabase_account_can_sign_in`。

---

## 檔案結構

| 檔案 | 動作 | 負責什麼 |
|---|---|---|
| `backend/repositories/postgres_db.py` | 新增 | `PostgresDatabase`、`DatabaseUnavailable`、佔位符轉換、型別轉換、重連、遮蔽密碼 |
| `backend/repositories/sqlite_db.py` | 修改 | `SqliteDatabase.dialect = "sqlite"`；`from_json()` 接受已解析的值 |
| `backend/repositories/database.py` | 新增 | `open_database()`：依環境變數選資料庫 |
| `backend/repositories/storage.py` | 修改 | `_init_tables()` 依 `dialect` 選建表語法；新增 `POSTGRES_TABLES` |
| `backend/repositories/auth_repository.py` | 修改 | `_init_tables()` 依 `dialect` 選建表語法；新增 `POSTGRES_AUTH_TABLES` |
| `backend/app.py` | 修改 | 用 `open_database()`；連不上就結束；`/health` 回報 `dialect` |
| `backend/scripts/reset_password.py` | 修改 | 用 `open_database()`，設了 `DATABASE_URL` 就能重設 Render 帳號 |
| `backend/requirements.txt` | 修改 | 加 `psycopg2-binary` |
| `backend/.env.local.example`、`render.yaml` | 修改 | 說明 `DATABASE_URL` |
| `backend/tests/test_postgres_db.py` | 新增 | 包裝層單元測試（假連線） |
| `backend/tests/test_database_selection.py` | 新增 | 選資料庫、啟動失敗、建表語法 |
| `backend/tests/test_postgres_integration.py` | 新增 | 對真的 Postgres 跑（沒設 `NUTRILENS_TEST_DATABASE_URL` 就跳過） |
| `backend/tests/test_api_routes.py` | 修改 | 開頭移除 `DATABASE_URL` |

---

### Task 1: `PostgresDatabase` 包裝層

**Files:**
- Create: `backend/repositories/postgres_db.py`
- Modify: `backend/repositories/sqlite_db.py`（`from_json` 約第 50 行、`class SqliteDatabase` 約第 56 行）
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_postgres_db.py`

**Interfaces:**
- Consumes: `repositories.sqlite_db.utc_iso(moment)`
- Produces:
  - `class DatabaseUnavailable(Exception)`：設了 `DATABASE_URL` 卻連不上；訊息不含密碼。
  - `class PostgresDatabase(url: str, connect=None)`：屬性 `dialect = "postgres"`、`label: str`（`host:port/dbname`）、`url`；方法 `execute(sql, params=()) -> int`、`executescript(sql) -> None`、`query_one(sql, params=()) -> dict | None`、`query_all(sql, params=()) -> list[dict]`、`column_names(table) -> list[str]`、`transaction()`（context manager）、`close()`。`connect` 預設 `psycopg2.connect`，測試傳假的。
  - `describe_database_url(url) -> str`、`ssl_mode_for(url) -> str | None`、`to_pyformat(sql) -> str`。
  - `SqliteDatabase.dialect = "sqlite"`。
  - `from_json(value)`：字串照舊 `json.loads`，`None` / `""` 回 `None`，其他型別原樣回傳。

- [ ] **Step 1: 寫失敗的測試**

建立 `backend/tests/test_postgres_db.py`：

```python
"""Render 用的 Postgres 包裝層。

這台電腦沒有 Postgres，這裡用假的連線測包裝層自己的邏輯（佔位符、型別、
交易、重連、不洩漏密碼）；真的 SQL 在 test_postgres_integration.py 對真的資料庫跑。
"""

import unittest
from datetime import datetime, timezone

import psycopg2

from repositories.postgres_db import (
    DatabaseUnavailable,
    PostgresDatabase,
    describe_database_url,
    ssl_mode_for,
    to_pyformat,
)
from repositories.sqlite_db import SqliteDatabase, from_json

# 密碼是 s3cr@t，網址裡編碼成 s3cr%40t
URL = "postgresql://postgres.abc:s3cr%40t@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self.conn.broken:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        self.conn.executed.append((sql, params))
        self._rows = list(self.conn.next_rows)
        self.rowcount = self.conn.next_rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.next_rows = []
        self.next_rowcount = 1
        self.broken = False
        self.closed = False
        self.autocommit = False

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def close(self):
        self.closed = True


class FakeConnector:
    """psycopg2.connect 的替身：記下每次連線的參數，可以指定接下來幾次失敗。"""

    def __init__(self, failures=0, error=None):
        self.failures = failures
        self.error = error or psycopg2.OperationalError("could not connect to server")
        self.calls = []
        self.connections = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.failures:
            self.failures -= 1
            raise self.error
        conn = FakeConnection()
        self.connections.append(conn)
        return conn


def statements(conn):
    return [sql for sql, _ in conn.executed]


class PlaceholderTests(unittest.TestCase):
    def test_question_marks_become_pyformat(self):
        self.assertEqual(
            to_pyformat("SELECT doc FROM t WHERE k IN (?, ?, ?) AND name LIKE ?"),
            "SELECT doc FROM t WHERE k IN (%s, %s, %s) AND name LIKE %s",
        )

    def test_literal_percent_is_escaped(self):
        self.assertEqual(to_pyformat("SELECT '100%' WHERE a = ?"), "SELECT '100%%' WHERE a = %s")

    def test_params_are_sent_as_a_tuple(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        db.query_all("SELECT doc FROM custom_foods WHERE user_id = ?", ["user-a"])
        self.assertEqual(
            connector.connections[0].executed[-1],
            ("SELECT doc FROM custom_foods WHERE user_id = %s", ("user-a",)),
        )

    def test_statements_without_params_are_sent_untouched(self):
        # 沒有參數時 psycopg2 不處理 %，所以不能把 % 變成 %%
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        db.execute("SELECT '100%'")
        self.assertEqual(connector.connections[0].executed[-1], ("SELECT '100%'", None))


class RowTests(unittest.TestCase):
    def test_datetimes_come_back_as_utc_iso_strings_and_json_as_is(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].next_rows = [{
            "failed_until": datetime(2026, 10, 15, 1, 2, 3, tzinfo=timezone.utc),
            "doc": {"name": "滷肉飯"},
        }]
        row = db.query_one("SELECT failed_until, doc FROM t WHERE venue_key = ?", ("k",))
        self.assertEqual(row["failed_until"], "2026-10-15T01:02:03.000000+00:00")
        self.assertEqual(row["doc"], {"name": "滷肉飯"})

    def test_query_one_returns_none_when_nothing_matches(self):
        db = PostgresDatabase(URL, connect=FakeConnector())
        self.assertIsNone(db.query_one("SELECT doc FROM users WHERE user_id = ?", ("nobody",)))

    def test_execute_returns_the_rowcount(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].next_rowcount = 0
        self.assertEqual(db.execute("INSERT INTO auth_users (id) VALUES (?) ON CONFLICT DO NOTHING", ("a",)), 0)

    def test_from_json_accepts_values_postgres_already_decoded(self):
        self.assertEqual(from_json({"a": 1}), {"a": 1})
        self.assertEqual(from_json([1, 2]), [1, 2])
        self.assertEqual(from_json('{"a": 1}'), {"a": 1})
        self.assertIsNone(from_json(None))
        self.assertIsNone(from_json(""))

    def test_column_names_read_information_schema(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].next_rows = [{"column_name": "user_id"}, {"column_name": "doc"}]
        self.assertEqual(db.column_names("users"), ["user_id", "doc"])
        sql, params = connector.connections[0].executed[-1]
        self.assertIn("information_schema.columns", sql)
        self.assertEqual(params, ("users",))

    def test_dialects(self):
        self.assertEqual(PostgresDatabase.dialect, "postgres")
        self.assertEqual(SqliteDatabase(":memory:").dialect, "sqlite")


class ConnectionTests(unittest.TestCase):
    def test_cloud_hosts_require_ssl_and_local_hosts_prefer_it(self):
        self.assertEqual(ssl_mode_for(URL), "require")
        self.assertEqual(ssl_mode_for("postgresql://u:p@localhost:5432/db"), "prefer")
        self.assertEqual(ssl_mode_for("postgresql://u:p@127.0.0.1:5432/db"), "prefer")
        self.assertIsNone(ssl_mode_for(URL + "?sslmode=disable"))

    def test_connects_with_autocommit_timeout_and_ssl(self):
        connector = FakeConnector()
        PostgresDatabase(URL, connect=connector)
        self.assertEqual(connector.calls[0], (URL, {"connect_timeout": 10, "sslmode": "require"}))
        self.assertTrue(connector.connections[0].autocommit)

    def test_url_with_its_own_sslmode_is_left_alone(self):
        connector = FakeConnector()
        PostgresDatabase(URL + "?sslmode=disable", connect=connector)
        self.assertEqual(connector.calls[0][1], {"connect_timeout": 10})

    def test_label_has_host_and_database_but_no_password(self):
        self.assertEqual(describe_database_url(URL), "aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres")
        self.assertEqual(PostgresDatabase(URL, connect=FakeConnector()).label, describe_database_url(URL))

    def test_unreachable_database_never_shows_the_password(self):
        # 連線字串寫錯時 psycopg2 會把整串連線字串放進錯誤訊息
        error = psycopg2.OperationalError(f'invalid dsn: missing "=" after "{URL}" (password s3cr@t)')
        with self.assertRaises(DatabaseUnavailable) as ctx:
            PostgresDatabase(URL, connect=FakeConnector(failures=1, error=error))
        message = str(ctx.exception)
        self.assertNotIn("s3cr%40t", message)
        self.assertNotIn("s3cr@t", message)
        self.assertIn("aws-0-ap-southeast-2.pooler.supabase.com", message)
        self.assertIsNone(ctx.exception.__cause__)

    def test_reconnects_once_after_the_connection_drops(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].broken = True
        self.assertEqual(db.query_all("SELECT doc FROM users WHERE user_id = ?", ("a",)), [])
        self.assertEqual(len(connector.connections), 2)
        self.assertTrue(connector.connections[0].closed)
        self.assertEqual(statements(connector.connections[1]), ["SELECT doc FROM users WHERE user_id = %s"])

    def test_gives_up_when_reconnecting_fails_too(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        connector.connections[0].broken = True
        connector.failures = 1
        with self.assertRaises(DatabaseUnavailable):
            db.query_all("SELECT 1 WHERE 1 = ?", (1,))


class TransactionTests(unittest.TestCase):
    def test_commits_when_everything_succeeds(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with db.transaction():
            db.execute("UPDATE records SET meal_type = ? WHERE user_id = ?", ("早餐", "a"))
        self.assertEqual(
            statements(connector.connections[0]),
            ["BEGIN", "UPDATE records SET meal_type = %s WHERE user_id = %s", "COMMIT"],
        )

    def test_rolls_back_and_reraises_on_error(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with self.assertRaises(ValueError):
            with db.transaction():
                db.execute("DELETE FROM records WHERE user_id = ?", ("a",))
                raise ValueError("boom")
        self.assertEqual(
            statements(connector.connections[0]),
            ["BEGIN", "DELETE FROM records WHERE user_id = %s", "ROLLBACK"],
        )

    def test_does_not_retry_inside_a_transaction(self):
        # 交易做到一半斷線，重連後只會做到後半段，所以直接丟錯
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with self.assertRaises(psycopg2.OperationalError):
            with db.transaction():
                connector.connections[0].broken = True
                db.execute("DELETE FROM auth_sessions WHERE user_id = ?", ("a",))
        self.assertEqual(len(connector.connections), 1)

    def test_next_query_after_a_failed_transaction_reconnects(self):
        connector = FakeConnector()
        db = PostgresDatabase(URL, connect=connector)
        with self.assertRaises(psycopg2.OperationalError):
            with db.transaction():
                connector.connections[0].broken = True
                db.execute("DELETE FROM auth_sessions WHERE user_id = ?", ("a",))
        db.query_all("SELECT 1 WHERE 1 = ?", (1,))
        self.assertEqual(len(connector.connections), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認會失敗**

Run（在 `backend/`）：`NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_postgres_db.py"`
Expected: FAIL，`ModuleNotFoundError: No module named 'repositories.postgres_db'`。

- [ ] **Step 3: 修改 `sqlite_db.py`**

`from_json` 換成：

```python
def from_json(text):
    """SQLite 存的是 JSON 字串；Postgres 的 jsonb 讀回來已經是 dict / list，原樣回傳。"""
    if text is None or text == "":
        return None
    if not isinstance(text, (str, bytes, bytearray)):
        return text
    return json.loads(text)
```

`class SqliteDatabase:` 的下一行加：

```python
    dialect = "sqlite"
```

- [ ] **Step 4: 建立 `backend/repositories/postgres_db.py`**

```python
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
```

`backend/requirements.txt` 最後加一行：

```
psycopg2-binary
```

- [ ] **Step 5: 跑測試確認通過**

Run: `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_postgres_db.py"`
Expected: 全部 PASS。

再跑全部：`NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests`
Expected: `OK`，測試數 = 294 + 本檔的數量。

- [ ] **Step 6: Commit**

```bash
git add backend/repositories/postgres_db.py backend/repositories/sqlite_db.py backend/requirements.txt backend/tests/test_postgres_db.py
git commit -m "feat: add a Postgres database with the same interface as the SQLite one"
```

---

### Task 2: 依資料庫種類建表（含 RLS）

**Files:**
- Modify: `backend/repositories/storage.py`（`RECORD_SELECT` 之後加常數；`_init_tables` 約第 34 行）
- Modify: `backend/repositories/auth_repository.py`（`EmailAlreadyRegistered` 之前加常數；`_init_tables` 約第 28 行）
- Test: `backend/tests/test_database_selection.py`（本 task 先建檔放建表的測試，Task 3 再加）

**Interfaces:**
- Consumes: `db.dialect`（Task 1）、`db.executescript(sql)`
- Produces: `repositories.storage.POSTGRES_TABLES: str`、`repositories.auth_repository.POSTGRES_AUTH_TABLES: str`

- [ ] **Step 1: 寫失敗的測試**

建立 `backend/tests/test_database_selection.py`：

```python
"""選資料庫、Postgres 建表、設了 DATABASE_URL 卻連不上時的行為。"""

import unittest

from repositories.auth_repository import AuthRepository
from repositories.storage import StorageRepository

STORAGE_TABLES = ("users", "records", "custom_foods", "restaurant_menus", "restaurant_menu_failures")


class RecordingDatabase:
    """只記下建表語法的假資料庫。"""

    dialect = "postgres"

    def __init__(self):
        self.scripts = []

    def executescript(self, sql):
        self.scripts.append(sql)


class PostgresTableTests(unittest.TestCase):
    def test_storage_tables_match_supabase_types_and_enable_rls(self):
        db = RecordingDatabase()
        StorageRepository(None, False, {}, [], [], sql=db)
        script = "\n".join(db.scripts)
        self.assertIn("JSONB", script)
        self.assertIn("BIGSERIAL", script)
        self.assertIn("TIMESTAMPTZ", script)
        self.assertNotIn("AUTOINCREMENT", script)
        for table in STORAGE_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", script)
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;", script)

    def test_auth_tables_enable_rls_so_the_public_api_cannot_read_hashes(self):
        db = RecordingDatabase()
        AuthRepository(db)
        script = "\n".join(db.scripts)
        self.assertIn("expires_at TIMESTAMPTZ NOT NULL", script)
        for table in ("auth_users", "auth_sessions"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", script)
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;", script)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認會失敗**

Run: `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_database_selection.py"`
Expected: FAIL（`JSONB` 不在建表語法裡：目前一律送 SQLite 的語法）。

- [ ] **Step 3: 修改 `storage.py`**

在 `RECORD_SELECT = ", ".join(RECORD_COLUMNS)` 之後加：

```python


# Render 用的 Supabase（Postgres）。型別跟 nutrilens 專案現有的表一致：
# 表已經存在時 CREATE ... IF NOT EXISTS 什麼都不做，舊資料原封不動。
# 每張表都開 RLS：後端是表的擁有者不受影響，但 Supabase 的公開 API（anon key）就讀不到。
POSTGRES_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    doc JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS records (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    client_record_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    meal_type TEXT,
    foods JSONB,
    total_calories DOUBLE PRECISION DEFAULT 0,
    total_protein DOUBLE PRECISION DEFAULT 0,
    total_carbs DOUBLE PRECISION DEFAULT 0,
    total_fat DOUBLE PRECISION DEFAULT 0,
    total_sodium DOUBLE PRECISION DEFAULT 0,
    total_fiber DOUBLE PRECISION DEFAULT 0,
    total_sugar DOUBLE PRECISION DEFAULT 0,
    total_saturated_fat DOUBLE PRECISION DEFAULT 0,
    total_trans_fat DOUBLE PRECISION DEFAULT 0,
    source TEXT DEFAULT 'camera'
);
CREATE INDEX IF NOT EXISTS idx_records_user_timestamp ON records (user_id, timestamp DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_records_user_client_record ON records (user_id, client_record_id);
CREATE TABLE IF NOT EXISTS custom_foods (
    owner_key TEXT PRIMARY KEY,
    food_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    doc JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_custom_foods_user_id ON custom_foods (user_id);
CREATE TABLE IF NOT EXISTS restaurant_menus (
    venue_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT,
    doc JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restaurant_menus_name ON restaurant_menus (name_key);
CREATE TABLE IF NOT EXISTS restaurant_menu_failures (
    venue_key TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    failed_until TIMESTAMPTZ NOT NULL
);
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_foods ENABLE ROW LEVEL SECURITY;
ALTER TABLE restaurant_menus ENABLE ROW LEVEL SECURITY;
ALTER TABLE restaurant_menu_failures ENABLE ROW LEVEL SECURITY;
"""
```

`_init_tables` 的開頭（`# SQLite 沒有 JSON 與時間型別` 那行之前）加：

```python
        if self.sql.dialect == "postgres":
            self.sql.executescript(POSTGRES_TABLES)
            return
```

- [ ] **Step 4: 修改 `auth_repository.py`**

在 `class EmailAlreadyRegistered(Exception):` 之前加：

```python
# Render 用的 Supabase（Postgres）。開 RLS：密碼雜湊和 token 雜湊不能被公開 API 讀到。
POSTGRES_AUTH_TABLES = """
CREATE TABLE IF NOT EXISTS auth_users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES auth_users (id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions (user_id);
ALTER TABLE auth_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
"""


```

`_init_tables` 的開頭（`# 只存 token 的 SHA-256` 那行之前）加：

```python
        if self.sql.dialect == "postgres":
            self.sql.executescript(POSTGRES_AUTH_TABLES)
            return
```

模組 docstring 第二段改成：

```python
帳號、密碼雜湊與登入 token 存在資料庫裡：本機是 SQLite，Render 是 Supabase 的 Postgres。
不依賴任何雲端登入服務。沒有資料庫時退回記憶體，只適合跑測試——重啟後帳號就不見了。
```

- [ ] **Step 5: 跑測試確認通過**

Run: `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_database_selection.py"`
Expected: PASS。

再跑全部：`NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests`
Expected: `OK`（SQLite 的建表沒變，`test_sqlite_storage.py` 照樣通過）。

- [ ] **Step 6: Commit**

```bash
git add backend/repositories/storage.py backend/repositories/auth_repository.py backend/tests/test_database_selection.py
git commit -m "feat: create the Postgres tables with Supabase's types and row level security"
```

---

### Task 3: 依 `DATABASE_URL` 選資料庫、連不上就不啟動

**Files:**
- Create: `backend/repositories/database.py`
- Modify: `backend/app.py`（import 約第 23 行；資料庫段落約第 84–95 行；`/health` 約第 414–431 行）
- Modify: `backend/scripts/reset_password.py`
- Modify: `backend/tests/test_api_routes.py`（第 13–15 行）
- Modify: `backend/.env.local.example`、`render.yaml`
- Test: `backend/tests/test_database_selection.py`（接著 Task 2 加）

**Interfaces:**
- Consumes: `PostgresDatabase`、`DatabaseUnavailable`（Task 1）、`SqliteDatabase`、`resolve_database_path()`
- Produces: `repositories.database.open_database(connect=None) -> tuple[PostgresDatabase | SqliteDatabase | None, str]`；說明文字是 `"Postgres <host:port/db>"`、`"SQLite <path>"` 或 `"memory"`。重新匯出 `DatabaseUnavailable`。

- [ ] **Step 1: 寫失敗的測試**

在 `backend/tests/test_database_selection.py` 最上面的 import 換成：

```python
import contextlib
import importlib
import io
import os
import sys
import unittest
from unittest.mock import patch

import psycopg2

from repositories.auth_repository import AuthRepository
from repositories.database import DatabaseUnavailable, open_database
from repositories.postgres_db import PostgresDatabase
from repositories.sqlite_db import SqliteDatabase
from repositories.storage import StorageRepository
from test_postgres_db import URL, FakeConnector
```

在 `if __name__ == "__main__":` 之前加：

```python
class OpenDatabaseTests(unittest.TestCase):
    def test_database_url_selects_postgres(self):
        with patch.dict(os.environ, {"DATABASE_URL": URL, "DATABASE_PATH": ""}, clear=True):
            db, label = open_database(connect=FakeConnector())
        self.assertIsInstance(db, PostgresDatabase)
        self.assertEqual(label, "Postgres aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres")

    def test_without_database_url_uses_sqlite(self):
        with patch.dict(os.environ, {"DATABASE_PATH": ":memory:"}, clear=True):
            db, label = open_database()
        self.assertIsInstance(db, SqliteDatabase)
        self.assertEqual(label, "SQLite :memory:")

    def test_blank_database_url_is_ignored(self):
        with patch.dict(os.environ, {"DATABASE_URL": "   ", "DATABASE_PATH": ""}, clear=True):
            self.assertEqual(open_database(), (None, "memory"))

    def test_unreachable_postgres_raises_instead_of_falling_back(self):
        with patch.dict(os.environ, {"DATABASE_URL": URL}, clear=True):
            with self.assertRaises(DatabaseUnavailable):
                open_database(connect=FakeConnector(failures=1))


class AppStartupTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("app", None)

    def test_app_refuses_to_start_when_database_url_is_unreachable(self):
        output = io.StringIO()
        failure = psycopg2.OperationalError(f'invalid dsn: "{URL}"')
        with patch.dict(os.environ, {"DATABASE_URL": URL, "NUTRILENS_SKIP_LOCAL_ENV": "1"}), \
                patch("repositories.postgres_db.psycopg2.connect", side_effect=failure), \
                contextlib.redirect_stdout(output):
            sys.modules.pop("app", None)
            with self.assertRaises(SystemExit) as ctx:
                importlib.import_module("app")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("pooler.supabase.com", output.getvalue())
        self.assertNotIn("s3cr", output.getvalue())
```

- [ ] **Step 2: 跑測試確認會失敗**

Run: `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_database_selection.py"`
Expected: FAIL，`ModuleNotFoundError: No module named 'repositories.database'`。

- [ ] **Step 3: 建立 `backend/repositories/database.py`**

```python
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
        db = PostgresDatabase(url, connect=connect)
        return db, f"Postgres {db.label}"
    path = resolve_database_path()
    if not path:
        return None, "memory"
    return SqliteDatabase(path), f"SQLite {path}"
```

- [ ] **Step 4: 修改 `app.py`**

第 23 行 `from repositories.sqlite_db import SqliteDatabase, resolve_database_path` 換成：

```python
from repositories.database import DatabaseUnavailable, open_database
from repositories.sqlite_db import resolve_database_path
```

資料庫段落（`# ─── 資料庫：本機的 SQLite 檔案` 到 `print(f"[WARN] SQLite unavailable ({database_path}) - {e}")`）整段換成：

```python
# ─── 資料庫 ──────────────────────────────────────────────────
# Render 設了 DATABASE_URL：用 Supabase 的 Postgres，部署和休眠都不會清空資料。
# 本機沒設：帳號、健康檔案、飲食紀錄、店家菜單都存在一個 SQLite 檔。位置見
# sqlite_db.py，可以用 DATABASE_PATH 改；設成空字串就不用資料庫，資料只存在記憶體。
sql_db = None
try:
    sql_db, database_label = open_database()
    if sql_db is not None:
        print(f"[OK] Database: {database_label}")
except DatabaseUnavailable as e:
    # 設了雲端資料庫卻連不上：不能退回記憶體，不然看起來正常、資料其實沒存。
    # Render 的部署會失敗，繼續跑上一版。
    print(f"[ERROR] {e}")
    sys.exit(1)
except Exception as e:
    print(f"[WARN] SQLite unavailable ({resolve_database_path()}) - {e}")
# 路徑裡有 Windows 使用者名稱，/health 只給這台電腦自己看
database_path = sql_db.path if sql_db is not None and sql_db.dialect == "sqlite" else None
```

`/health` 裡的三行換成：

```python
        "database": sql_db.dialect if sql_db is not None else ("mongo" if USE_MONGO else "memory"),
        # 路徑裡有 Windows 使用者名稱，只給這台電腦自己看；Postgres 不回傳主機
        "database_path": database_path if database_path and is_local_request() else None,
```

和

```python
        "auth_provider": f"local-{sql_db.dialect}" if auth_repo.use_sql else "local-memory",
```

改完用 `grep -n "database_path\|SqliteDatabase" backend/app.py` 確認沒有漏掉的舊用法（應該只剩上面這幾處）。

- [ ] **Step 5: 修改 `scripts/reset_password.py`**

docstring 的最後一段之後加一段：

```
要重設 Render 上（Supabase）的帳號：先把 DATABASE_URL 設成 Supabase 的連線字串再執行。
```

import 的兩行

```python
from repositories.auth_repository import AuthRepository  # noqa: E402
from repositories.sqlite_db import SqliteDatabase, resolve_database_path  # noqa: E402
```

換成

```python
from repositories.auth_repository import AuthRepository  # noqa: E402
from repositories.database import DatabaseUnavailable, open_database  # noqa: E402
from repositories.sqlite_db import resolve_database_path  # noqa: E402
```

`main()` 從開頭到 `repo = AuthRepository(sql)` 換成：

```python
def main() -> int:
    load_local_env()
    if not os.environ.get("DATABASE_URL", "").strip():
        # 本機：資料庫檔不存在就停下來，不要建一個新的空檔
        database_path = resolve_database_path()
        if not database_path or database_path == ":memory:" or not os.path.exists(database_path):
            print(f"找不到資料庫檔案：{database_path}")
            return 1
    try:
        sql, label = open_database()
    except DatabaseUnavailable as error:
        print(error)
        return 1
    print(f"資料庫：{label}")
    repo = AuthRepository(sql)
```

- [ ] **Step 6: 測試不能連到正式資料庫**

`backend/tests/test_api_routes.py` 第 13–15 行換成：

```python
# 在任何測試 import app 之前：不讀 backend/.env.local（裡面是真的金鑰），
# DATABASE_PATH 設成空字串（不設的話後端會開本機正式的 SQLite 檔），
# 拿掉 DATABASE_URL（有的話後端會連 Supabase），測試只寫記憶體。
os.environ["NUTRILENS_SKIP_LOCAL_ENV"] = "1"
os.environ["DATABASE_PATH"] = ""
os.environ.pop("DATABASE_URL", None)
```

- [ ] **Step 7: 說明文件**

`backend/.env.local.example` 在 `# DATABASE_PATH=D:\NutriLens\nutrilens.db` 之後加：

```
# 本機不要設 DATABASE_URL：設了就會改連雲端的 Supabase。只有 Render 要設（在 Render 後台）。
```

`render.yaml` 的 `nutrilens-backend` 裡，把

```yaml
    # 資料存在 SQLite 檔（DATABASE_PATH）。Render 免費方案的磁碟每次部署都會清空，
    # 帳號與紀錄會跟著消失；要長期放在 Render 得掛 persistent disk 並把 DATABASE_PATH 指過去。
    envVars:
```

換成

```yaml
    # 資料存在 Supabase 的 Postgres：DATABASE_URL 填 Supabase → Connect → Session pooler
    # 的連線字串（Render 只走 IPv4，db.<ref>.supabase.co 那個直連網址連不上）。
    # 沒設的話會用 Render 磁碟上的 SQLite，每次部署都會清空。
    envVars:
      - key: DATABASE_URL
        sync: false
```

- [ ] **Step 8: 跑測試確認通過**

Run: `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_database_selection.py"`
Expected: PASS。

再跑全部：`NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests`
Expected: `OK`。

本機啟動檢查（不設 `DATABASE_URL`）：`DATABASE_PATH=":memory:" NUTRILENS_SKIP_LOCAL_ENV=1 python -c "import app; print(app.app.test_client().get('/health').get_json()['database'])"`
Expected: 啟動訊息有 `[OK] Database: SQLite :memory:`，最後印 `sqlite`。

- [ ] **Step 9: Commit**

```bash
git add backend/repositories/database.py backend/app.py backend/scripts/reset_password.py backend/tests/test_api_routes.py backend/tests/test_database_selection.py backend/.env.local.example render.yaml
git commit -m "feat: use Supabase when DATABASE_URL is set and refuse to start if it is unreachable"
```

---

### Task 4: 對真的 Postgres 跑一次

**Files:**
- Test: `backend/tests/test_postgres_integration.py`

**Interfaces:**
- Consumes: `PostgresDatabase`（Task 1）、`StorageRepository` / `AuthRepository` 的 Postgres 建表（Task 2）、`services.auth_service` 的 `sign_up` / `sign_in` / `verify_access_token` / `hash_token` / `AuthError`
- Produces: 無（只有測試）

測試只在設了 `NUTRILENS_TEST_DATABASE_URL` 時跑，而且每次建一個隨機名字的 schema、全部在裡面做、做完整個刪掉，不碰 `public` 裡的任何表。

- [ ] **Step 1: 寫測試**

建立 `backend/tests/test_postgres_integration.py`：

```python
"""對真的 Postgres 跑 storage 與登入。

只有設了 NUTRILENS_TEST_DATABASE_URL 才會跑。每次建一個隨機名字的 schema，
所有表都建在裡面，跑完整個刪掉；不會碰到 public 裡的資料。
"""

import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt

from repositories.auth_repository import AuthRepository
from repositories.postgres_db import PostgresDatabase
from repositories.storage import StorageRepository
from services.app_time_service import app_now
from services.auth_service import AuthError, hash_token, sign_in, sign_up, verify_access_token

TEST_URL = os.environ.get("NUTRILENS_TEST_DATABASE_URL", "").strip()


@unittest.skipUnless(TEST_URL, "沒設 NUTRILENS_TEST_DATABASE_URL")
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.schema = f"nutrilens_test_{uuid.uuid4().hex[:8]}"
        self.db = PostgresDatabase(TEST_URL)
        self.db.execute(f"CREATE SCHEMA {self.schema}")
        self.db.execute(f"SET search_path TO {self.schema}")
        self.storage = StorageRepository(None, False, {}, [], [], sql=self.db)
        self.auth = AuthRepository(self.db)

    def tearDown(self):
        self.db.execute(f"DROP SCHEMA {self.schema} CASCADE")
        self.db.close()

    def meal(self, client_record_id, calories=500):
        stamp = app_now().replace(tzinfo=None).strftime("%Y-%m-%dT12:00:00")
        return {
            "user_id": "user-a",
            "client_record_id": client_record_id,
            "timestamp": stamp,
            "meal_type": "午餐",
            "foods": [{"name": "滷肉飯", "calories": calories, "sodium": 800}],
            "total_calories": calories,
            "total_sodium": 800,
            "source": "manual",
        }

    def test_tables_land_in_the_test_schema_with_rls(self):
        rows = self.db.query_all(
            "SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = ? ORDER BY tablename",
            (self.schema,),
        )
        self.assertEqual(
            {row["tablename"] for row in rows},
            {"auth_sessions", "auth_users", "custom_foods", "records",
             "restaurant_menu_failures", "restaurant_menus", "users"},
        )
        self.assertTrue(all(row["rowsecurity"] for row in rows))
        self.assertIn("doc", self.db.column_names("users"))

    def test_user_doc_round_trips_as_a_dict(self):
        doc = {"user_id": "user-a", "name": "小明", "health_conditions": ["高血壓"]}
        self.storage.upsert_user(doc)
        self.assertEqual(self.storage.get_user("user-a"), doc)
        # 舊資料：直接寫進去、沒有 profile_complete 的 jsonb 也要讀得出 dict
        self.db.execute("INSERT INTO users (user_id, doc) VALUES (?, ?)", ("legacy", '{"user_id": "legacy"}'))
        self.assertEqual(self.storage.get_user("legacy"), {"user_id": "legacy"})

    def test_records_insert_update_history_and_delete(self):
        self.storage.insert_record(self.meal("m1", 500))
        self.storage.insert_record(self.meal("m2", 300))
        again = self.storage.insert_record(self.meal("m1", 500))
        self.assertTrue(again.get("_deduplicated"))
        records = self.storage.get_records("user-a")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["foods"][0]["name"], "滷肉飯")
        history = self.storage.get_history("user-a", 7)
        self.assertEqual(history[-1]["record_count"], 2)
        self.assertEqual(history[-1]["calories"], 800)
        updated = self.storage.update_record({**self.meal("m2", 300), "meal_type": "晚餐"})
        self.assertTrue(updated)
        self.assertEqual(self.storage.get_record_by_client_record_id("user-a", "m2")["meal_type"], "晚餐")
        self.storage.delete_record("user-a", "m1")
        self.assertEqual(len(self.storage.get_records("user-a")), 1)

    def test_restaurant_menu_and_failure_cooldown(self):
        self.storage.save_restaurant_menu("阿明小吃", [{"name": "滷肉飯"}], {"google_place_id": "p1"})
        menu = self.storage.get_restaurant_menu(name="阿明小吃", place_id="p1")
        self.assertEqual(menu["items"][0]["name"], "滷肉飯")
        self.assertEqual(self.storage.count_restaurant_menus(), 1)
        self.storage.mark_restaurant_menu_failure("k1", "no menu", 600)
        self.assertEqual(self.storage.active_restaurant_menu_failures(["k1", "k2"]), {"k1"})

    def test_sign_up_sign_in_and_token(self):
        sign_up(self.auth, "小明", "pw")
        session = sign_in(self.auth, "小明", "pw")
        user = verify_access_token(self.auth, f"Bearer {session['access_token']}")
        self.assertEqual(user["email"], "小明")

    def test_nickname_is_case_insensitive(self):
        sign_up(self.auth, "Amy", "pw")
        with self.assertRaises(AuthError) as ctx:
            sign_up(self.auth, "amy", "other")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) AS n FROM auth_users")["n"], 1)

    def test_expired_session_is_rejected(self):
        user = self.auth.create_user("old", "hash")
        self.auth.create_session(user["id"], hash_token("fresh"), datetime.now(timezone.utc) + timedelta(hours=1))
        self.auth.create_session(user["id"], hash_token("stale"), datetime.now(timezone.utc) - timedelta(seconds=1))
        self.assertIsNotNone(self.auth.get_session_user(hash_token("fresh")))
        self.assertIsNone(self.auth.get_session_user(hash_token("stale")))

    def test_migrated_supabase_account_can_sign_in(self):
        # Supabase Auth 存的是 $2a$ 開頭的 bcrypt；舊帳號的 Email 可能超過暱稱的 30 字上限
        email = "a.very.long.address.from.before@example.com"
        legacy_hash = bcrypt.hashpw(b"old-password", bcrypt.gensalt(prefix=b"2a")).decode()
        self.auth.create_user(email, legacy_hash, user_id="6f1c2d3e-0000-4000-8000-000000000001")
        session = sign_in(self.auth, email.upper(), "old-password")
        self.assertEqual(session["user"]["id"], "6f1c2d3e-0000-4000-8000-000000000001")


if __name__ == "__main__":
    unittest.main()
```

先確認這幾個方法的實際簽名和回傳，跟測試對得上再往下走（不對就改測試、不改產品程式）：`grep -n "def create_session\|def save_restaurant_menu\|def update_record\|def delete_record\|def mark_restaurant_menu_failure" backend/repositories/*.py`、`grep -n "\"user\"" backend/services/auth_service.py`。

- [ ] **Step 2: 沒設網址時會跳過**

Run: `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_postgres_integration.py"`
Expected: `OK (skipped=1)`。

- [ ] **Step 3: 準備一個真的 Postgres，先問使用者**

先試本機的拋棄式 Postgres（不碰任何雲端資料）：在 scratchpad 建一個 venv 安裝 `pgserver`（PyPI 上把 Postgres 執行檔包成 wheel 的套件），啟動一個資料夾在 scratchpad 的伺服器，取得連線網址。

```bash
python -m venv "<scratchpad>/pgvenv"
"<scratchpad>/pgvenv/Scripts/python" -m pip install pgserver
"<scratchpad>/pgvenv/Scripts/python" -c "import pgserver; s = pgserver.get_server(r'<scratchpad>/pgdata', cleanup_mode=None); print(s.get_uri())"
```

裝不起來或啟動失敗時，停下來問使用者選哪一個：
- (a) 部署後再驗證（見 Task 5 的步驟 4–6）；
- (b) 用 Supabase `nutrilens` 專案的連線字串跑這個測試——它只在自己建的隨機 schema 裡做事、做完刪掉，但仍然是對正式專案的寫入，要使用者明確同意，並由使用者自己把網址設進 `NUTRILENS_TEST_DATABASE_URL`（Claude 不經手密碼）。

- [ ] **Step 4: 對真的 Postgres 跑**

Run: `NUTRILENS_TEST_DATABASE_URL="<網址>" NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests -p "test_postgres_integration.py" -v`
Expected: 8 個測試全部 PASS。失敗時照錯誤修正產品程式（多半是 Task 1 的型別轉換或 Task 2 的建表），修完重跑 Task 1–3 的單元測試和這裡。

用完關掉本機的 Postgres：`"<scratchpad>/pgvenv/Scripts/python" -c "import pgserver; pgserver.get_server(r'<scratchpad>/pgdata', cleanup_mode='stop')"`（或用 pgserver 附的 `pg_ctl stop -D <scratchpad>/pgdata`）。

- [ ] **Step 5: 全部測試再跑一次**

Run: `NUTRILENS_SKIP_LOCAL_ENV=1 python -m unittest discover -s tests`
Expected: `OK (skipped=1)`。

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_postgres_integration.py
git commit -m "test: run storage and login against a real Postgres when one is provided"
```

---

### Task 5: 上線（每一步都要使用者點頭）

這個 task 沒有程式碼，是部署檢查表。每個「問使用者」都要等到明確同意才做。

（最後審查後改過順序：先建登入表、搬帳號，再 push。原本是部署後才搬，Render 預設開放註冊，那段空檔裡舊使用者用同一個 Email 重新註冊的話，舊帳號會被默默略過。）

- [ ] **Step 1: 交給使用者設 `DATABASE_URL`**

請使用者到 Render 後台 → `pfrs` 服務 → Environment，設 `DATABASE_URL` = Supabase `nutrilens` 專案 → Connect → **Session pooler** 的連線字串（埠 5432，密碼自己填；密碼裡有特殊字元要網址編碼，否則後端會拒絕啟動）。如果那裡已經有 Supabase 時期留下的 `DATABASE_URL`，確認它是 `nutrilens` 專案、是 pooler 網址。現在線上那版還不認得這個變數，設了不影響。Claude 不輸入密碼。

- [ ] **Step 2: 問使用者能不能建登入表、搬舊帳號**

同意後，對 `nutrilens` 專案（`jtvdvkvdckbunjkhzsbu`）執行 spec 第 4 節的 SQL（建 `auth_users` / `auth_sessions`＋開 RLS＋把 `auth.users` 的帳號搬進去）。可以透過 Supabase MCP 執行，或請使用者貼到 Supabase 的 SQL Editor。然後用 spec 第 4 節的三句回報：搬了幾個、沒搬幾個（含 `encrypted_password` 是 NULL 的）、有沒有撞名。

- [ ] **Step 3: 問使用者能不能 push**

同意後：`git push origin refs/heads/v0.0.9:refs/heads/v0.0.9`。

- [ ] **Step 4: 等部署完成後確認**

約 10 分鐘內（之前的經驗）：`curl -s https://pfrs.onrender.com/health`，確認 `"database": "postgres"`、`"auth_provider": "local-postgres"`、`deployed_commit` 是新的 commit。還是舊 commit 或 `sqlite`：回頭看 Step 1 有沒有設好，或請使用者看 Render 的部署 log 有沒有 `[ERROR]`（連不上或網址格式不對）。

用 Supabase MCP 的 `list_tables`（唯讀）確認七張表都在、`rls_enabled` 都是 true。

- [ ] **Step 5: 實際登入**

請使用者在 https://pfrs-frontend.onrender.com 用一個舊帳號（Email 當暱稱、原密碼）登入，確認看得到以前的紀錄和健康檔案；再註冊一個新暱稱、記一筆、等 Render 休眠後再打開，確認紀錄還在。

- [ ] **Step 6: 收尾**

更新記憶（`deployment-topology.md`、`local-sqlite-and-auth.md`）：Render 現在用 Supabase `nutrilens` 專案、本機用 SQLite；「不要用 Supabase」那條改成「只有 Render 用」。

---

## Self-Review 紀錄

- **Spec 對照**：選資料庫（Task 3）、`PostgresDatabase` 連線／佔位符／型別／重連／交易（Task 1）、建表與 RLS（Task 2）、搬帳號 SQL（Task 5 Step 4）、Render 設定與 `render.yaml`（Task 3 Step 7、Task 5 Step 1）、`/health`（Task 3 Step 4）、錯誤處理（Task 1、Task 3）、`reset_password.py`（Task 3 Step 5）、測試三層（Task 1–4）、上線順序（Task 5）、測試不連正式資料庫（Task 3 Step 6）。都有對應。
- **名稱一致**：`PostgresDatabase(url, connect=None)`、`DatabaseUnavailable`、`open_database(connect=None)`、`dialect`、`label`、`POSTGRES_TABLES`、`POSTGRES_AUTH_TABLES` 在各 task 用法一致。
- **Review Focus**：五項都各自有測試，標在上面。
