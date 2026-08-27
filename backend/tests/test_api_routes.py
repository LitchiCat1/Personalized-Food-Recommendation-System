import base64
import importlib
import os
import sys
import unittest
from datetime import datetime, timezone
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
        self.app_module._mem_recommendation_feedback.clear()
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

    def test_custom_food_route_scopes_food_to_authenticated_user(self):
        payload = {
            "user_id": "user-a",
            "name_zh": "測試豆漿",
            "nutrition_per_100g": {"calories": 42, "protein": 3.4, "fat": 1.8, "carbs": 4.1, "sodium": 5},
        }

        with self.mock_auth("user-a"):
            response = self.client.post("/custom-food", json=payload, headers=self.auth_headers())

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["food"]["user_id"], "user-a")
        self.assertIn("owner_key", data["food"])

        with self.mock_auth("user-a"):
            list_response = self.client.get("/custom-foods?user_id=user-a", headers=self.auth_headers())

        self.assertEqual(list_response.status_code, 200)
        list_data = list_response.get_json()
        self.assertEqual(list_data["count"], 1)
        self.assertEqual(list_data["foods"][0]["user_id"], "user-a")

    def test_recommendation_feedback_round_trip(self):
        payload = {
            "action": "accepted",
            "item": {
                "label": "chicken_salad",
                "name_zh": "雞肉沙拉",
                "source": "tfda",
            },
        }

        with self.mock_auth("user-a"):
            create_response = self.client.post("/recommend/user-a/feedback", json=payload, headers=self.auth_headers())
            list_response = self.client.get("/recommend/user-a/feedback", headers=self.auth_headers())

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.get_json()["feedback"]["item_label"], "chicken_salad")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json()["count"], 1)

    def test_recommendation_feedback_rejects_invalid_action(self):
        with self.mock_auth("user-a"):
            response = self.client.post("/recommend/user-a/feedback", json={"action": "maybe", "item": {"label": "salad"}}, headers=self.auth_headers())
        self.assertEqual(response.status_code, 400)

    def test_map_food_recommend_requires_google_places_key(self):
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "", "GOOGLE_MAPS_API_KEY": ""}, clear=False):
            with self.mock_auth("user-a"):
                response = self.client.get("/map-food-recommend/user-a?budget=150&lat=24.9890&lng=121.3443&radius_km=3&category=all", headers=self.auth_headers())
        self.assertEqual(response.status_code, 503)

    def test_recommend_route_includes_medical_risk(self):
        with self.mock_auth("user-a"):
            response = self.client.get("/recommend/user-a", headers=self.auth_headers())
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("recommended", data)
        self.assertGreaterEqual(len(data["recommended"]), 0)

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
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
