"""帳號與登入 session 的存取。

帳號、密碼雜湊與登入 token 存在資料庫裡：本機是 SQLite，Render 是 Supabase 的 Postgres。
不依賴任何雲端登入服務。沒有資料庫時退回記憶體，只適合跑測試——重啟後帳號就不見了。
"""

from datetime import datetime, timezone
import threading
import uuid

from repositories.sqlite_db import SqliteDatabase, utc_iso


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


class EmailAlreadyRegistered(Exception):
    pass


class AuthRepository:
    def __init__(self, sql: SqliteDatabase | None = None):
        self.sql = sql
        self.use_sql = sql is not None
        self._lock = threading.Lock()
        self.mem_users: dict[str, dict] = {}
        self.mem_sessions: dict[str, dict] = {}
        if self.use_sql:
            self._init_tables()

    def _init_tables(self):
        if self.sql.dialect == "postgres":
            self.sql.executescript(POSTGRES_AUTH_TABLES)
            return
        # 只存 token 的 SHA-256，資料庫檔案外流也拿不到能用的 token
        self.sql.executescript(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES auth_users (id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions (user_id);
            """
        )

    def count_users(self) -> int:
        if self.use_sql:
            return int(self.sql.query_one("SELECT COUNT(*) AS n FROM auth_users")["n"])
        return len(self.mem_users)

    def get_user_by_email(self, email: str) -> dict | None:
        if self.use_sql:
            return self.sql.query_one("SELECT id, email, password_hash FROM auth_users WHERE email = ?", (email,))
        return next((user for user in self.mem_users.values() if user["email"] == email), None)

    def create_user(self, email: str, password_hash: str, user_id: str | None = None) -> dict:
        user = {"id": user_id or str(uuid.uuid4()), "email": email, "password_hash": password_hash}
        if self.use_sql:
            inserted = self.sql.execute(
                """
                INSERT INTO auth_users (id, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (user["id"], email, password_hash, utc_iso()),
            )
            if not inserted:
                raise EmailAlreadyRegistered(email)
            return user
        with self._lock:
            if self.get_user_by_email(email):
                raise EmailAlreadyRegistered(email)
            self.mem_users[user["id"]] = user
        return user

    def set_password(self, user_id: str, password_hash: str) -> None:
        """改密碼，並讓這個帳號所有已登入的裝置失效。"""
        if self.use_sql:
            with self.sql.transaction():
                self.sql.execute("UPDATE auth_users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
                self.sql.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            return
        with self._lock:
            if user_id in self.mem_users:
                self.mem_users[user_id]["password_hash"] = password_hash
            self.mem_sessions = {key: s for key, s in self.mem_sessions.items() if s["user_id"] != user_id}

    def create_session(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        if self.use_sql:
            with self.sql.transaction():
                # 順手清掉過期的，表才不會一直長大
                self.sql.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (utc_iso(),))
                self.sql.execute(
                    "INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                    (token_hash, user_id, utc_iso(expires_at), utc_iso()),
                )
            return
        with self._lock:
            now = datetime.now(timezone.utc)
            self.mem_sessions = {key: s for key, s in self.mem_sessions.items() if s["expires_at"] > now}
            self.mem_sessions[token_hash] = {"user_id": user_id, "expires_at": expires_at}

    def get_session_user(self, token_hash: str) -> dict | None:
        """token 有效就回傳 {id, email}；過期或登出過的都回 None。"""
        if self.use_sql:
            return self.sql.query_one(
                """
                SELECT u.id, u.email
                FROM auth_sessions s
                JOIN auth_users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, utc_iso()),
            )
        session = self.mem_sessions.get(token_hash)
        if not session or session["expires_at"] <= datetime.now(timezone.utc):
            return None
        user = self.mem_users.get(session["user_id"])
        return {"id": user["id"], "email": user["email"]} if user else None

    def delete_session(self, token_hash: str) -> None:
        if self.use_sql:
            self.sql.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
            return
        with self._lock:
            self.mem_sessions.pop(token_hash, None)
