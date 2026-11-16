"""SQLite-only database configuration shared by the app and maintenance scripts."""

import os

from repositories.sqlite_db import SqliteDatabase, resolve_database_path

__all__ = ["DatabaseUnavailable", "SQLITE_ONLY_MESSAGE", "open_database"]

SQLITE_ONLY_MESSAGE = (
    "此版本僅支援 SQLite；DATABASE_URL/PostgreSQL 已停用。請移除 DATABASE_URL，"
    "並用 DATABASE_PATH 指向既有 SQLite 資料庫。"
)


class DatabaseUnavailable(Exception):
    """The configured database cannot be opened safely."""


def open_database():
    """Return the configured SQLite database, or explicit memory mode."""
    if os.environ.get("DATABASE_URL", "").strip():
        raise DatabaseUnavailable(SQLITE_ONLY_MESSAGE)
    path = resolve_database_path()
    if not path:
        return None, "memory"
    return SqliteDatabase(path), f"SQLite {path}"
