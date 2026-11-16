from copy import deepcopy
import hashlib
import json
import os
import tempfile
import threading
import unittest

from repositories.nutrition_profile_repository import (
    NutritionProfileSourceRepository, NutritionRepositoryError,
    profile_hash,
)
from repositories.sqlite_db import SqliteDatabase
from services.nutrition_authority_service import NutritionAuthorityService
from services.nutrition_profile_service import build_nutrition_profile


def policy(name="糯米腸", source_id="source-1", *, cross_user=False):
    identity = {"food_state": "prepared", "preparation_method": "roasted",
                "components_scope": "food_only", "brand": None, "variant": None}
    rights = {"reference": "Synthetic review", "reviewed_at": "2026-11-14T00:00:00Z",
              "license_url": "https://example.com/license", "license_name": "Fixture license",
              "attribution": "Fixture", "reuse_scope": "cross_user" if cross_user else "server_internal",
              "provider_cache_scope": "cross_user_approved" if cross_user else "server_internal",
              "retention_policy": "Test only", "withdrawal_policy": "Withdraw immediately",
              "reviewer": "test", "evidence_urls": ["https://example.com/terms"],
              "search_allowed": True, "extract_allowed": True,
              "snapshot_allowed": True, "reuse_allowed": True}
    return {"policy_id": "policy-" + source_id, "accepted_names": [name],
            "target_identity": identity,
            "source_spec": {"source_id": source_id, "source_url": "https://example.com/" + source_id,
                            "adapter_version": "fixture-v1", "table_id": "nutrition-1",
                            "food_identity": {"name": name, **identity},
                            "identity_line": "# " + name,
                            "table_header": ["Nutrient", "Per 100 g"],
                            "columns": {"per_100g": {"index": 1, "basis": "per_100g",
                                                       "basis_weight_g": "100", "evidence": "Per 100 g"}}},
            "match_policy": "reference_only", "compatibility_review": "Fixture review",
            "rights": rights}


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


def fdc_policy():
    """Reviewed FDC policy fixture for repository provenance tests."""
    fdc_id = "171688"
    identity = {"name": "Apples, raw, with skin", "food_state": "raw",
                "preparation_method": "mixed", "components_scope": "food_only",
                "brand": None, "variant": None}
    rights = {"reference": "USDA FDC terms review", "reviewed_at": "2026-11-14T00:00:00Z",
              "license_url": "https://fdc.nal.usda.gov/about-us.html", "license_name": "USDA FDC CC0",
              "attribution": "USDA Agricultural Research Service", "reuse_scope": "server_internal",
              "provider_cache_scope": "server_internal", "retention_policy": "Retain source hash only",
              "withdrawal_policy": "Withdraw on provider notice", "reviewer": "nutrition-review",
              "evidence_urls": ["https://fdc.nal.usda.gov/about-us.html"],
              "search_allowed": True, "extract_allowed": True, "snapshot_allowed": True,
              "reuse_allowed": True}
    return {
        "policy_id": "policy-usda-fdc-171688", "accepted_names": [identity["name"]],
        "target_identity": {key: identity[key] for key in identity if key != "name"},
        "source_spec": {"provider_kind": "usda_fdc_api", "source_id": "usda-fdc-171688",
                        "fdc_id": fdc_id,
                        "source_url": "https://api.nal.usda.gov/fdc/v1/food/171688",
                        "adapter_version": "usda-fdc-json-v1", "retrieval_version": "usda-fdc-api-v1",
                        "table_id": "fdc-171688-per-100g", "food_identity": identity},
        "match_policy": "reference_only", "compatibility_review": "Exact raw apple reference reviewed",
        "rights": rights,
        "server_review": {"status": "approved", "provider_kind": "usda_fdc_api",
                          "reviewer": "nutrition-review", "reviewed_at": "2026-11-14T00:00:00Z"},
    }


