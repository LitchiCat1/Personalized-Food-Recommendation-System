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


if __name__ == "__main__":
    unittest.main()
