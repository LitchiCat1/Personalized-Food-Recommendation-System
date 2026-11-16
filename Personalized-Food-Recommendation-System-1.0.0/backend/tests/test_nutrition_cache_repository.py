from copy import deepcopy
import hashlib
import os
import tempfile
import unittest

from repositories.nutrition_cache_repository import (
    NutritionCacheRepositoryError, NutritionProfileCacheRepository,
)
from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.sqlite_db import SqliteDatabase
from services.nutrition_profile_service import build_nutrition_profile


IDENTITY = {"name": "糯米腸", "food_state": "prepared", "preparation_method": "roasted",
            "components_scope": "food_only", "brand": None, "variant": None}


def policy(*, cross_user=False, source_id="source-1"):
    rights = {
        "reference": "Synthetic review", "reviewed_at": "2026-11-14T00:00:00Z",
        "license_url": "https://example.com/license", "license_name": "Fixture license",
        "attribution": "Fixture", "reuse_scope": "cross_user" if cross_user else "server_internal",
        "provider_cache_scope": "cross_user_approved" if cross_user else "server_internal",
        "retention_policy": "Test only", "withdrawal_policy": "Withdraw immediately",
        "reviewer": "test", "evidence_urls": ["https://example.com/terms"],
        "search_allowed": True, "extract_allowed": True, "snapshot_allowed": True,
        "reuse_allowed": True,
    }
    source_identity = {key: value for key, value in IDENTITY.items() if key != "name"}
    return {
        "policy_id": "policy-" + source_id, "accepted_names": [IDENTITY["name"]],
        "target_identity": source_identity,
        "source_spec": {
            "source_id": source_id, "source_url": "https://example.com/" + source_id,
            "adapter_version": "fixture-v1", "table_id": "nutrition-1",
            "food_identity": deepcopy(IDENTITY), "identity_line": "# " + IDENTITY["name"],
            "table_header": ["Nutrient", "Per 100 g"],
            "columns": {"per_100g": {"index": 1, "basis": "per_100g",
                                      "basis_weight_g": "100", "evidence": "Per 100 g"}},
        },
        "match_policy": "reference_only", "compatibility_review": "Fixture review",
        "rights": rights,
    }


def profile():
    nutrients = {field: {"value": value, "unit": unit, "comparison": "exact"}
                 for field, value, unit in (
                     ("calories", "200", "kcal"), ("protein", "8", "g"),
                     ("carbs", "30", "g"), ("fat", "6", "g"),
                     ("sodium", "250", "mg"), ("fiber", "2", "g"),
                     ("sugar", "1", "g"), ("saturated_fat", "2", "g"),
                     ("trans_fat", "0", "g"))}
    return build_nutrition_profile(nutrients, basis="per_100g", source_details={
        "source_id": "source-1", "source_url": "https://example.com/source-1",
        "content_hash": hashlib.sha256(b"fixture").hexdigest(),
        "retrieved_at": "2026-11-14T00:00:00Z", "adapter_version": "fixture-v1",
        "retrieval_version": "fixture-v1"})


class NutritionCacheRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [1_700_000_000.0]
        self.sql = SqliteDatabase(":memory:")
        self.sources = NutritionProfileSourceRepository(self.sql)
        self.source = self.sources.save_source_policy(policy(cross_user=True))
        self.cache = NutritionProfileCacheRepository(
            self.sources, self.sql, clock=lambda: self.now[0], default_ttl_seconds=100)

    def tearDown(self):
        self.sql.close()

    def test_successful_cross_user_profile_round_trip(self):
        saved = self.cache.put_success(food_identity=IDENTITY, profile=profile(),
                                       source_id="source-1", source_policy_revision=0)
        self.assertEqual(saved["cache_scope"], "cross_user")
        loaded = self.cache.get(food_identity=IDENTITY, source_id="source-1",
                                source_policy_revision=0, user_id="another-user")
        self.assertEqual(loaded["profile_hash"], saved["profile_hash"])
        self.assertEqual(loaded["profile"], profile())

    def test_policy_id_alias_is_normalized_for_cache_write_and_read(self):
        saved = self.cache.put_success(
            food_identity=IDENTITY, profile=profile(),
            source_id="policy-source-1", source_policy_revision=0)
        self.assertEqual(saved["source_id"], "source-1")
        loaded = self.cache.get(
            food_identity=IDENTITY, source_id="policy-source-1",
            source_policy_revision=0, user_id="another-user")
        self.assertEqual(loaded["source_id"], "source-1")

    def test_server_internal_cache_is_owner_bound(self):
        source_repo = NutritionProfileSourceRepository(SqliteDatabase(":memory:"))
        source_repo.save_source_policy(policy(cross_user=False))
        cache = NutritionProfileCacheRepository(source_repo, source_repo.sql, clock=lambda: self.now[0])
        cache.put_success(food_identity=IDENTITY, profile=profile(), source_id="source-1",
                          source_policy_revision=0, user_id="owner")
        self.assertIsNone(cache.get(food_identity=IDENTITY, source_id="source-1",
                                     source_policy_revision=0, user_id="other"))
        self.assertIsNotNone(cache.get(food_identity=IDENTITY, source_id="source-1",
                                       source_policy_revision=0, user_id="owner"))
        source_repo.sql.close()

    def test_expiry_is_a_miss_and_does_not_create_negative_cache(self):
        self.assertIsNone(self.cache.get(food_identity=IDENTITY, source_id="source-1",
                                         source_policy_revision=0))
        self.cache.put_success(food_identity=IDENTITY, profile=profile(), source_id="source-1",
                               source_policy_revision=0, ttl_seconds=10)
        self.now[0] += 10
        self.assertIsNone(self.cache.get(food_identity=IDENTITY, source_id="source-1",
                                         source_policy_revision=0))
        self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS count FROM nutrition_profile_cache")["count"], 1)
        self.assertEqual(self.cache.purge_expired(), 1)
        self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS count FROM nutrition_profile_cache")["count"], 0)

    def test_source_revision_and_withdrawal_invalidate_future_reads(self):
        self.cache.put_success(food_identity=IDENTITY, profile=profile(), source_id="source-1",
                               source_policy_revision=0)
        self.sources.save_source_policy(policy(cross_user=True), expected_revision=0)
        self.assertIsNone(self.cache.get(food_identity=IDENTITY, source_id="source-1",
                                         source_policy_revision=0))
        # A new policy revision can be cached only with a profile whose source
        # details also identify the current adapter/source contract.
        self.sources.withdraw_source_policy("source-1", expected_revision=1)
        self.assertIsNone(self.cache.get(food_identity=IDENTITY, source_id="source-1",
                                         source_policy_revision=1))

    def test_rights_and_provenance_gate_writes(self):
        restricted = NutritionProfileSourceRepository(SqliteDatabase(":memory:"))
        restricted.save_source_policy({**policy(cross_user=True), "rights": {
            **policy(cross_user=True)["rights"], "snapshot_allowed": False}})
        restricted_cache = NutritionProfileCacheRepository(restricted, restricted.sql)
        with self.assertRaisesRegex(NutritionCacheRepositoryError, "does not allow"):
            restricted_cache.put_success(food_identity=IDENTITY, profile=profile(), source_id="source-1",
                                         source_policy_revision=0)
        bad = deepcopy(profile())
        bad["source_details"]["adapter_version"] = "old-adapter"
        with self.assertRaisesRegex(NutritionCacheRepositoryError, "provenance"):
            self.cache.put_success(food_identity=IDENTITY, profile=bad, source_id="source-1",
                                   source_policy_revision=0)
        with self.assertRaisesRegex(NutritionCacheRepositoryError, "identity"):
            self.cache.put_success(food_identity={**IDENTITY, "name": "白飯"}, profile=profile(),
                                   source_id="source-1", source_policy_revision=0)
        restricted.sql.close()

    def test_cache_key_binds_identity_policy_and_adapter(self):
        base = dict(food_identity=IDENTITY, source_id="source-1", source_policy_id="policy-source-1",
                    source_policy_revision=0, source_url="https://example.com/source-1",
                    adapter_version="fixture-v1", retrieval_version="fixture-v1")
        self.assertNotEqual(NutritionProfileCacheRepository.cache_key(**base),
                            NutritionProfileCacheRepository.cache_key(**{**base, "adapter_version": "fixture-v2"}))
        self.assertNotEqual(NutritionProfileCacheRepository.cache_key(**base),
                            NutritionProfileCacheRepository.cache_key(**{**base, "food_identity": {**IDENTITY, "name": "白飯"}}))

    def test_restart_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "cache.db")
            first_sql = SqliteDatabase(path)
            first_sources = NutritionProfileSourceRepository(first_sql)
            first_sources.save_source_policy(policy(cross_user=True))
            first_cache = NutritionProfileCacheRepository(first_sources, first_sql, clock=lambda: self.now[0])
            first_cache.put_success(food_identity=IDENTITY, profile=profile(), source_id="source-1",
                                    source_policy_revision=0)
            first_sql.close()
            second_sql = SqliteDatabase(path)
            try:
                second_sources = NutritionProfileSourceRepository(second_sql)
                second_cache = NutritionProfileCacheRepository(second_sources, second_sql,
                                                               clock=lambda: self.now[0])
                self.assertIsNotNone(second_cache.get(food_identity=IDENTITY, source_id="source-1",
                                                      source_policy_revision=0))
            finally:
                second_sql.close()


if __name__ == "__main__":
    unittest.main()
