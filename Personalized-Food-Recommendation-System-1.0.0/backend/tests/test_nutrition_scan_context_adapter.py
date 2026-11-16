import unittest

from repositories.scan_context_repository import NutritionScanContextRepository
from services.nutrition_scan_context_adapter import (
    NutritionScanContextAdapterError,
    build_scan_context_items,
    persist_vision_scan_context,
)


ITEM = {
    "item_id": "scan-1:0", "item_revision": 0, "name_zh": "糯米腸",
    "confidence": 0.92, "weight_confidence": 0.8, "estimated_weight_g": 120,
    "food_state": "prepared", "preparation_method": "steamed",
    "components_scope": "food_only", "count": 2,
    "alternatives": ["吉林糯米腸"], "visual_evidence": "visible sausage",
    "validation_issues": [],
}


class NutritionScanContextAdapterTests(unittest.TestCase):
    def setUp(self):
        self.repo = NutritionScanContextRepository(clock=lambda: 1000.0)

    def response(self, items=None):
        return {
            "scan_id": "scan-1", "scan_revision": 0,
            "recognition_context": {"items": items if items is not None else [ITEM]},
        }

    def test_narrows_presentation_fields_and_persists_complete_set(self):
        saved = persist_vision_scan_context(self.response(), user_id="user-1", repository=self.repo)
        self.assertEqual(saved["user_id"], "user-1")
        self.assertEqual(saved["items"][0]["name_zh"], "糯米腸")
        self.assertNotIn("alternatives", saved["items"][0])
        self.assertNotIn("visual_evidence", saved["items"][0])
        self.assertNotIn("count", saved["items"][0])
        loaded = self.repo.assert_complete_item_set(
            user_id="user-1", scan_id="scan-1", scan_revision=0,
            items=build_scan_context_items(self.response()),
        )
        self.assertEqual(loaded["item_set_hash"], saved["item_set_hash"])

    def test_empty_result_does_not_create_authority_context(self):
        self.assertIsNone(persist_vision_scan_context(self.response([]), user_id="user-1", repository=self.repo))

    def test_missing_server_identity_is_rejected(self):
        with self.assertRaisesRegex(NutritionScanContextAdapterError, "scan_id"):
            persist_vision_scan_context({"recognition_context": {"items": [ITEM]}},
                                        user_id="user-1", repository=self.repo)

    def test_client_only_fields_are_not_authority_input(self):
        items = build_scan_context_items(self.response())
        items[0]["name_zh"] = "被竄改"
        # The adapter returns a detached copy; modifying it cannot mutate the
        # original recognition response that was persisted.
        saved = persist_vision_scan_context(self.response(), user_id="user-1", repository=self.repo)
        self.assertEqual(saved["items"][0]["name_zh"], "糯米腸")


if __name__ == "__main__":
    unittest.main()
