import unittest
from copy import deepcopy

from services.fdc_source_policy_service import (
    FdcSourcePolicyError, validate_fdc_source_policy, validate_fdc_source_spec,
)


def policy():
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
        "policy_id": "policy-usda-fdc-171688", "accepted_names": ["蘋果"],
        "target_identity": {key: identity[key] for key in identity if key != "name"},
        "source_spec": {"provider_kind": "usda_fdc_api", "source_id": "usda-fdc-171688",
                        "fdc_id": fdc_id, "source_url": "https://api.nal.usda.gov/fdc/v1/food/171688",
                        "adapter_version": "usda-fdc-json-v1", "retrieval_version": "usda-fdc-api-v1",
                        "table_id": "fdc-171688-per-100g", "food_identity": identity},
        "match_policy": "reference_only", "compatibility_review": "Exact raw apple reference reviewed",
        "rights": rights,
        "server_review": {"status": "approved", "provider_kind": "usda_fdc_api",
                          "reviewer": "nutrition-review", "reviewed_at": "2026-11-14T00:00:00Z"},
    }


class FdcSourcePolicyTests(unittest.TestCase):
    def test_valid_reviewed_policy_round_trips_without_mutation(self):
        original = policy()
        result = validate_fdc_source_policy(original)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_candidate_search_output_is_not_promotable(self):
        candidate = {"fdcId": "171688", "description": "Apples, raw, with skin", "dataType": "SR Legacy"}
        with self.assertRaises(FdcSourcePolicyError) as ctx:
            validate_fdc_source_policy(candidate)
        self.assertEqual(ctx.exception.code, "invalid_policy")

    def test_fdc_id_and_url_must_match(self):
        for field, value in (("fdc_id", "171689"),
                             ("source_url", "https://api.nal.usda.gov/fdc/v1/food/171689")):
            changed = policy()
            changed["source_spec"][field] = value
            with self.assertRaises(FdcSourcePolicyError) as ctx:
                validate_fdc_source_policy(changed)
            self.assertIn(ctx.exception.code, {"source_mismatch", "invalid_fdc_id"})

    def test_table_and_versions_are_fixed(self):
        for field, value in (("table_id", "fdc-171688-per-serving"),
                             ("adapter_version", "usda-fdc-json-v0"),
                             ("retrieval_version", "usda-fdc-api-v0")):
            changed = policy()
            changed["source_spec"][field] = value
            with self.assertRaises(FdcSourcePolicyError) as ctx:
                validate_fdc_source_policy(changed)
            self.assertEqual(ctx.exception.code, "invalid_version" if field.endswith("version") else "source_mismatch")

    def test_unknown_identity_values_are_not_wildcards(self):
        changed = policy()
        changed["target_identity"]["food_state"] = "unknown"
        with self.assertRaises(FdcSourcePolicyError) as ctx:
            validate_fdc_source_policy(changed)
        self.assertEqual(ctx.exception.code, "identity_mismatch")

        changed = policy()
        changed["source_spec"]["food_identity"]["brand"] = "unknown"
        with self.assertRaises(FdcSourcePolicyError) as ctx:
            validate_fdc_source_policy(changed)
        self.assertEqual(ctx.exception.code, "identity_mismatch")

    def test_provider_rights_and_server_approval_are_required(self):
        changed = policy()
        changed["source_spec"]["provider_kind"] = "tavily_extract"
        with self.assertRaises(FdcSourcePolicyError) as ctx:
            validate_fdc_source_policy(changed)
        self.assertEqual(ctx.exception.code, "invalid_provider")

        changed = policy()
        changed["rights"].pop("snapshot_allowed")
        with self.assertRaises(FdcSourcePolicyError) as ctx:
            validate_fdc_source_policy(changed)
        self.assertEqual(ctx.exception.code, "invalid_policy")

        changed = policy()
        changed["server_review"]["status"] = "candidate"
        with self.assertRaises(FdcSourcePolicyError) as ctx:
            validate_fdc_source_policy(changed)
        self.assertEqual(ctx.exception.code, "invalid_review")

    def test_spec_validator_does_not_accept_numeric_or_padded_ids(self):
        for value in (171688, "0171688", "", "not-a-number"):
            spec = policy()["source_spec"]
            spec["fdc_id"] = value
            with self.assertRaises(FdcSourcePolicyError) as ctx:
                validate_fdc_source_spec(spec)
            self.assertEqual(ctx.exception.code, "invalid_fdc_id")


if __name__ == "__main__":
    unittest.main()
