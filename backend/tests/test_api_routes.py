import importlib
import os
import sys
import unittest
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
        self.app_module.storage.upsert_user({"user_id": "user-a", "name": "User A"})

    def auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    def mock_auth(self, user_id="user-a"):
        return patch.object(self.app_module, "verify_supabase_user", return_value={"id": user_id})

    def test_disease_rules_route_exposes_governance_metadata(self):
        response = self.client.get("/disease-rules")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertGreater(data["count"], 0)
        self.assertIn("medical_disclaimer", data)
        self.assertIn("review_status_counts", data)
        self.assertIn("limits", data["conditions"][0])

    def test_user_route_rejects_missing_token_when_auth_required(self):
        response = self.client.get("/user/user-a")

        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.get_json())

    def test_user_route_rejects_cross_user_access(self):
        with self.mock_auth("user-a"):
            response = self.client.get("/user/user-b", headers=self.auth_headers())

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.get_json())

    def test_record_route_deduplicates_client_record_id(self):
        payload = {
            "user_id": "user-a",
            "client_record_id": "client-record-1",
            "meal_type": "點心",
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
        records = records_response.get_json()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["client_record_id"], "client-record-1")

    def test_recommendation_feedback_round_trip(self):
        payload = {
            "action": "accepted",
            "item": {
                "label": "chicken_salad",
                "name_zh": "雞胸沙拉",
                "source": "tfda",
            },
        }

        with self.mock_auth("user-a"):
            create_response = self.client.post(
                "/recommend/user-a/feedback",
                json=payload,
                headers=self.auth_headers(),
            )
            list_response = self.client.get(
                "/recommend/user-a/feedback",
                headers=self.auth_headers(),
            )

        self.assertEqual(create_response.status_code, 201)
        created = create_response.get_json()["feedback"]
        self.assertEqual(created["user_id"], "user-a")
        self.assertEqual(created["action"], "accepted")
        self.assertEqual(created["item_label"], "chicken_salad")

        self.assertEqual(list_response.status_code, 200)
        listed = list_response.get_json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["feedback"][0]["item_label"], "chicken_salad")

    def test_recommendation_feedback_rejects_invalid_action(self):
        with self.mock_auth("user-a"):
            response = self.client.post(
                "/recommend/user-a/feedback",
                json={"action": "maybe", "item": {"label": "salad"}},
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("action", response.get_json()["error"])

    def test_map_food_recommend_requires_google_places_key(self):
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "", "GOOGLE_MAPS_API_KEY": ""}, clear=False):
            with self.mock_auth("user-a"):
                response = self.client.get(
                    "/map-food-recommend/user-a?budget=150&lat=24.9890&lng=121.3443&radius_km=3&category=all",
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 503)
        data = response.get_json()
        self.assertFalse(data["places_enabled"])
        self.assertIn("GOOGLE_PLACES_API_KEY", data["error"])

    def test_map_food_recommend_uses_google_places_source(self):
        fake_restaurants = [
            {
                "restaurant_id": "google_place_1",
                "name": "真實附近餐廳",
                "lat": 24.9891,
                "lng": 121.3444,
                "address": "桃園市龜山區示範路 1 號",
                "phone": "",
                "google_place_id": "place_1",
                "distance_km": 0.02,
                "tags": ["Google Places", "真實店家"],
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
                        "restaurant_name": "真實附近餐廳",
                        "item_name": "到店後選擇符合預算的餐點",
                        "price": 120,
                        "calories": 0,
                        "protein": 0,
                        "carbs": 0,
                        "fat": 0,
                        "sodium": 0,
                        "match_score": 88,
                        "nutrition_available": False,
                        "reasons": ["Google Places 找到的真實店家"],
                    }
                ],
                "filtered_items": [],
            }
        ]

        with self.mock_auth("user-a"):
            with patch("services.healthy_food_service.fetch_google_places_restaurants", return_value=fake_restaurants):
                response = self.client.get(
                    "/map-food-recommend/user-a?budget=150&lat=24.9890&lng=121.3443&radius_km=3&category=all",
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["data_source"], "google_places")
        self.assertFalse(data["nutrition_available"])
        self.assertEqual(data["restaurants"][0]["name"], "真實附近餐廳")

    def test_restaurant_summary_route_returns_fixed_summary(self):
        summary = {
            "restaurant_type": "滷味小吃",
            "likely_foods": ["滷味", "豆干", "青菜"],
            "price_range_twd": {"min": 80, "max": 150},
            "budget_fit": "適合",
            "health_tips": ["少鹽", "湯不要喝"],
            "confidence": "medium",
            "source_note": "Google Places + Gemini 推測，非店家正式菜單；實際品項與價格請以店家現場為準。",
        }

        with self.mock_auth("user-a"):
            with patch("app.build_restaurant_ai_summary", return_value=summary):
                response = self.client.post(
                    "/map-food-recommend/user-a/restaurant-summary",
                    json={"budget": 150, "category": "小吃", "restaurant": {"name": "測試滷味", "tags": ["Google Places"]}},
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["summary"]
        self.assertEqual(data["restaurant_type"], "滷味小吃")
        self.assertEqual(data["price_range_twd"]["max"], 150)
        self.assertEqual(data["budget_fit"], "適合")


if __name__ == "__main__":
    unittest.main()
