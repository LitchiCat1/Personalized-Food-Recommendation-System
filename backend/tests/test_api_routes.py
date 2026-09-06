import base64
import importlib
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

from services.app_time_service import app_now
from unittest.mock import patch


class ApiRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["SUPABASE_AUTH_REQUIRED"] = "true"
        os.environ["SUPABASE_URL"] = "https://example.supabase.co"
        os.environ["SUPABASE_PUBLISHABLE_KEY"] = "test-publishable-key"
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.app_module.app.config["TESTING"] = True

    def setUp(self):
        self.client = self.app_module.app.test_client()
        self.app_module._mem_users.clear()
        self.app_module._mem_records.clear()
        self.app_module._mem_custom_foods.clear()
        self.app_module.storage.upsert_user({"user_id": "user-a", "name": "User A", "health_conditions": ["hypertension"], "allergens": ["egg"]})

    def auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    def mock_auth(self, user_id="user-a"):
        return patch.object(self.app_module, "verify_supabase_user", return_value={"id": user_id})

    def test_medical_metadata_route_exposes_governance_metadata(self):
        response = self.client.get("/medical-metadata")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("disease_rules", data)
        self.assertIn("allergen_taxonomy", data)
        self.assertGreater(data["disease_rules"]["count"], 0)
        self.assertGreater(data["allergen_taxonomy"]["count"], 0)

    def test_user_route_rejects_missing_token_when_auth_required(self):
        response = self.client.get("/user/user-a")
        self.assertEqual(response.status_code, 401)

    def test_user_route_rejects_cross_user_access(self):
        with self.mock_auth("user-a"):
            response = self.client.get("/user/user-b", headers=self.auth_headers())
        self.assertEqual(response.status_code, 403)

    def test_vision_food_accepts_raw_base64_and_browser_data_uri(self):
        image_base64 = base64.b64encode(b"\x89PNG\r\n\x1a\nmock-image").decode("ascii")

        for image_payload in (image_base64, f"data:image/png;base64,{image_base64}"):
            with self.subTest(data_uri=image_payload.startswith("data:")):
                with self.mock_auth("user-a"):
                    with patch.object(self.app_module, "get_gemini_api_keys", return_value=["test-key"]):
                        with patch.object(
                            self.app_module,
                            "call_gemini_food_recognition_with_rotation",
                            return_value={"items": []},
                        ) as recognize:
                            response = self.client.post(
                                "/predict/vision-food",
                                json={"image": image_payload, "user_id": "user-a"},
                                headers=self.auth_headers(),
                            )

                self.assertEqual(response.status_code, 200)
                recognize.assert_called_once_with(image_base64, "image/png", ["test-key"])

    def test_vision_food_rejects_invalid_image_payloads(self):
        invalid_payloads = ("", "not-base64", "data:text/plain;base64,SGVsbG8=")

        for image_payload in invalid_payloads:
            with self.subTest(image_payload=image_payload):
                response = self.client.post("/predict/vision-food", json={"image": image_payload})
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())

    def test_menu_photo_route_exposes_recognition_failure(self):
        image_base64 = base64.b64encode(b"\x89PNG\r\n\x1a\nmenu-image").decode("ascii")
        parsed = {
            "items": [],
            "recognition_status": "error",
            "recognition_error": "Gemini HTTP 429: quota exceeded",
        }

        with self.mock_auth("user-a"):
            with patch.object(self.app_module, "parse_menu_image_with_gemini", return_value=parsed):
                response = self.client.post(
                    "/restaurant/menu",
                    json={
                        "restaurant_id": "menu-test-restaurant",
                        "name": "測試菜單辨識店",
                        "user_id": "user-a",
                        "menu_image": image_base64,
                    },
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["recommended_items"], [])
        self.assertEqual(data["menu_recognition"]["recognition_status"], "error")
        self.assertIn("429", data["menu_recognition"]["recognition_error"])

    def test_record_route_deduplicates_client_record_id(self):
        payload = {
            "user_id": "user-a",
            "client_record_id": "client-record-1",
            "meal_type": "午餐",
            "foods": [{"name": "apple", "calories": 80}],
            "total_calories": 80,
            "source": "manual",
        }

        with self.mock_auth("user-a"):
            first_response = self.client.post("/record", json=payload, headers=self.auth_headers())
            second_response = self.client.post("/record", json=payload, headers=self.auth_headers())
            records_response = self.client.get("/records/user-a", headers=self.auth_headers())

        self.assertEqual(first_response.status_code, 201)
        self.assertFalse(first_response.get_json()["deduplicated"])
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.get_json()["deduplicated"])
        self.assertEqual(len(records_response.get_json()["records"]), 1)

    def test_record_route_generates_client_record_id_when_missing(self):
        payload = {
            "user_id": "user-a",
            "meal_type": "午餐",
            "foods": [{"name": "apple", "calories": 80}],
            "total_calories": 80,
            "source": "manual",
        }

        with self.mock_auth("user-a"):
            response = self.client.post("/record", json=payload, headers=self.auth_headers())

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertFalse(data["deduplicated"])
        self.assertTrue(data["record"]["client_record_id"].startswith("server_record_"))

    def test_record_route_creates_today_and_historical_manual_records(self):
        local_timezone = timezone(timedelta(hours=8))
        local_now = datetime.now(local_timezone)
        timestamps = (
            local_now.replace(microsecond=123000).isoformat(),
            (local_now - timedelta(days=45)).replace(microsecond=456000).isoformat(),
        )

        for index, timestamp in enumerate(timestamps):
            with self.subTest(timestamp=timestamp):
                payload = {
                    "user_id": "user-a",
                    "client_record_id": f"manual-date-{index}",
                    "timestamp": timestamp,
                    "foods": [{
                        "name": "  手動豆漿  ",
                        "calories": 120,
                        "protein": 8.5,
                        "carbs": 10,
                        "fat": 4,
                        "sodium": 95,
                        "fiber": 2,
                    }],
                    "source": "manual",
                }
                with self.mock_auth("user-a"):
                    response = self.client.post("/record", json=payload, headers=self.auth_headers())

                self.assertEqual(response.status_code, 201)
                record = response.get_json()["record"]
                self.assertEqual(record["timestamp"], timestamp)
                self.assertEqual(record["foods"][0]["name"], "手動豆漿")
                self.assertEqual(record["source"], "manual")
                self.assertEqual(record["meal_type"], "午餐")

    def test_record_route_rejects_future_calendar_date(self):
        local_timezone = timezone(timedelta(hours=8))
        future_timestamp = (datetime.now(local_timezone) + timedelta(days=1)).isoformat()
        payload = {
            "user_id": "user-a",
            "client_record_id": "future-manual-record",
            "timestamp": future_timestamp,
            "foods": [{"name": "未來餐點", "calories": 100}],
            "source": "manual",
        }

        with self.mock_auth("user-a"):
            response = self.client.post("/record", json=payload, headers=self.auth_headers())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "紀錄日期不得晚於今天")
        self.assertIsNone(self.app_module.storage.get_record_by_client_record_id("user-a", "future-manual-record"))

    def test_record_route_rejects_invalid_food_values(self):
        invalid_foods = (
            [{"name": "   ", "calories": 80}],
            [{"name": "豆漿", "calories": "not-a-number"}],
            [{"name": "豆漿", "sodium": -1}],
        )

        for index, foods in enumerate(invalid_foods):
            with self.subTest(foods=foods):
                with self.mock_auth("user-a"):
                    response = self.client.post(
                        "/record",
                        json={
                            "user_id": "user-a",
                            "client_record_id": f"invalid-create-{index}",
                            "foods": foods,
                            "source": "manual",
                        },
                        headers=self.auth_headers(),
                    )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())

    def _seed_places(self, names):
        return [
            {
                "restaurant_id": f"google_{name}",
                "name": name,
                "address": "台北",
                "tags": ["Google Places"],
            }
            for name in names
        ]

    def _seed_menu(self, name, address, text):
        return {
            "items": [
                {
                    "item_id": f"{name}_{index}",
                    "name": f"{name} 餐點{index}",
                    "price": 110 + index,
                    "calories": 500,
                    "protein": 25,
                    "carbs": 55,
                    "fat": 16,
                    "sugar": 3,
                    "saturated_fat": 4,
                    "trans_fat": 0,
                    "fiber": 5,
                    "sodium": 600,
                }
                for index in range(4)
            ]
        }

    def test_week_seed_route_uses_real_venues_and_clears(self):
        with self.mock_auth("user-a"):
            self.client.post(
                "/user",
                json={"user_id": "user-a", "name": "Seed User", "height": 170, "weight": 65, "age": 25},
                headers=self.auth_headers(),
            )
            with patch.object(
                self.app_module, "fetch_google_places_restaurants",
                lambda *a, **k: self._seed_places(["真實店家 A", "真實店家 B"]),
            ), patch.object(self.app_module, "enrich_restaurant_with_gemini", self._seed_menu):
                response = self.client.post(
                    "/seed/week-records/user-a",
                    json={"source": "recommend", "days": 7, "budget": 150},
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 201)
        summary = response.get_json()
        self.assertEqual(summary["days"], 7)
        self.assertEqual(summary["records"], 21)
        self.assertEqual(summary["data_source"], "google_places")

        with self.mock_auth("user-a"):
            records = self.client.get("/records/user-a?limit=500", headers=self.auth_headers()).get_json()["records"]
        by_day = {}
        for record in records:
            by_day.setdefault(record["timestamp"][:10], []).append(record["foods"][0]["name"])
        self.assertEqual(len(by_day), 7)
        self.assertEqual(len({tuple(sorted(v)) for v in by_day.values()}), 7)
        # 直接讀菜單品項才留得住纖維
        self.assertGreater(records[0]["foods"][0]["fiber"], 0)

        with self.mock_auth("user-a"):
            cleared = self.client.delete(
                "/seed/week-records/user-a?source=recommend&days=7", headers=self.auth_headers()
            )
        self.assertEqual(cleared.get_json()["removed"], 21)

    def test_week_seed_route_reports_why_instead_of_seeding_fake_data(self):
        """拿不到真實菜單時要明講原因，不能改用本地模擬目錄充數。"""
        with self.mock_auth("user-a"):
            self.client.post(
                "/user",
                json={"user_id": "user-a", "name": "Seed User", "height": 170, "weight": 65, "age": 25},
                headers=self.auth_headers(),
            )
            with patch.object(
                self.app_module, "fetch_google_places_restaurants", lambda *a, **k: []
            ):
                response = self.client.post(
                    "/seed/week-records/user-a",
                    json={"source": "recommend", "days": 7},
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 409)
        self.assertIn("搜尋不到店家", response.get_json()["error"])

    def test_week_seed_route_rejects_unknown_source(self):
        with self.mock_auth("user-a"):
            response = self.client.post(
                "/seed/week-records/user-a", json={"source": "curated"}, headers=self.auth_headers()
            )
        self.assertEqual(response.status_code, 400)

    def test_week_seed_delete_still_accepts_the_retired_curated_source(self):
        """灌入只剩 recommend，但清除按鈕仍要能刪掉舊版 curated 留下的紀錄。"""
        with self.mock_auth("user-a"):
            response = self.client.delete(
                "/seed/week-records/user-a?source=curated&days=7", headers=self.auth_headers()
            )
        self.assertEqual(response.status_code, 200)

    def test_record_route_recalculates_totals_instead_of_trusting_payload(self):
        payload = {
            "user_id": "user-a",
            "client_record_id": "manual-recalculated-record",
            "foods": [
                {
                    "name": "炸豆腐",
                    "calories": 120,
                    "protein": 8.5,
                    "carbs": 10,
                    "refined_sugar": 1.5,
                    "fat": 4,
                    "saturated_fat": 0.8,
                    "trans_fat": 0,
                    "sodium": 95,
                    "fiber": 2,
                    "is_fried": True,
                },
                {
                    "name": "香蕉",
                    "calories": 90,
                    "protein": 1,
                    "carbs": 23,
                    "sugar": 4.2,
                    "fat": 0.3,
                    "saturated_fat": 0.1,
                    "trans_fat": 0,
                    "sodium": 1,
                    "fiber": 2.6,
                    "is_fried": False,
                },
            ],
            "total_calories": 9999,
            "total_protein": 9999,
            "total_sodium": 9999,
            "source": "manual",
        }

        with self.mock_auth("user-a"):
            response = self.client.post("/record", json=payload, headers=self.auth_headers())

        self.assertEqual(response.status_code, 201)
        record = response.get_json()["record"]
        self.assertEqual(record["total_calories"], 210)
        self.assertEqual(record["total_protein"], 9.5)
        self.assertEqual(record["total_sodium"], 96)
        self.assertEqual(record["total_fiber"], 4.6)
        self.assertEqual(record["total_sugar"], 5.7)
        self.assertEqual(record["total_saturated_fat"], 0.9)
        self.assertEqual(record["total_trans_fat"], 0)
        self.assertTrue(record["contains_fried_food"])
        self.assertEqual(record["foods"][0]["sugar"], 1.5)

    def test_record_route_keeps_existing_scanner_creation_compatible(self):
        payload = {
            "user_id": "user-a",
            "client_record_id": "scanner-compatible-record",
            "meal_type": "點心",
            "foods": [{"name": "掃描蘋果", "calories": 80, "source": "camera"}],
            "total_calories": 999,
            "source": "camera",
        }

        with self.mock_auth("user-a"):
            response = self.client.post("/record", json=payload, headers=self.auth_headers())

        self.assertEqual(response.status_code, 201)
        record = response.get_json()["record"]
        self.assertEqual(record["meal_type"], "點心")
        self.assertEqual(record["source"], "camera")
        self.assertEqual(record["total_calories"], 80)
        self.assertTrue(record["timestamp"])

    def test_records_route_paginates_in_newest_first_order(self):
        for index in range(1, 4):
            self.app_module.storage.insert_record({
                "user_id": "user-a",
                "client_record_id": f"record-{index}",
                "timestamp": f"2026-08-0{index}T12:00:00Z",
                "foods": [],
                "total_calories": index * 100,
            })

        with self.mock_auth("user-a"):
            first_page = self.client.get("/records/user-a?limit=2&offset=0", headers=self.auth_headers())
            second_page = self.client.get("/records/user-a?limit=2&offset=2", headers=self.auth_headers())

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual([record["client_record_id"] for record in first_page.get_json()["records"]], ["record-3", "record-2"])
        self.assertEqual([record["client_record_id"] for record in second_page.get_json()["records"]], ["record-1"])

    def test_record_update_trims_names_and_recalculates_totals(self):
        self.app_module.storage.insert_record({
            "user_id": "user-a",
            "client_record_id": "editable-record",
            "timestamp": "2026-08-03T12:00:00Z",
            "meal_type": "午餐",
            "foods": [{"name": "原始名稱", "calories": 80}],
            "total_calories": 80,
            "source": "nutrition-label",
        })
        payload = {
            "foods": [
                {"name": "  豆漿  ", "calories": 120, "protein": 8.5, "carbs": 10, "fat": 4, "sodium": 95, "fiber": 2},
                {"name": "香蕉", "calories": 90, "protein": 1, "carbs": 23, "fat": 0.3, "sodium": 1, "fiber": 2.6},
            ],
            "total_calories": 9999,
        }

        with self.mock_auth("user-a"):
            response = self.client.patch(
                "/records/user-a/editable-record",
                json=payload,
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        record = response.get_json()["record"]
        self.assertEqual(record["foods"][0]["name"], "豆漿")
        self.assertEqual(record["total_calories"], 210)
        self.assertEqual(record["total_protein"], 9.5)
        self.assertEqual(record["total_fiber"], 4.6)
        self.assertEqual(record["source"], "nutrition-label")

    def test_record_update_rejects_blank_names_invalid_numbers_and_negatives(self):
        self.app_module.storage.insert_record({
            "user_id": "user-a",
            "client_record_id": "invalid-record",
            "timestamp": "2026-08-03T12:00:00Z",
            "foods": [{"name": "原始名稱", "calories": 80}],
        })
        invalid_foods = (
            [{"name": "   ", "calories": 80}],
            [{"name": "豆漿", "calories": "not-a-number"}],
            [{"name": "豆漿", "calories": -1}],
        )

        for foods in invalid_foods:
            with self.subTest(foods=foods):
                with self.mock_auth("user-a"):
                    response = self.client.patch(
                        "/records/user-a/invalid-record",
                        json={"foods": foods},
                        headers=self.auth_headers(),
                    )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())

        record = self.app_module.storage.get_record_by_client_record_id("user-a", "invalid-record")
        self.assertEqual(record["foods"][0]["name"], "原始名稱")

    def test_record_delete_removes_only_authenticated_users_record(self):
        for user_id in ("user-a", "user-b"):
            self.app_module.storage.insert_record({
                "user_id": user_id,
                "client_record_id": "shared-client-id",
                "timestamp": "2026-08-03T12:00:00Z",
                "foods": [{"name": user_id, "calories": 80}],
            })

        with self.mock_auth("user-a"):
            response = self.client.delete(
                "/records/user-a/shared-client-id",
                headers=self.auth_headers(),
            )
            records_response = self.client.get("/records/user-a", headers=self.auth_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(records_response.get_json()["records"], [])
        self.assertIsNotNone(self.app_module.storage.get_record_by_client_record_id("user-b", "shared-client-id"))

    def test_record_mutations_reject_cross_user_access(self):
        self.app_module.storage.insert_record({
            "user_id": "user-b",
            "client_record_id": "private-record",
            "timestamp": "2026-08-03T12:00:00Z",
            "foods": [{"name": "私有紀錄", "calories": 80}],
        })

        with self.mock_auth("user-a"):
            update_response = self.client.patch(
                "/records/user-b/private-record",
                json={"foods": [{"name": "越權修改", "calories": 1}]},
                headers=self.auth_headers(),
            )
            delete_response = self.client.delete(
                "/records/user-b/private-record",
                headers=self.auth_headers(),
            )

        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertIsNotNone(self.app_module.storage.get_record_by_client_record_id("user-b", "private-record"))

    def test_custom_food_route_scopes_food_to_authenticated_user(self):
        payload = {
            "user_id": "user-a",
            "name_zh": "油炸測試豆漿",
            "nutrition_per_100g": {
                "calories": 42,
                "protein": 3.4,
                "fat": 1.8,
                "carbs": 4.1,
                "sugar": 1.2,
                "sodium": 5,
            },
        }

        with self.mock_auth("user-a"):
            response = self.client.post("/custom-food", json=payload, headers=self.auth_headers())

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["food"]["user_id"], "user-a")
        self.assertTrue(data["food"]["is_fried"])
        self.assertIn("owner_key", data["food"])

        with self.mock_auth("user-a"):
            list_response = self.client.get("/custom-foods?user_id=user-a", headers=self.auth_headers())

        self.assertEqual(list_response.status_code, 200)
        list_data = list_response.get_json()
        self.assertEqual(list_data["count"], 1)
        self.assertEqual(list_data["foods"][0]["user_id"], "user-a")

    def test_map_food_recommend_requires_google_places_key(self):
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "", "GOOGLE_MAPS_API_KEY": ""}, clear=False):
            with self.mock_auth("user-a"):
                response = self.client.get("/map-food-recommend/user-a?budget=150&lat=24.9890&lng=121.3443&radius_km=3&category=all", headers=self.auth_headers())
        self.assertEqual(response.status_code, 503)

    def test_health_metadata_in_map_food_route(self):
        fake_restaurants = [
            {
                "restaurant_id": "google_place_1",
                "name": "Healthy Bento",
                "lat": 24.9891,
                "lng": 121.3444,
                "address": "Taipei",
                "phone": "",
                "google_place_id": "place_1",
                "distance_km": 0.02,
                "tags": ["Google Places", "healthy"],
                "price_level": 1,
                "is_open": True,
                "rating": 4.3,
                "user_ratings_total": 25,
                "match_score": 88,
                "data_source": "google_places",
                "nutrition_available": False,
                "recommended_items": [
                    {
                        "restaurant_id": "google_place_1",
                        "restaurant_name": "Healthy Bento",
                        "item_name": "Chicken bowl",
                        "price": 120,
                        "calories": 0,
                        "protein": 0,
                        "carbs": 0,
                        "fat": 0,
                        "sodium": 0,
                        "match_score": 88,
                        "nutrition_available": False,
                        "reasons": ["Google Places result"],
                    }
                ],
                "filtered_items": [],
            }
        ]

        with self.mock_auth("user-a"):
            with patch("services.healthy_food_service.fetch_google_places_restaurants", return_value=fake_restaurants):
                response = self.client.get("/map-food-recommend/user-a?budget=150&lat=24.9890&lng=121.3443&radius_km=3&category=all", headers=self.auth_headers())

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["data_source"], "google_places")

    def test_restaurant_summary_uses_profile_disease_and_current_over_target_progress(self):
        self.app_module.storage.upsert_user(
            {
                "user_id": "user-a",
                "name": "User A",
                "health_conditions": ["hypertension"],
                "allergens": [],
                "daily_calorie_target": 1800,
            }
        )
        self.app_module.storage.insert_record(
            {
                "user_id": "user-a",
                "client_record_id": "over-target-record",
                "timestamp": app_now().isoformat(),
                "total_calories": 1900,
                "total_protein": 80,
                "total_carbs": 200,
                "total_fat": 60,
                "total_sodium": 2300,
                "total_fiber": 12,
            }
        )
        fake_summary = {
            "restaurant_type": "便當店",
            "likely_foods": ["便當"],
            "recommended_foods": [{"name": "少醬蔬菜餐", "reason": "鈉已超標"}],
            "price_range_twd": {"min": 100, "max": 150},
            "budget_fit": "適合",
            "health_tips": ["醬汁另外放"],
            "confidence": "medium",
            "source_note": "test",
        }

        with self.mock_auth("user-a"):
            with patch.object(self.app_module, "build_restaurant_ai_summary", return_value=fake_summary) as build_summary:
                response = self.client.post(
                    "/map-food-recommend/user-a/restaurant-summary",
                    json={"restaurant": {"name": "Healthy Bento"}, "budget": 150, "category": "bento"},
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 200)
        args = build_summary.call_args.args
        self.assertEqual(args[3], ["hypertension"])
        self.assertEqual(args[4]["status"]["sodium"], "over")
        self.assertEqual(args[4]["over_by"]["sodium"], 300)
        self.assertIn("hypertension", args[5])


if __name__ == "__main__":
    unittest.main()
