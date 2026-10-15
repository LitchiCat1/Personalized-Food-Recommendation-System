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