def fdc_profile(details=None):
    nutrients = {field: {"value": value, "unit": unit, "comparison": "exact"}
                 for field, value, unit in (
                     ("calories", "52", "kcal"), ("protein", "0.26", "g"),
                     ("carbs", "13.81", "g"), ("fat", "0.17", "g"),
                     ("sodium", "1", "mg"), ("fiber", "2.4", "g"),
                     ("sugar", "10.39", "g"), ("saturated_fat", "0.028", "g"),
                     ("trans_fat", "0", "g"))}
    source = {"source_id": "usda-fdc-171688",
              "source_url": "https://api.nal.usda.gov/fdc/v1/food/171688",
              "content_hash": hashlib.sha256(b"fdc-fixture").hexdigest(),
              "retrieved_at": "2026-11-14T00:00:00Z", "adapter_version": "usda-fdc-json-v1",
              "retrieval_version": "usda-fdc-api-v1", "table_id": "fdc-171688-per-100g",
              "provider_kind": "usda_fdc_api", "fdc_id": "171688",
              "food_identity": {"name": "Apples, raw, with skin", "food_state": "raw",
                                "preparation_method": "mixed", "components_scope": "food_only",
                                "brand": None, "variant": None}}
    if details:
        source.update(details)
    return build_nutrition_profile(nutrients, basis="per_100g", source_details=source)


IDENTITY = {"name": "糯米腸", "food_state": "prepared", "preparation_method": "roasted",
            "components_scope": "food_only", "brand": None, "variant": None}


class SqliteRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.sql = SqliteDatabase(":memory:")
        self.repo = NutritionProfileSourceRepository(self.sql)
        self.source = self.repo.save_source_policy(policy())

    def tearDown(self):
        self.sql.close()

    def test_source_and_profile_round_trip_uses_authority_hash(self):
        saved = self.repo.save_profile(profile_id="p1", user_id="u1", profile=profile(),
                                       food_identity=IDENTITY, source_id="source-1",
                                       source_policy_revision=self.source["revision"])
        self.assertEqual(saved["profile_revision"], 0)
        self.assertEqual(saved["profile_hash"], NutritionAuthorityService.profile_hash(profile()))
        self.assertEqual(saved["profile_hash"], profile_hash(profile()))
        loaded = self.repo.get_profile_for_user("u1", "p1")
        self.assertEqual(loaded["profile"], profile())
        self.assertEqual(loaded["food_identity"], IDENTITY)

    def test_source_update_requires_compare_and_set_revision(self):
        updated = self.repo.save_source_policy(policy(name="糯米腸"), expected_revision=0)
        self.assertEqual(updated["revision"], 1)
        self.assertEqual(self.repo.get_source_policy("source-1", revision=0)["revision"], 0)
        with self.assertRaisesRegex(NutritionRepositoryError, "stale") as ctx:
            self.repo.save_source_policy(policy(name="糯米腸"), expected_revision=0)
        self.assertEqual(ctx.exception.code, "revision_conflict")

    def test_policy_id_alias_resolves_to_its_canonical_source_id(self):
        resolved = self.repo.get_source_policy_by_policy_id("policy-source-1", revision=0)
        self.assertEqual(resolved["source_id"], "source-1")
        self.assertEqual(resolved["policy_id"], "policy-source-1")
        alias = self.repo.resolve_source_policy_reference("policy-source-1", revision=0)
        self.assertEqual(alias["source_id"], "source-1")

    def test_duplicate_policy_id_fails_closed(self):
        second = policy(source_id="source-2")
        second["policy_id"] = "policy-source-1"
        self.repo.save_source_policy(second)
        with self.assertRaisesRegex(NutritionRepositoryError, "ambiguous") as ctx:
            self.repo.resolve_source_policy_reference("policy-source-1", revision=0)
        self.assertEqual(ctx.exception.code, "source_conflict")

    def test_profile_update_requires_compare_and_set_revision(self):
        self.repo.save_profile(profile_id="p1", user_id="u1", profile=profile(), food_identity=IDENTITY,
                               source_id="source-1", source_policy_revision=0)
        with self.assertRaisesRegex(NutritionRepositoryError, "stale") as ctx:
            self.repo.save_profile(profile_id="p1", user_id="u1", profile=profile(), food_identity=IDENTITY,
                                   source_id="source-1", source_policy_revision=0, expected_revision=1)
        self.assertEqual(ctx.exception.code, "revision_conflict")
        changed = self.repo.save_profile(profile_id="p1", user_id="u1", profile=profile(), food_identity=IDENTITY,
                                         source_id="source-1", source_policy_revision=0, expected_revision=0)
        self.assertEqual(changed["profile_revision"], 1)

    def test_withdrawn_source_blocks_new_profiles_and_reads(self):
        self.repo.save_profile(profile_id="existing", user_id="u1", profile=profile(), food_identity=IDENTITY,
                               source_id="source-1", source_policy_revision=0)
        self.repo.withdraw_source_policy("source-1", expected_revision=0)
        self.assertIsNone(self.repo.get_source_policy("source-1"))
        with self.assertRaisesRegex(NutritionRepositoryError, "withdrawn"):
            self.repo.save_profile(profile_id="p1", user_id="u1", profile=profile(), food_identity=IDENTITY,
                                   source_id="source-1", source_policy_revision=0)
        with self.assertRaisesRegex(NutritionRepositoryError, "no longer active"):
            self.repo.get_profile_for_user("u1", "existing")
        self.assertEqual(self.repo.get_profile_for_user("u1", "existing", include_withdrawn=True)["profile_id"], "existing")

    def test_profile_identity_and_source_revision_are_checked(self):
        with self.assertRaisesRegex(NutritionRepositoryError, "reviewed alias"):
            self.repo.save_profile(profile_id="p1", user_id="u1", profile=profile(),
                                   food_identity={**IDENTITY, "name": "臭豆腐"}, source_id="source-1",
                                   source_policy_revision=0)
        with self.assertRaisesRegex(NutritionRepositoryError, "stale"):
            self.repo.save_profile(profile_id="p1", user_id="u1", profile=profile(), food_identity=IDENTITY,
                                   source_id="source-1", source_policy_revision=1)

    def test_profile_provenance_and_rights_are_rechecked(self):
        bad_profile = deepcopy(profile())
        bad_profile["source_details"]["source_url"] = "https://example.com/other"
        with self.assertRaisesRegex(NutritionRepositoryError, "provenance"):
            self.repo.save_profile(profile_id="p1", user_id="u1", profile=bad_profile,
                                   food_identity=IDENTITY, source_id="source-1", source_policy_revision=0)
        restricted = policy()
        restricted["rights"]["snapshot_allowed"] = False
        restricted["rights"]["reuse_allowed"] = False
        self.repo.save_source_policy(restricted, expected_revision=0)
        with self.assertRaisesRegex(NutritionRepositoryError, "does not allow"):
            self.repo.save_profile(profile_id="p2", user_id="u1", profile=profile(), food_identity=IDENTITY,
                                   source_id="source-1", source_policy_revision=1)

    def test_fdc_policy_and_profile_provenance_are_bound_to_fixed_record(self):
        repo = NutritionProfileSourceRepository(SqliteDatabase(":memory:"))
        try:
            source = repo.save_source_policy(fdc_policy())
            identity = {"name": "Apples, raw, with skin", "food_state": "raw",
                        "preparation_method": "mixed", "components_scope": "food_only",
                        "brand": None, "variant": None}
            saved = repo.save_profile(profile_id="fdc-profile", user_id="u1", profile=fdc_profile(),
                                      food_identity=identity, source_id="usda-fdc-171688",
                                      source_policy_revision=source["revision"])
            self.assertEqual(saved["profile_revision"], 0)
            for field, value in (
                    ("source_id", "usda-fdc-171689"),
                    ("source_url", "https://api.nal.usda.gov/fdc/v1/food/171689"),
                    ("retrieval_version", "other-retriever-v1"),
                    ("table_id", "fdc-171689-per-100g"),
                    ("fdc_id", "171689"),
                    ("provider_kind", "tavily_extract"),
                    ("food_identity", {**identity, "food_state": "prepared"})):
                with self.subTest(field=field):
                    with self.assertRaises(NutritionRepositoryError) as ctx:
                        repo.save_profile(profile_id="bad-" + field, user_id="u1",
                                          profile=fdc_profile({field: value}), food_identity=identity,
                                          source_id="usda-fdc-171688",
                                          source_policy_revision=source["revision"])
                    self.assertEqual(ctx.exception.code, "source_conflict")
        finally:
            repo.sql.close()

    def test_fdc_policy_withdrawal_survives_restart_and_blocks_new_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "fdc-nutrition.db")
            first_sql = SqliteDatabase(path)
            first = NutritionProfileSourceRepository(first_sql)
            source = first.save_source_policy(fdc_policy())
            identity = {"name": "Apples, raw, with skin", "food_state": "raw",
                        "preparation_method": "mixed", "components_scope": "food_only",
                        "brand": None, "variant": None}
            first.save_profile(profile_id="fdc-existing", user_id="u1", profile=fdc_profile(),
                               food_identity=identity, source_id="usda-fdc-171688",
                               source_policy_revision=source["revision"])
            first_sql.close()

            second_sql = SqliteDatabase(path)
            try:
                second = NutritionProfileSourceRepository(second_sql)
                self.assertEqual(second.get_source_policy("usda-fdc-171688")["revision"], 0)
                self.assertEqual(second.get_profile_for_user("u1", "fdc-existing")["profile_id"],
                                 "fdc-existing")
                withdrawn = second.withdraw_source_policy("usda-fdc-171688", expected_revision=0)
                self.assertEqual(withdrawn["status"], "withdrawn")
                self.assertEqual(withdrawn["revision"], 1)
                self.assertIsNone(second.get_source_policy("usda-fdc-171688"))
                self.assertEqual(second.get_source_policy("usda-fdc-171688", include_withdrawn=True)["revision"], 1)
                with self.assertRaisesRegex(NutritionRepositoryError, "withdrawn"):
                    second.save_profile(profile_id="fdc-new", user_id="u1", profile=fdc_profile(),
                                        food_identity=identity, source_id="usda-fdc-171688",
                                        source_policy_revision=0)
                with self.assertRaisesRegex(NutritionRepositoryError, "no longer active"):
                    second.get_profile_for_user("u1", "fdc-existing")
                self.assertEqual(second.get_profile_for_user("u1", "fdc-existing",
                                                              include_withdrawn=True)["profile_id"],
                                 "fdc-existing")
            finally:
                second_sql.close()

    def test_fdc_policy_rejects_unbound_id_or_provider(self):
        for field, value in (("fdc_id", "171689"), ("provider_kind", "tavily_extract")):
            with self.subTest(field=field):
                repo = NutritionProfileSourceRepository(SqliteDatabase(":memory:"))
                try:
                    changed = fdc_policy()
                    changed["source_spec"][field] = value
                    with self.assertRaises(NutritionRepositoryError):
                        repo.save_source_policy(changed)
                finally:
                    repo.sql.close()

    def test_fdc_policy_revision_uses_compare_and_set(self):
        repo = NutritionProfileSourceRepository(SqliteDatabase(":memory:"))
        try:
            source = repo.save_source_policy(fdc_policy())
            changed = fdc_policy()
            changed["compatibility_review"] = "Re-reviewed fixed FDC record"
            updated = repo.save_source_policy(changed, expected_revision=source["revision"])
            self.assertEqual(updated["revision"], 1)
            with self.assertRaises(NutritionRepositoryError) as caught:
                repo.save_source_policy(fdc_policy(), expected_revision=source["revision"])
            self.assertEqual(caught.exception.code, "revision_conflict")
            identity = {"name": "Apples, raw, with skin", "food_state": "raw",
                        "preparation_method": "mixed", "components_scope": "food_only",
                        "brand": None, "variant": None}
            with self.assertRaises(NutritionRepositoryError) as caught:
                repo.save_profile(profile_id="fdc-stale", user_id="u1", profile=fdc_profile(),
                                  food_identity=identity, source_id="usda-fdc-171688",
                                  source_policy_revision=source["revision"])
            self.assertEqual(caught.exception.code, "source_conflict")
        finally:
            repo.sql.close()

    def test_owner_boundary_and_cross_user_reuse_are_explicit(self):
        self.repo.save_profile(profile_id="private", user_id="u1", profile=profile(), food_identity=IDENTITY,
                               source_id="source-1", source_policy_revision=0)
        with self.assertRaisesRegex(NutritionRepositoryError, "another user"):
            self.repo.get_profile_for_user("u2", "private")
        cross = NutritionProfileSourceRepository(SqliteDatabase(":memory:"))
        try:
            source = cross.save_source_policy(policy(cross_user=True))
            cross.save_profile(profile_id="shared", user_id="u1", profile=profile(), food_identity=IDENTITY,
                               source_id="source-1", source_policy_revision=source["revision"], reusable=True)
            self.assertEqual(cross.get_profile_for_user("u2", "shared")["profile_id"], "shared")
        finally:
            cross.sql.close()

    def test_withdrawn_source_rejects_non_owner_historical_reuse_without_type_error(self):
        cross = NutritionProfileSourceRepository(SqliteDatabase(":memory:"))
        try:
            source = cross.save_source_policy(policy(cross_user=True))
            cross.save_profile(profile_id="shared-withdrawn", user_id="u1", profile=profile(),
                               food_identity=IDENTITY, source_id="source-1",
                               source_policy_revision=source["revision"], reusable=True)
            cross.withdraw_source_policy("source-1", expected_revision=source["revision"])
            with self.assertRaisesRegex(NutritionRepositoryError, "no longer active") as caught:
                cross.get_profile_for_user("u2", "shared-withdrawn", include_withdrawn=True)
            self.assertEqual(caught.exception.code, "source_unavailable")
        finally:
            cross.sql.close()

    def test_restart_round_trip_with_file_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrition.db")
            first_sql = SqliteDatabase(path)
            first = NutritionProfileSourceRepository(first_sql)
            source = first.save_source_policy(policy())
            first.save_profile(profile_id="p1", user_id="u1", profile=profile(), food_identity=IDENTITY,
                               source_id="source-1", source_policy_revision=source["revision"])
            first_sql.close()
            second_sql = SqliteDatabase(path)
            try:
                second = NutritionProfileSourceRepository(second_sql)
                self.assertEqual(second.get_source_policy("source-1")["revision"], 0)
                self.assertEqual(second.get_profile_for_user("u1", "p1")["profile_hash"], profile_hash(profile()))
            finally:
                second_sql.close()

    def test_two_connections_cannot_silently_overwrite_source_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrition.db")
            a_sql, b_sql = SqliteDatabase(path), SqliteDatabase(path)
            a, b = NutritionProfileSourceRepository(a_sql), NutritionProfileSourceRepository(b_sql)
            a.save_source_policy(policy())
            barrier = threading.Barrier(2)
            results = []

            def update(repo):
                barrier.wait()
                try:
                    results.append(("ok", repo.save_source_policy(policy(), expected_revision=0)["revision"]))
                except NutritionRepositoryError as error:
                    results.append((error.code, None))

            threads = [threading.Thread(target=update, args=(repo,)) for repo in (a, b)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            a_sql.close(); b_sql.close()
            self.assertEqual(sorted(result[0] for result in results), ["ok", "revision_conflict"])


if __name__ == "__main__":
    unittest.main()
