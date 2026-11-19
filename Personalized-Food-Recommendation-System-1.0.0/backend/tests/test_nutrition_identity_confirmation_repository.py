import unittest

from repositories.nutrition_identity_confirmation_repository import (
    NutritionIdentityConfirmationError,
    NutritionIdentityConfirmationRepository,
)
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase


ITEM_A = {
    "item_id": "scan-identity:0", "item_revision": 0, "name_zh": "炒菜葉",
    "confidence": 0.42, "weight_confidence": 0.55, "estimated_weight_g": 120,
    "food_state": "prepared", "preparation_method": "stir_fried",
    "components_scope": "food_only", "brand": "舊品牌", "variant": "舊品種",
    "validation_issues": [], "identity_confirmation_required": True,
}
ITEM_B = {**ITEM_A, "item_id": "scan-identity:1", "name_zh": "米飯",
          "confidence": 0.96, "identity_confirmation_required": False,
          "brand": None, "variant": None}


class NutritionIdentityConfirmationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.sql = SqliteDatabase(":memory:")
        self.scan = NutritionScanContextRepository(self.sql, clock=lambda: self.now[0])
        self.repo = NutritionIdentityConfirmationRepository(
            self.sql, scan_context_repository=self.scan, clock=lambda: self.now[0])
        self.scan.save_scan_context(user_id="user-a", scan_id="scan-identity",
                                    scan_revision=0, items=[ITEM_A, ITEM_B], ttl_seconds=120)

    def tearDown(self):
        self.sql.close()

    def _confirm(self, **overrides):
        values = {
            "authenticated_user_id": "user-a", "actor_id": "user-a",
            "scan_id": "scan-identity", "scan_revision": 0,
            "item_id": ITEM_A["item_id"], "item_revision": 0,
            "confirmed_name": "青江菜", "idempotency_key": "identity-1",
        }
        values.update(overrides)
        return self.repo.confirm_item_name(**values)

    def test_corrected_name_creates_an_audited_owner_bound_revision(self):
        result = self._confirm()
        old = self.scan.get_scan_context(user_id="user-a", scan_id="scan-identity",
                                         scan_revision=0, include_inactive=True)
        new = self.scan.get_scan_context(user_id="user-a", scan_id="scan-identity",
                                         scan_revision=1)
        corrected = next(item for item in new["items"] if item["item_id"] == ITEM_A["item_id"])
        untouched = next(item for item in new["items"] if item["item_id"] == ITEM_B["item_id"])

        self.assertEqual(result["result"]["decision"], "correct")
        self.assertEqual(result["issued_scan_revision"], 1)
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(corrected["item_revision"], 1)
        self.assertEqual(corrected["name_zh"], "青江菜")
        self.assertEqual(corrected["confidence"], ITEM_A["confidence"])
        self.assertEqual(corrected["weight_confidence"], ITEM_A["weight_confidence"])
        self.assertEqual(corrected["estimated_weight_g"], ITEM_A["estimated_weight_g"])
        self.assertIsNone(corrected["brand"])
        self.assertIsNone(corrected["variant"])
        self.assertFalse(corrected["identity_confirmation_required"])
        self.assertEqual(corrected["identity_confirmation_source"], "user")
        self.assertEqual(corrected["identity_confirmation_id"], result["confirmation_id"])
        self.assertEqual(untouched, ITEM_B)
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_identity_confirmations")["count"], 1)

    def test_exact_name_confirmation_preserves_existing_qualifiers(self):
        item = {**ITEM_A, "name_zh": "糯米腸"}
        self.scan.save_scan_context(user_id="user-a", scan_id="scan-exact",
                                    scan_revision=0, items=[item])
        result = self._confirm(scan_id="scan-exact", item_id=item["item_id"],
                               confirmed_name="糯米腸", idempotency_key="identity-exact")
        current = self.scan.get_scan_context(user_id="user-a", scan_id="scan-exact",
                                             scan_revision=1)
        item = current["items"][0]
        self.assertEqual(result["result"]["decision"], "confirm")
        self.assertEqual(item["brand"], ITEM_A["brand"])
        self.assertEqual(item["variant"], ITEM_A["variant"])
        self.assertEqual(item["confidence"], ITEM_A["confidence"])

    def test_same_key_replays_but_cannot_be_rebound(self):
        first = self._confirm()
        replay = self._confirm()
        self.assertEqual(first["confirmation_id"], replay["confirmation_id"])
        self.assertTrue(replay["replayed"])
        with self.assertRaises(NutritionIdentityConfirmationError) as conflict:
            self._confirm(confirmed_name="小白菜")
        self.assertEqual(conflict.exception.code, "idempotency_conflict")
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_scan_contexts")["count"], 2)

    def test_generic_name_unknown_state_and_validation_errors_cannot_be_confirmed(self):
        for name in ("菜葉", "炒菜葉", "未知青菜", "需確認"):
            with self.subTest(name=name), self.assertRaises(NutritionIdentityConfirmationError) as error:
                self._confirm(confirmed_name=name, idempotency_key=f"generic-{name}")
            self.assertEqual(error.exception.code, "invalid_identity")

        unknown = {**ITEM_A, "preparation_method": "unknown"}
        self.scan.save_scan_context(user_id="user-a", scan_id="scan-unknown",
                                    scan_revision=0, items=[unknown])
        with self.assertRaises(NutritionIdentityConfirmationError) as error:
            self._confirm(scan_id="scan-unknown", item_id=unknown["item_id"])
        self.assertEqual(error.exception.code, "identity_context_incomplete")

        invalid = {**ITEM_A, "validation_issues": ["invalid_state"]}
        self.scan.save_scan_context(user_id="user-a", scan_id="scan-invalid",
                                    scan_revision=0, items=[invalid])
        with self.assertRaises(NutritionIdentityConfirmationError) as error:
            self._confirm(scan_id="scan-invalid", item_id=invalid["item_id"])
        self.assertEqual(error.exception.code, "identity_context_incomplete")

    def test_cross_user_stale_and_non_identity_flags_fail_closed(self):
        with self.assertRaises(NutritionIdentityConfirmationError) as wrong_user:
            self._confirm(authenticated_user_id="user-b", actor_id="user-b")
        self.assertEqual(wrong_user.exception.code, "wrong_user")

        self._confirm()
        with self.assertRaises(NutritionIdentityConfirmationError) as stale:
            self._confirm(idempotency_key="identity-stale")
        self.assertEqual(stale.exception.code, "stale_revision")

        self.scan.save_scan_context(user_id="user-a", scan_id="scan-ready",
                                    scan_revision=0, items=[ITEM_B])
        with self.assertRaises(NutritionIdentityConfirmationError) as not_required:
            self._confirm(scan_id="scan-ready", item_id=ITEM_B["item_id"],
                          confirmed_name="白飯", idempotency_key="not-required")
        self.assertEqual(not_required.exception.code, "identity_confirmation_not_required")


if __name__ == "__main__":
    unittest.main()
