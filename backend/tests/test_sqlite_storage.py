"""本機 SQLite 版的資料存取。

API 測試跑的是記憶體版本；這裡把同一組操作對 SQLite 跑一次，
確認 SQL 寫得對、JSON 與時間存進去讀出來都還是原樣。
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from repositories.auth_repository import AuthRepository
from repositories.sqlite_db import SqliteDatabase, default_database_path, resolve_database_path, utc_iso
from repositories.storage import StorageRepository
from services.app_time_service import app_now
from test_api_routes import ApiTestBase


def sqlite_storage(path=":memory:"):
    return StorageRepository(None, False, {}, [], [], sql=SqliteDatabase(path))


def meal(client_record_id, day_offset=0, calories=500, name="滷肉飯"):
    stamp = (app_now() - timedelta(days=day_offset)).replace(tzinfo=None).strftime("%Y-%m-%dT12:00:00")
    return {
        "user_id": "user-a",
        "client_record_id": client_record_id,
        "timestamp": stamp,
        "meal_type": "午餐",
        "foods": [{"name": name, "calories": calories, "sodium": 800, "is_fried": False}],
        # 跟 /record 一樣先把總量算好；趨勢是直接加總這些欄位
        "total_calories": calories,
        "total_sodium": 800,
        "source": "manual",
    }


class SqliteDatabasePathTests(unittest.TestCase):
    def test_default_location_is_outside_the_project(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\someone\AppData\Local"}, clear=True):
            self.assertEqual(resolve_database_path(), default_database_path())
            self.assertIn("NutriLens", resolve_database_path())

    def test_empty_setting_turns_the_database_off(self):
        with patch.dict(os.environ, {"DATABASE_PATH": "  "}, clear=True):
            self.assertIsNone(resolve_database_path())

    def test_timestamps_have_a_fixed_width_so_strings_sort_like_times(self):
        whole_second = datetime(2026, 10, 9, 3, 0, 0, tzinfo=timezone.utc)
        later = whole_second + timedelta(microseconds=1)
        self.assertEqual(len(utc_iso(whole_second)), len(utc_iso(later)))
        self.assertLess(utc_iso(whole_second), utc_iso(later))

    def test_data_survives_closing_and_reopening_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "sub", "nutrilens.db")
            first = sqlite_storage(path)
            first.upsert_user({"user_id": "user-a", "name": "小明"})
            first.insert_record(meal("r1"))
            first.sql.close()

            reopened = sqlite_storage(path)
            self.assertEqual(reopened.get_user("user-a")["name"], "小明")
            self.assertEqual(len(reopened.get_records("user-a")), 1)
            reopened.sql.close()


class SqliteStorageTests(unittest.TestCase):
    def setUp(self):
        self.storage = sqlite_storage()

    def test_user_profile_round_trip(self):
        self.storage.upsert_user({"user_id": "user-a", "name": "小明", "health_conditions": ["hypertension"]})
        self.storage.upsert_user({"user_id": "user-a", "name": "小明", "health_conditions": ["gout"]})

        self.assertEqual(self.storage.get_user("user-a")["health_conditions"], ["gout"])
        self.assertIsNone(self.storage.get_user("nobody"))
        self.assertEqual(self.storage.get_user("demo_user")["user_id"], "demo_user")

    def test_records_are_deduplicated_listed_and_filtered_by_day(self):
        self.storage.insert_record(meal("today"))
        again = self.storage.insert_record(meal("today"))
        self.storage.insert_record(meal("yesterday", day_offset=1))

        self.assertTrue(again["_deduplicated"])
        records = self.storage.get_records("user-a")
        self.assertEqual([r["client_record_id"] for r in records], ["today", "yesterday"])
        self.assertEqual(records[0]["foods"][0]["name"], "滷肉飯")
        self.assertEqual(records[0]["total_sodium"], 800)
        self.assertFalse(records[0]["contains_fried_food"])
        self.assertEqual(len(self.storage.get_today_records("user-a")), 1)
        self.assertEqual(len(self.storage.get_records("user-a", limit=1, offset=1)), 1)

    def test_an_old_non_unique_index_with_the_same_name_stops_startup(self):
        # CREATE UNIQUE INDEX IF NOT EXISTS 只看名字；同名的一般索引會讓它跳過，
        # 存紀錄的 ON CONFLICT 就沒有唯一索引可用，每一次儲存都會失敗
        db = SqliteDatabase(":memory:")
        db.executescript(
            """
            CREATE TABLE records (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, client_record_id TEXT NOT NULL,
                                  timestamp TEXT NOT NULL);
            CREATE INDEX idx_records_user_client_record ON records (user_id, client_record_id);
            """
        )
        with self.assertRaises(RuntimeError) as ctx:
            StorageRepository(None, False, {}, [], [], sql=db)
        self.assertIn("唯一索引", str(ctx.exception))

    def test_two_saves_of_the_same_record_at_once_do_not_fail(self):
        # 離線補傳和手動重按同時送出：兩邊都先查過、都沒查到，才各自寫入。
        # 先前後到的那個撞到唯一索引，變成 IntegrityError（500）。
        self.storage.insert_record(meal("same"))
        real_lookup = self.storage.get_record_by_client_record_id
        calls = []

        def lookup_before_the_other_write_landed(user_id, client_record_id):
            calls.append(client_record_id)
            return None if len(calls) == 1 else real_lookup(user_id, client_record_id)

        with patch.object(self.storage, "get_record_by_client_record_id", lookup_before_the_other_write_landed):
            again = self.storage.insert_record(meal("same", calories=999))

        self.assertTrue(again["_deduplicated"])
        self.assertEqual(again["total_calories"], 500, "回傳的是先寫進去的那筆")
        self.assertEqual(len(self.storage.get_records("user-a")), 1)

    def test_update_and_delete_return_the_record(self):
        self.storage.insert_record(meal("r1"))

        updated = self.storage.update_record({**meal("r1", calories=300, name="燙青菜")})
        self.assertEqual(updated["foods"][0]["name"], "燙青菜")
        self.assertEqual(self.storage.get_record_by_client_record_id("user-a", "r1")["total_calories"], 300)
        self.assertIsNone(self.storage.update_record(meal("missing")))

        deleted = self.storage.delete_record("user-a", "r1")
        self.assertEqual(deleted["client_record_id"], "r1")
        self.assertIsNone(self.storage.delete_record("user-a", "r1"))
        self.assertEqual(self.storage.get_records("user-a"), [])

    def test_history_sums_each_day(self):
        self.storage.insert_record(meal("a", calories=500))
        self.storage.insert_record(meal("b", calories=300))
        self.storage.insert_record(meal("c", day_offset=2, calories=700))
        self.storage.insert_record(meal("old", day_offset=30, calories=999))

        history = self.storage.get_history("user-a", 7)

        self.assertEqual([day["record_count"] for day in history], [1, 2])
        self.assertEqual(history[-1]["calories"], 800)
        self.assertEqual(history[-1]["sodium"], 1600)

    def test_custom_foods_upsert_by_owner(self):
        food = {"food_id": "f1", "user_id": "user-a", "name": "自製便當", "calories": 600}
        self.storage.upsert_custom_food(food)
        self.storage.upsert_custom_food({**food, "calories": 650})

        self.assertEqual(len(self.storage.get_custom_foods("user-a")), 1)
        self.assertEqual(self.storage.get_custom_food("f1", "user-a")["calories"], 650)
        self.assertIsNone(self.storage.get_custom_food("f1", "user-b"))

    def test_custom_foods_are_counted_without_loading_them(self):
        # /health 先前把每個人的自訂食品整份讀出來、解析 JSON，只為了數筆數
        for owner, food_id in (("user-a", "f1"), ("user-a", "f2"), ("user-b", "f1")):
            self.storage.upsert_custom_food({"food_id": food_id, "user_id": owner, "name": "便當"})
        with patch.object(self.storage, "get_custom_foods", side_effect=AssertionError("不該整份讀出來")):
            self.assertEqual(self.storage.count_custom_foods(), 3)

    def test_restaurant_menu_cache(self):
        items = [{"name": "雞腿便當", "price": 120}]
        self.storage.save_restaurant_menu("好吃便當", items, {"google_place_id": "abc"})
        self.storage.save_restaurant_menu("巷口麵店", items)

        self.assertEqual(self.storage.get_restaurant_menu(place_id="abc")["items"], items)
        self.assertEqual(self.storage.get_restaurant_menu(name="好吃便當")["venue_key"], "place:abc")
        self.assertEqual(self.storage.get_restaurant_menu(name="巷口麵店")["name"], "巷口麵店")
        self.assertEqual(self.storage.count_restaurant_menus(), 2)
        self.assertEqual(len(self.storage.list_restaurant_menus()), 2)
        self.assertEqual(self.storage.clear_restaurant_menus(), 2)
        self.assertIsNone(self.storage.get_restaurant_menu(place_id="abc"))

    def test_menu_failures_cool_down_and_expire(self):
        self.storage.mark_restaurant_menu_failure("place:a", "看不出菜單", cooldown_seconds=3600)
        self.storage.mark_restaurant_menu_failure("place:b", "看不出菜單", cooldown_seconds=-1)

        self.assertEqual(self.storage.active_restaurant_menu_failures(["place:a", "place:b", ""]), {"place:a"})
        self.storage.clear_restaurant_menu_failures()
        self.assertEqual(self.storage.active_restaurant_menu_failures(["place:a"]), set())


class SqliteApiTests(ApiTestBase):
    """登入、記一餐、看紀錄與趨勢，整條路都走 SQLite。"""

    def test_signup_then_record_and_read_back(self):
        sql = SqliteDatabase(":memory:")
        with patch.object(self.app_module, "storage", StorageRepository(None, False, {}, [], [], sql=sql)), \
                patch.object(self.app_module, "auth_repo", AuthRepository(sql)):
            self.app_module._auth_limiter.reset()
            session = self.client.post(
                "/auth/signup", json={"email": "sqlite@example.com", "password": "secret-pass"}
            ).get_json()
            user_id = session["user"]["id"]
            headers = {"Authorization": f"Bearer {session['access_token']}"}
            payload = {**meal("r1"), "user_id": user_id}

            first = self.client.post("/record", json=payload, headers=headers)
            second = self.client.post("/record", json=payload, headers=headers)
            listed = self.client.get(f"/records/{user_id}", headers=headers).get_json()["records"]
            history = self.client.get(f"/history/{user_id}?days=7", headers=headers)
            deleted = self.client.delete(f"/records/{user_id}/r1", headers=headers)

        self.assertEqual(first.status_code, 201)
        self.assertTrue(second.get_json()["deduplicated"])
        self.assertEqual(len(listed), 1)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(deleted.status_code, 200)


if __name__ == "__main__":
    unittest.main()
