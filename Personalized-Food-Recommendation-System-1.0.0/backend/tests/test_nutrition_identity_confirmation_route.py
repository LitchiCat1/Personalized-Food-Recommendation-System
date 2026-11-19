import unittest
from unittest.mock import patch

from repositories.nutrition_identity_confirmation_repository import NutritionIdentityConfirmationRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.nutrition_profile_service import profile_from_local_food

from test_api_routes import ApiTestBase


ITEM = {
    "item_id": "identity-http:0", "item_revision": 0, "name_zh": "菜葉",
    "confidence": 0.41, "weight_confidence": 0.6, "estimated_weight_g": 80,
    "food_state": "prepared", "preparation_method": "stir_fried",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [], "identity_confirmation_required": True,
}


class NutritionIdentityConfirmationRouteTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.sql = SqliteDatabase(":memory:")
        self.scan = NutritionScanContextRepository(self.sql)
        self.identity = NutritionIdentityConfirmationRepository(
            self.sql, scan_context_repository=self.scan)
        self.scan.save_scan_context(user_id="user-a", scan_id="identity-http",
                                    scan_revision=0, items=[ITEM], ttl_seconds=120)
        self.addCleanup(self.sql.close)

    def _body(self, **changes):
        body = {
            "scan_id": "identity-http", "scan_revision": 0,
            "item_id": ITEM["item_id"], "item_revision": 0,
            "name_zh": "青江菜", "idempotency_key": "identity-http-key",
        }
        body.update(changes)
        return body

    def test_route_requires_authentication_and_stays_disabled_by_default(self):
        self.assertEqual(self.client.post("/nutrition/identity/confirmation", json=self._body()).status_code, 401)
        with self.mock_auth("user-a"):
            response = self.client.post(
                "/nutrition/identity/confirmation", json=self._body(), headers=self.auth_headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "feature_disabled")

    def test_authenticated_name_decision_is_exact_atomic_and_idempotent(self):
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_identity_confirmation_repository", self.identity), \
                patch.object(self.app_module, "nutrition_scan_context_repository", self.scan), \
                patch.object(self.app_module, "nutrition_identity_confirmation_route_enabled", True):
            forged = self.client.post(
                "/nutrition/identity/confirmation", json=self._body(confirmed=True),
                headers=self.auth_headers())
            self.assertEqual(forged.status_code, 400)
            self.assertEqual(forged.get_json()["error"]["code"], "invalid_request")
            self.assertIsNone(self.scan.get_scan_context(
                user_id="user-a", scan_id="identity-http", scan_revision=1))

            response = self.client.post(
                "/nutrition/identity/confirmation", json=self._body(), headers=self.auth_headers())
            replay = self.client.post(
                "/nutrition/identity/confirmation", json=self._body(), headers=self.auth_headers())

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["decision"], "correct")
        self.assertEqual(response.get_json()["issued_scan_revision"], 1)
        self.assertEqual(response.get_json()["name_zh"], "青江菜")
        self.assertNotIn("confidence", response.get_json())
        self.assertIn(response.get_json()["local_lookup"]["status"], {
            "matched", "source_conflict", "incomplete_profile", "incompatible", "no_local_mapping",
        })
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.get_json()["confirmation_id"], response.get_json()["confirmation_id"])
        self.assertTrue(replay.get_json()["replayed"])
        context = self.scan.get_scan_context(
            user_id="user-a", scan_id="identity-http", scan_revision=1)
        self.assertEqual(context["items"][0]["identity_confirmation_source"], "user")

    def test_authenticated_owner_cannot_confirm_another_users_scan(self):
        with self.mock_auth("user-b"), \
                patch.object(self.app_module, "nutrition_identity_confirmation_repository", self.identity), \
                patch.object(self.app_module, "nutrition_scan_context_repository", self.scan), \
                patch.object(self.app_module, "nutrition_identity_confirmation_route_enabled", True):
            response = self.client.post(
                "/nutrition/identity/confirmation", json=self._body(), headers=self.auth_headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "wrong_user")

    def test_confirmation_returns_only_the_new_revision_local_hit(self):
        profile = profile_from_local_food({
            "unit": "per 100g", "calories": 120, "protein": 4,
            "fat": 2, "carbs": 20, "sodium": 80, "fiber": 3,
        })
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_identity_confirmation_repository", self.identity), \
                patch.object(self.app_module, "nutrition_scan_context_repository", self.scan), \
                patch.object(self.app_module, "nutrition_identity_confirmation_route_enabled", True), \
                patch.object(self.app_module, "make_local_nutrition_lookup", return_value=lambda _item: {
                    "status": "matched", "nutrition_profile": profile,
                    "diagnostics": {"source": "TFDA"},
                }):
            response = self.client.post(
                "/nutrition/identity/confirmation", json=self._body(), headers=self.auth_headers())

        self.assertEqual(response.status_code, 202)
        local_item = response.get_json()["local_lookup"]["item"]
        self.assertEqual(local_item["origin"], "local")
        self.assertEqual(local_item["item_id"], ITEM["item_id"])
        self.assertEqual(local_item["item_revision"], 1)
        self.assertEqual(local_item["recognition_context"]["name_zh"], "青江菜")
        self.assertEqual(local_item["portion"]["weight_g"], 80)
        self.assertEqual(local_item["portion"]["values"]["calories"], 96)


if __name__ == "__main__":
    unittest.main()
