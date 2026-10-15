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
from services.auth_service import (
    AuthError,
    hash_token,
    reset_password,
    sign_in,
    sign_out,
    sign_up,
    verify_access_token,
)

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


    def test_reconnects_after_the_server_drops_the_connection(self):
        # 模擬 Supabase 把閒置連線關掉：從另一條連線把這條砍掉，下一句要能自動重連
        pid = self.db.query_one("SELECT pg_backend_pid() AS pid")["pid"]
        other = PostgresDatabase(TEST_URL)
        try:
            other.execute("SELECT pg_terminate_backend(?)", (pid,))
        finally:
            other.close()
        self.assertEqual(self.db.query_one("SELECT 1 AS one"), {"one": 1})
        self.assertNotEqual(self.db.query_one("SELECT pg_backend_pid() AS pid")["pid"], pid)

    def test_records_for_one_day_use_like_with_a_percent_param(self):
        # 首頁的「今天」是用 timestamp LIKE '2026-10-15%' 查的
        self.storage.insert_record(self.meal("today", 500))
        yesterday = (app_now() - timedelta(days=1)).replace(tzinfo=None).strftime("%Y-%m-%dT12:00:00")
        self.storage.insert_record({**self.meal("yesterday", 300), "timestamp": yesterday})
        today = self.storage.get_today_records("user-a")
        self.assertEqual([record["client_record_id"] for record in today], ["today"])
        self.assertEqual(len(self.storage.get_records("user-a", yesterday[:10])), 1)

    def test_custom_foods_round_trip(self):
        food = {"food_id": "f1", "user_id": "user-a", "name": "阿嬤的滷蛋", "calories": 80}
        self.storage.upsert_custom_food(food)
        self.storage.upsert_custom_food({**food, "calories": 90})
        self.assertEqual(self.storage.get_custom_food("f1", "user-a")["calories"], 90)
        self.assertEqual([doc["food_id"] for doc in self.storage.get_custom_foods("user-a")], ["f1"])
        self.assertEqual(self.storage.get_custom_foods("someone-else"), [])

    def test_password_reset_signs_out_everywhere(self):
        sign_up(self.auth, "小華", "old")
        session = sign_in(self.auth, "小華", "old")
        reset_password(self.auth, "小華", "new")
        with self.assertRaises(AuthError):
            verify_access_token(self.auth, f"Bearer {session['access_token']}")
        with self.assertRaises(AuthError):
            sign_in(self.auth, "小華", "old")
        fresh = sign_in(self.auth, "小華", "new")
        sign_out(self.auth, f"Bearer {fresh['access_token']}")
        with self.assertRaises(AuthError):
            verify_access_token(self.auth, f"Bearer {fresh['access_token']}")

    def test_menus_can_be_listed_and_cleared(self):
        self.storage.save_restaurant_menu("阿明小吃", [{"name": "滷肉飯"}], {"google_place_id": "p1"})
        self.storage.save_restaurant_menu("阿華麵店", [{"name": "陽春麵"}], {"google_place_id": "p2"})
        self.assertEqual({menu["name"] for menu in self.storage.list_restaurant_menus()}, {"阿明小吃", "阿華麵店"})
        self.storage.clear_restaurant_menus()
        self.assertEqual(self.storage.count_restaurant_menus(), 0)


if __name__ == "__main__":
    unittest.main()
