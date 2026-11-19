"""Source admission uses server evidence; fixtures grant no publisher rights."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.sqlite_db import SqliteDatabase
from services.nutrition_source_admission_service import (
    NutritionSourceAdmissionError, source_policy_digest, validate_source_admission,
)
from services.web_nutrition_service import (
    PRODUCTION_SOURCE_REGISTRY, WebNutritionError, build_production_web_registry,
)
from test_web_nutrition import fixture


CANDIDATE_PATH = (Path(__file__).resolve().parents[1] / "config" /
                  "nutrition_source_candidates" / "usda-fdc-1750340.json")


def review_for(policy):
    return {
        "source_id": policy["source_spec"]["source_id"],
        "policy_sha256": source_policy_digest(policy),
        "provider_kind": "tavily_extract",
        "publisher_rights_approved": True, "provider_terms_approved": True,
        "deletion_requirement": "not_required", "cross_user_cache_approved": False,
        "reviewer": "offline-test", "reviewed_at": "2026-11-16T00:00:00+08:00",
        "evidence_urls": deepcopy(policy["rights"]["evidence_urls"]),
    }


class NutritionSourceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.item, self.policy, _ = fixture()
        self.review = review_for(self.policy)
        self.candidate = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
        self.network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def assert_denied(self, code, *, policy=None, review=None):
        with self.assertRaises(NutritionSourceAdmissionError) as caught:
            validate_source_admission(self.policy if policy is None else policy,
                                      self.review if review is None else review)
        self.assertEqual(caught.exception.code, code)

    def test_review_is_required_even_when_legacy_policy_has_all_rights_flags(self):
        self.assert_denied("admission_review_required", review={})
        with self.assertRaises(WebNutritionError) as caught:
            build_production_web_registry([self.policy])
        self.assertEqual(caught.exception.code, "admission_review_required")

    def test_approved_web_policy_is_copied_and_matches_only_reviewed_identity(self):
        registry = build_production_web_registry([self.policy], admission_reviews=[self.review])
        self.policy["accepted_names"].append("unreviewed")
        self.review["publisher_rights_approved"] = False
        self.assertEqual(len(registry.compatible(self.item)), 1)
        self.assertEqual(registry.compatible(dict(self.item, name_zh="unreviewed")), [])

    def test_any_policy_change_invalidates_review_including_alias_rights_and_nutrient_choice(self):
        for mutate in (
            lambda value: value["accepted_names"].append("unreviewed"),
            lambda value: value["rights"].update(retention_policy="New retention"),
            lambda value: value["source_spec"].update(preferred_nutrient_numbers={"calories": "958"}),
        ):
            with self.subTest(mutation=mutate):
                changed = deepcopy(self.policy)
                mutate(changed)
                self.assert_denied("policy_changed", policy=changed)

    def test_publisher_and_actual_provider_terms_need_separate_approval(self):
        for field, code in (("publisher_rights_approved", "publisher_rights_unapproved"),
                            ("provider_terms_approved", "provider_terms_unapproved")):
            with self.subTest(field=field):
                changed = dict(self.review, **{field: False})
                self.assert_denied(code, review=changed)
                changed[field] = 1
                self.assert_denied("invalid_review", review=changed)

    def test_delete_required_and_unknown_retention_are_excluded(self):
        for value, code in (("on_withdrawal", "purge_unavailable"),
                            ("unknown", "retention_unreviewed"), (None, "retention_unreviewed")):
            with self.subTest(value=value):
                self.assert_denied(code, review=dict(self.review, deletion_requirement=value))

    def test_hash_and_source_bindings_prevent_reusing_another_review(self):
        self.assert_denied("source_mismatch", review=dict(self.review, source_id="other"))
        self.assert_denied("policy_changed", review=dict(self.review, policy_sha256="0" * 64))

    def test_cross_user_cache_needs_both_policy_and_account_approval(self):
        changed = deepcopy(self.policy)
        changed["rights"].update(reuse_scope="cross_user", provider_cache_scope="cross_user_approved")
        review = review_for(changed)
        self.assert_denied("cross_user_unapproved", policy=changed, review=review)
        review["cross_user_cache_approved"] = True
        self.assertEqual(validate_source_admission(changed, review), changed)
        changed["rights"]["provider_cache_scope"] = "server_internal"
        review["policy_sha256"] = source_policy_digest(changed)
        self.assert_denied("cross_user_unapproved", policy=changed, review=review)

    def test_single_request_and_no_provider_storage_cannot_enter_durable_pipeline(self):
        for scope, provider_scope in (("single_request", "none"), ("server_internal", "none")):
            changed = deepcopy(self.policy)
            changed["rights"].update(reuse_scope=scope, provider_cache_scope=provider_scope)
            self.assert_denied("retention_not_allowed", policy=changed, review=review_for(changed))

    def test_disabled_rights_are_rejected_even_with_positive_admission_review(self):
        for field in ("search_allowed", "extract_allowed", "snapshot_allowed", "reuse_allowed"):
            with self.subTest(field=field):
                changed = deepcopy(self.policy)
                changed["rights"][field] = False
                self.assert_denied("rights_not_allowed", policy=changed, review=review_for(changed))

    def test_exact_review_shape_time_reviewer_and_evidence_are_required(self):
        for change in ({"reviewed_at": "2026-11-16"}, {"reviewer": " "},
                       {"evidence_urls": []}, {"evidence_urls": ["http://example.com/terms"]},
                       {"evidence_urls": ["https://example.com/unreviewed"]},
                       {"evidence_urls": self.review["evidence_urls"] * 2},
                       {"provider_kind": "browser_crawl"}, {"extra": True}):
            with self.subTest(change=change):
                with self.assertRaises(NutritionSourceAdmissionError):
                    validate_source_admission(self.policy, dict(self.review, **change))

    def test_production_builder_rejects_duplicate_or_orphan_reviews(self):
        for policies, reviews in (([self.policy], [self.review, self.review]),
                                  ([], [self.review]), ([self.policy], [])):
            with self.subTest(policies=len(policies), reviews=len(reviews)):
                with self.assertRaises(WebNutritionError):
                    build_production_web_registry(policies, admission_reviews=reviews)

    def test_real_fdc_candidate_is_separate_from_web_and_synthetic_phone_fixture(self):
        policy, review = self.candidate["policy"], self.candidate["admission_review"]
        checked = validate_source_admission(policy, review)
        self.assertEqual(checked["source_spec"]["fdc_id"], "1750340")
        self.assertEqual(checked["target_identity"]["variant"], "fuji_with_skin")
        self.assertNotIn("蘋果", checked["accepted_names"])
        self.assertEqual(checked["source_spec"]["preferred_nutrient_numbers"]["calories"], "957")
        with self.assertRaises(WebNutritionError) as caught:
            build_production_web_registry([policy], admission_reviews=[review])
        self.assertEqual(caught.exception.code, "provider_mismatch")
        self.assertEqual(PRODUCTION_SOURCE_REGISTRY.compatible(self.item), [])

    def test_fdc_cannot_be_relabelled_as_tavily_even_with_a_new_review_hash(self):
        for disguise in ({}, {"provider_kind": "tavily_extract"}):
            policy = deepcopy(self.candidate["policy"])
            policy["source_spec"].pop("provider_kind")
            policy["source_spec"].update(disguise)
            self.assert_denied("provider_mismatch", policy=policy, review=review_for(policy))

    def test_real_review_can_be_persisted_with_existing_sqlite_cas_and_withdrawal(self):
        policy = validate_source_admission(self.candidate["policy"], self.candidate["admission_review"])
        source_id = policy["source_spec"]["source_id"]
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "admission.db")
            sql = SqliteDatabase(database_path)
            try:
                repository = NutritionProfileSourceRepository(sql)
                saved = repository.save_source_policy(policy)
                self.assertEqual(saved["revision"], 0)
            finally:
                sql.close()
            sql = SqliteDatabase(database_path)
            try:
                repository = NutritionProfileSourceRepository(sql)
                reloaded = repository.get_source_policy(source_id)
                self.assertEqual(source_policy_digest(reloaded["policy"]),
                                 self.candidate["admission_review"]["policy_sha256"])
                repository.withdraw_source_policy(source_id, expected_revision=0)
                self.assertIsNone(repository.get_source_policy(source_id))
                withdrawn = repository.get_source_policy(source_id, include_withdrawn=True)
                self.assertEqual(withdrawn["status"], "withdrawn")
                self.assertEqual(withdrawn["policy"], policy)
                self.assertEqual(sql.query_one("SELECT COUNT(*) AS n FROM nutrition_profiles")["n"], 0)
            finally:
                sql.close()


if __name__ == "__main__":
    unittest.main()
