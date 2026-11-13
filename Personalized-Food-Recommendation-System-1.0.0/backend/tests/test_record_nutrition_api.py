"""Offline integration checks for nullable records and client capability gates."""

import copy
import importlib
import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ["NUTRILENS_SKIP_LOCAL_ENV"] = "1"
os.environ["DATABASE_PATH"] = ""
for _name in (
    "DATABASE_URL", "MONGODB_URI", "MONGO_URI", "NUTRILENS_TEST_DATABASE_URL",
    "AI_BASE_URL", "AI_MODEL", "AI_API_KEYS", "AI_RELAY_KEYS_FILE",
):
    os.environ.pop(_name, None)

from services.app_time_service import app_now


def manual_food(identifier="known", **overrides):
    return {
        "item_id": identifier, "name": "Manual bowl", "weight_g": 150,
        "portion_source": "user_weighed",
        "user_entered_nutrients": {
            "calories": 200, "protein": 10, "carbs": 20, "fat": 5,
            "sodium": None, "fiber": 2, "sugar": 0, "saturated_fat": 1,
            "trans_fat": {"value": "0.1", "unit": "g", "comparison": "less_than"},
        },
        **overrides,
    }


def unresolved_food(identifier="unknown"):
    return {"item_id": identifier, "name": "Manual bowl", "weight_g": None,
            "portion_source": "unknown"}


class RecordNutritionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["AUTH_REQUIRED"] = "true"
        sys.modules.pop("app", None)
        cls.module = importlib.import_module("app")
        cls.module.app.config["TESTING"] = True

    def setUp(self):
        self.client = self.module.app.test_client()
        self.module._mem_users.clear()
        self.module._mem_records.clear()
        self.module._mem_custom_foods.clear()
        self.module._general_limiter.reset()
        self.module._paid_api_limiter.reset()
        self.module.storage.upsert_user({
            "user_id": "nutrition-user", "name": "Contract test",
            "health_conditions": ["hypertension"], "allergens": [],
            "height": 170, "weight": 65, "age": 30,
        })
        self.auth = patch.object(self.module, "verify_access_token",
                                 return_value={"id": "nutrition-user"})
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.headers = {"Authorization": "Bearer offline-test-token"}

    def payload(self, **overrides):
        return {
            "user_id": "nutrition-user", "client_record_id": "nutrition-record",
            "timestamp": app_now().isoformat(), "nutrition_contract_version": 2,
            "foods": [manual_food(), unresolved_food()],
            "nutrition_context": {
                "scan_id": "client-scan",
                "recognition_context": {
                    "items": [{"item_id": "known"}, {"item_id": "unknown"}],
                    "uncertainty_notes": ["Unweighed background food"],
                },
            },
            **overrides,
        }

    def post_record(self, payload=None):
        return self.client.post("/record", json=self.payload() if payload is None else payload,
                                headers=self.headers)

    def save_record(self, payload=None):
        response = self.post_record(payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["record"]

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.get_json())
        self.assertEqual(response.get_json()["error_code"], code)
        self.assertTrue(response.get_json()["error"])

    def patch_record(self, foods, revision=0, **extra):
        return self.client.patch("/records/nutrition-user/nutrition-record", json={
            "nutrition_contract_version": 2, "base_revision": revision,
            "foods": foods, **extra,
        }, headers=self.headers)

    def test_preview_and_save_agree_without_preview_writing(self):
        payload = self.payload()
        preview = self.client.post("/record/preview", json=payload, headers=self.headers)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual(self.module.storage.get_records("nutrition-user"), [])
        saved = self.save_record(payload)
        draft = preview.get_json()["record"]
        self.assertEqual(saved["foods"], draft["foods"])
        self.assertEqual(saved["nutrition_context"], draft["nutrition_context"])
        for field in ("calories", "protein", "carbs", "fat", "sodium", "trans_fat"):
            self.assertEqual(saved[f"total_{field}"], draft[f"total_{field}"])

    def test_null_zero_bound_and_unresolved_context_survive_read(self):
        self.save_record()
        response = self.client.get("/records/nutrition-user?nutrition_contract_version=2",
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        record = response.get_json()["records"][0]
        known, unknown = record["foods"]
        self.assertIsNone(known["sodium"])
        self.assertEqual(known["sugar"], 0)
        self.assertIsNone(known["trans_fat"])
        self.assertAlmostEqual(known["nutrition_intake"]["upper_bounds"]["trans_fat"], 0.15)
        self.assertIsNone(unknown["calories"])
        self.assertIsNone(unknown["weight_g"])
        self.assertEqual(known["source"], "user_modified")
        context = record["nutrition_context"]
        self.assertEqual(context["visual_completeness"], "not_verified")
        self.assertEqual(context["recognition_context"]["uncertainty_notes"],
                         ["Unweighed background food"])
        calories = context["coverage"]["nutrients"]["calories"]
        self.assertEqual(calories["known_sum"], 300)
        self.assertEqual(calories["eligible_items"], 2)
        self.assertEqual(calories["status"], "partial")
        self.assertIn("unknown", context["unresolved_item_ids"])

    def test_weight_edit_keeps_original_profile_and_unresolved_item(self):
        original = self.save_record()
        foods = [{"item_id": "known", "name": "Manual bowl", "weight_g": 225,
                  "portion_source": "user_adjusted"}, unresolved_food()]
        changed = self.patch_record(foods)
        self.assertEqual(changed.status_code, 200, changed.get_json())
        record = changed.get_json()["record"]
        self.assertEqual(record["foods"][0]["nutrition_profile"],
                         original["foods"][0]["nutrition_profile"])
        self.assertEqual(record["foods"][0]["calories"], 450)
        self.assertIsNone(record["foods"][0]["sodium"])
        self.assertEqual(record["nutrition_context"]["revision"], 1)
        self.assertEqual(record["nutrition_context"]["coverage"]["nutrients"]["calories"]["eligible_items"], 2)

    def test_stale_edit_and_silent_unresolved_removal_are_rejected(self):
        self.save_record()
        foods = [{"item_id": "known", "name": "Manual bowl", "weight_g": 225,
                  "portion_source": "user_adjusted"}, unresolved_food()]
        self.assertEqual(self.patch_record(foods).status_code, 200)
        self.assert_error(self.patch_record(foods), 409, "stale_revision")
        self.assert_error(self.patch_record(foods[:1], revision=1), 400, "missing_items")

    def test_explicit_not_consumed_preserves_audit_and_changes_denominator(self):
        self.save_record()
        foods = [{"item_id": "known", "name": "Manual bowl", "weight_g": 150,
                  "portion_source": "user_weighed"},
                 {**unresolved_food(), "included": False, "exclusion_reason": "not_consumed"}]
        changed = self.patch_record(foods)
        self.assertEqual(changed.status_code, 200, changed.get_json())
        record = changed.get_json()["record"]
        self.assertEqual(len(record["foods"]), 2)
        self.assertEqual(record["foods"][1]["exclusion_reason"], "not_consumed")
        self.assertEqual(record["nutrition_context"]["coverage"]["nutrients"]["calories"]["eligible_items"], 1)
        self.assertEqual(record["nutrition_context"]["coverage"]["nutrients"]["calories"]["status"], "complete")

    def test_source_snapshot_cannot_be_uploaded_or_overwritten(self):
        response = self.post_record(self.payload(foods=[{
            **unresolved_food(), "nutrition_profile": {"source_type": "TFDA", "calories": 0},
        }]))
        self.assert_error(response, 400, "untrusted_profile")
        original = self.save_record()
        foods = copy.deepcopy(original["foods"])
        foods[0]["nutrition_profile"]["per_100g"]["calories"] = 0
        self.assert_error(self.patch_record(foods), 400, "untrusted_profile")

    def test_saved_source_name_cannot_be_reused_for_another_food(self):
        record = self.save_record()
        foods = copy.deepcopy(record["foods"])
        foods[0]["name"] = "Another food"
        self.assert_error(self.patch_record(foods), 400, "profile_identity_changed")

    def test_capability_header_and_query_work_without_body_version(self):
        for index, use_header in enumerate((True, False)):
            with self.subTest(header=use_header):
                payload = self.payload(client_record_id=f"record-{index}")
                del payload["nutrition_contract_version"]
                headers = {**self.headers, **({"X-Nutrition-Contract-Version": "2"} if use_header else {})}
                url = "/record" if use_header else "/record?nutrition_contract_version=2"
                response = self.client.post(url, json=payload, headers=headers)
                self.assertEqual(response.status_code, 201, response.get_json())
                self.assertEqual(response.get_json()["record"]["nutrition_contract_version"], 2)

    def test_conflicting_and_boolean_capabilities_fail_before_writes(self):
        response = self.client.post("/record?nutrition_contract_version=1",
                                    json=self.payload(), headers=self.headers)
        self.assertEqual(response.status_code, 400, response.get_json())
        response = self.post_record(self.payload(nutrition_contract_version=True))
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(self.module.storage.get_records("nutrition-user"), [])

    def test_old_clients_cannot_read_mutate_or_delete_v2_record(self):
        self.save_record()
        requests = (
            ("get", "/records/nutrition-user", None),
            ("get", "/history/nutrition-user", None),
            ("patch", "/records/nutrition-user/nutrition-record", {"foods": []}),
            ("delete", "/records/nutrition-user/nutrition-record", None),
        )
        for method, url, body in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, json=body, headers=self.headers)
                self.assert_error(response, 409, "upgrade_required")
        self.assertIsNotNone(self.module.storage.get_record_by_client_record_id("nutrition-user", "nutrition-record"))

    def test_legacy_retry_id_cannot_disclose_existing_v2_record(self):
        self.save_record()
        response = self.post_record({
            "user_id": "nutrition-user", "client_record_id": "nutrition-record",
            "foods": [{"name": "Old client", "calories": 1, "protein": 0,
                       "carbs": 0, "fat": 0, "sodium": 0, "fiber": 0}],
        })
        self.assert_error(response, 409, "upgrade_required")

    def test_v2_retry_remains_idempotent_with_null_snapshot(self):
        payload = self.payload()
        saved = self.save_record(payload)
        response = self.post_record(payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["deduplicated"])
        self.assertEqual(response.get_json()["record"], saved)
        self.assertEqual(len(self.module.storage.get_records("nutrition-user")), 1)

    def test_history_retains_the_same_unresolved_denominator(self):
        self.save_record()
        response = self.client.get("/history/nutrition-user?nutrition_contract_version=2",
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        history = response.get_json()
        self.assertEqual(history["nutrition_contract_version"], 2)
        for coverage in (history["daily"][0]["nutrition_coverage"],
                         history["summary"]["nutrition_coverage"]):
            self.assertEqual(coverage["nutrients"]["calories"]["known_sum"], 300)
            self.assertEqual(coverage["nutrients"]["calories"]["eligible_items"], 2)
            self.assertEqual(coverage["nutrients"]["calories"]["status"], "partial")
            self.assertEqual(coverage["nutrients"]["sodium"]["status"], "unknown")

    def test_v2_reads_mark_legacy_unknown_without_changing_old_zero(self):
        self.module.storage.insert_record({
            "user_id": "nutrition-user", "client_record_id": "legacy-record",
            "timestamp": app_now().isoformat(), "foods": [{"name": "Old meal", "sodium": 0}],
            "total_sodium": 0, "total_calories": 100,
        })
        response = self.client.get("/records/nutrition-user?nutrition_contract_version=2",
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        record = response.get_json()["records"][0]
        self.assertEqual(record["nutrition_context"]["status"], "legacy_unknown")
        self.assertEqual(record["foods"][0]["sodium"], 0)

    def test_preview_unknown_risk_and_known_exceedance_are_distinct(self):
        unknown = self.client.post("/record/preview", json=self.payload(), headers=self.headers)
        self.assertEqual(unknown.status_code, 200, unknown.get_json())
        risk = unknown.get_json()["record"]["nutrition_context"]["medical_risk"]
        self.assertIsNone(risk["is_safe"])
        self.assertIn("sodium", risk["missing_nutrition_fields"])
        foods = [manual_food(), unresolved_food()]
        foods[0]["user_entered_nutrients"]["sodium"] = 1000
        excess = self.client.post("/record/preview", json=self.payload(foods=foods), headers=self.headers)
        self.assertEqual(excess.status_code, 200, excess.get_json())
        excess_risk = excess.get_json()["record"]["nutrition_context"]["medical_risk"]
        self.assertTrue(any(item.get("nutrient") == "sodium" for item in excess_risk["risks"]))
        self.assertNotEqual(excess_risk["is_safe"], True)

    def test_preview_and_reads_retain_user_access_boundaries(self):
        payload = self.payload(user_id="another-user")
        response = self.client.post("/record/preview", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 403, response.get_json())
        self.assertEqual(self.module.storage.get_records("another-user"), [])
        self.save_record()
        with patch.object(self.module, "verify_access_token", return_value={"id": "another-user"}):
            response = self.client.get("/records/nutrition-user?nutrition_contract_version=2",
                                       headers=self.headers)
        self.assertEqual(response.status_code, 403, response.get_json())

    def test_old_paginated_read_cannot_hide_v2_in_the_requested_scope(self):
        self.save_record()
        self.module.storage.insert_record({
            "user_id": "nutrition-user", "client_record_id": "legacy-page",
            "timestamp": app_now().isoformat(), "foods": [{"name": "Old meal", "calories": 100}],
            "total_calories": 100,
        })
        for query in ("?limit=1", "?date=" + app_now().date().isoformat() + "&limit=1"):
            response = self.client.get("/records/nutrition-user" + query, headers=self.headers)
            self.assert_error(response, 409, "upgrade_required")

    def test_v2_scanning_and_ocr_are_gated_before_paid_calls(self):
        for path, target in (("/predict/vision-food", "call_gemini_food_recognition_with_rotation"),
                             ("/ocr/nutrition-label", "call_gemini_nutrition_ocr_with_rotation")):
            with self.subTest(path=path), patch.object(self.module, target) as paid:
                response = self.client.post(path, json={
                    "user_id": "nutrition-user", "nutrition_contract_version": 2,
                    "image": "not-an-image",
                }, headers=self.headers)
                self.assert_error(response, 409, "nutrition_flow_unavailable")
                paid.assert_not_called()

    def test_personalized_recommendations_are_gated_before_downstream_calls(self):
        self.save_record()
        cases = (
            ("get", "/healthy-food-recommend/nutrition-user", None,
             "build_healthy_food_recommendations"),
            ("get", "/map-food-recommend/nutrition-user", None,
             "build_google_places_food_recommendations"),
            ("post", "/map-food-recommend/nutrition-user/restaurant-summary",
             {"restaurant": {"name": "Example"}}, "build_restaurant_ai_summary"),
            ("post", "/restaurant/menu", {"user_id": "nutrition-user", "name": "Example"},
             "enrich_restaurant_with_gemini"),
            ("post", "/menu/photo-check", {"user_id": "nutrition-user", "menu_image": "invalid"},
             "parse_menu_image_with_gemini"),
        )
        for version in (1, 2):
            for method, path, payload, target in cases:
                with self.subTest(version=version, path=path), ExitStack() as stack:
                    paid = stack.enter_context(patch.object(self.module, target))
                    headers = {**self.headers, "X-Nutrition-Contract-Version": str(version)}
                    response = getattr(self.client, method)(path, json=payload, headers=headers)
                    expected = "upgrade_required" if version == 1 else "nutrition_flow_unavailable"
                    self.assert_error(response, 409, expected)
                    paid.assert_not_called()


if __name__ == "__main__":
    unittest.main()
