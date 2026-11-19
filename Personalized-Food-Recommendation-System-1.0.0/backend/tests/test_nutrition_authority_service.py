import base64
import json
import unittest

from services.nutrition_authority_service import (
    NutritionAuthorityError, NutritionAuthorityService, PROFILE_TOKEN_TYPE,
    SCAN_TOKEN_TYPE,
)


ITEM = {
    "item_id": "item-1", "item_revision": 3, "name_zh": "烤糯米腸",
    "confidence": 0.93, "weight_confidence": 0.8, "estimated_weight_g": 150,
    "food_state": "prepared", "preparation_method": "roasted", "components_scope": "food_only",
    "brand": None, "variant": None, "validation_issues": [],
}
IDENTITY = {"name": "USDA rice sausage", "food_state": "prepared", "preparation_method": "roasted",
            "components_scope": "food_only", "brand": None, "variant": None}


class NutritionAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.now = [1_700_000_000]
        self.service = NutritionAuthorityService({"current": b"a" * 32, "previous": b"b" * 32},
                                                 active_kid="current", clock=lambda: self.now[0])

    def test_scan_token_binds_user_revision_and_items(self):
        item = dict(ITEM, identity_confirmation_required=True)
        token = self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=2,
                                                items=[item])
        claims = self.service.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-1")
        self.assertEqual(claims["scan_id"], "scan-1")
        self.assertEqual(claims["scan_revision"], 2)
        self.assertEqual(claims["items"][0]["item_id"], "item-1")
        self.assertTrue(claims["items"][0]["identity_confirmation_required"])

    def test_cross_user_and_wrong_type_are_rejected(self):
        token = self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0, items=[ITEM])
        with self.assertRaisesRegex(NutritionAuthorityError, "another user"):
            self.service.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-2")
        with self.assertRaisesRegex(NutritionAuthorityError, "version or type"):
            self.service.verify(token, expected_type=PROFILE_TOKEN_TYPE, user_id="user-1")

    def test_expiration_and_future_clock_are_checked(self):
        token = self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0,
                                                items=[ITEM], ttl_seconds=10)
        self.now[0] += 10
        with self.assertRaisesRegex(NutritionAuthorityError, "expired"):
            self.service.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-1")
        self.now[0] = 1_699_999_990
        with self.assertRaisesRegex(NutritionAuthorityError, "not yet"):
            self.service.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-1")

    def test_consume_is_atomic_for_process_local_replay_guard(self):
        token = self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0, items=[ITEM])
        self.service.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-1", consume=True)
        with self.assertRaisesRegex(NutritionAuthorityError, "already been consumed"):
            self.service.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-1", consume=True)
        # Non-consuming verification remains available for a route that uses a
        # durable idempotency key rather than one-time token semantics.
        self.assertEqual(self.service.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-1")["scan_id"], "scan-1")

    def test_tamper_and_unknown_key_id_are_rejected(self):
        token = self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0, items=[ITEM])
        body, signature = token.split(".")
        tampered = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + signature
        with self.assertRaisesRegex(NutritionAuthorityError, "signature|invalid"):
            self.service.verify(tampered, expected_type=SCAN_TOKEN_TYPE, user_id="user-1")
        encoded_body, signature = token.split(".")
        body = base64.urlsafe_b64decode(encoded_body + "=" * ((4 - len(encoded_body) % 4) % 4))
        envelope = json.loads(body)
        envelope["kid"] = "unknown"
        changed_body = base64.urlsafe_b64encode(json.dumps(envelope, ensure_ascii=True, sort_keys=True,
                                                          separators=(",", ":")).encode()).rstrip(b"=").decode()
        unknown = changed_body + "." + signature
        with self.assertRaisesRegex(NutritionAuthorityError, "signature|invalid"):
            self.service.verify(unknown, expected_type=SCAN_TOKEN_TYPE, user_id="user-1")

    def test_scan_rejects_sensitive_fields_duplicate_ids_and_bad_confidence(self):
        for mutation in (
            {"health_conditions": ["private"]},
            {"confidence": True},
            {"estimated_weight_g": 0},
        ):
            item = dict(ITEM, **mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(NutritionAuthorityError):
                    self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0, items=[item])
        with self.assertRaisesRegex(NutritionAuthorityError, "unique"):
            self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0, items=[ITEM, ITEM])

    def test_scan_ttl_is_bounded(self):
        with self.assertRaisesRegex(NutritionAuthorityError, "TTL"):
            self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0,
                                            items=[ITEM], ttl_seconds=901)

    def test_profile_token_contains_hash_and_identity_but_not_profile_values(self):
        profile = {"schema_version": "NutritionProfileV1", "per_100g": {"calories": 200}}
        digest = self.service.profile_hash(profile)
        token = self.service.issue_profile_authority(
            user_id="user-1", profile_id="profile-1", profile_hash=digest, source_id="usda-fdc-1",
            profile_revision=4, food_identity=IDENTITY,
        )
        claims = self.service.verify(token, expected_type=PROFILE_TOKEN_TYPE, user_id="user-1")
        self.assertEqual(claims["profile_hash"], digest)
        self.assertNotIn("200", token)
        self.assertEqual(claims["food_identity"]["name"], IDENTITY["name"])

    def test_profile_hash_and_identity_are_validated(self):
        with self.assertRaisesRegex(NutritionAuthorityError, "profile_hash"):
            self.service.issue_profile_authority(user_id="user-1", profile_id="p", profile_hash="bad",
                                                 source_id="s", profile_revision=0, food_identity=IDENTITY)
        with self.assertRaisesRegex(NutritionAuthorityError, "food identity"):
            self.service.issue_profile_authority(user_id="user-1", profile_id="p", profile_hash="a" * 64,
                                                 source_id="s", profile_revision=0,
                                                 food_identity={"name": "x", "food_state": "unknown",
                                                                "preparation_method": "unknown",
                                                                "components_scope": "food_only", "brand": None,
                                                                "variant": None, "private": "secret"})

    def test_key_rotation_keeps_old_tokens_verifiable(self):
        token = self.service.issue_scan_context(user_id="user-1", scan_id="scan-1", scan_revision=0, items=[ITEM])
        rotated = NutritionAuthorityService({"new": b"c" * 32, "current": b"a" * 32},
                                            active_kid="new", clock=lambda: self.now[0])
        self.assertEqual(rotated.verify(token, expected_type=SCAN_TOKEN_TYPE, user_id="user-1")["scan_id"], "scan-1")


if __name__ == "__main__":
    unittest.main()

