import hashlib
import json
import unittest
from copy import deepcopy

from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_profile_preview_service import (
    FdcProfilePreviewError,
    FdcProfilePreviewService,
)
from services.fooddata_central_adapter import RETRIEVAL_VERSION


def reviewed_policy():
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
        "policy_id": "policy-usda-fdc-171688", "accepted_names": ["蘋果", identity["name"]],
        "target_identity": {key: identity[key] for key in identity if key != "name"},
        "source_spec": {"provider_kind": "usda_fdc_api", "source_id": "usda-fdc-171688",
                        "fdc_id": "171688", "source_url": "https://api.nal.usda.gov/fdc/v1/food/171688",
                        "adapter_version": "usda-fdc-json-v1", "retrieval_version": RETRIEVAL_VERSION,
                        "table_id": "fdc-171688-per-100g", "food_identity": identity},
        "match_policy": "reference_only", "compatibility_review": "Exact raw apple reference reviewed",
        "rights": rights,
        "server_review": {"status": "approved", "provider_kind": "usda_fdc_api",
                          "reviewer": "nutrition-review", "reviewed_at": "2026-11-14T00:00:00Z"},
    }


def detail_document():
    values = {
        "1008": ("Energy", "kcal", 52.0), "1003": ("Protein", "g", 0.26),
        "1005": ("Carbohydrate", "g", 13.81), "1004": ("Total lipid (fat)", "g", 0.17),
        "1093": ("Sodium, Na", "mg", 1.0), "1079": ("Fiber, total dietary", "g", 2.4),
        "2000": ("Sugars, total", "g", 10.39), "1258": ("Fatty acids, total saturated", "g", 0.028),
        "1257": ("Fatty acids, total trans", "g", 0.0),
    }
    payload = {"fdcId": 171688, "description": "Apples, raw, with skin", "dataType": "SR Legacy",
               "foodNutrients": [{"nutrient": {"number": number, "name": name, "unitName": unit},
                                   "amount": amount}
                                  for number, (name, unit, amount) in values.items()]}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {"url": "https://api.nal.usda.gov/fdc/v1/food/171688", "payload": payload,
            "content_hash": hashlib.sha256(encoded.encode()).hexdigest(),
            "retrieved_at": "2026-11-14T05:00:00+00:00", "retrieval_version": RETRIEVAL_VERSION}


class FakeConfirmation:
    def __init__(self, item_revision=1):
        self.calls = []
        self.item_revision = item_revision
        self.confirmation = {
            "confirmation_id": "confirm-1", "scan_id": "scan-1",
            "issued_scan_revision": 1, "snapshot_digest": "a" * 64,
            "confirmed_items": [{"item_id": "scan-1:0", "item_revision": item_revision,
                                 "confirmed_fdc_id": "171688"}],
        }

    def get_confirmation(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.confirmation)


class FakeScanContext:
    def __init__(self):
        self.calls = []
        self.context = {
            "user_id": "user-1", "scan_id": "scan-1", "scan_revision": 1,
            "item_set_hash": "b" * 64, "status": "active", "items": [{
                "item_id": "scan-1:0", "item_revision": 1, "name_zh": "蘋果",
                "food_state": "raw", "preparation_method": "mixed",
                "components_scope": "food_only", "brand": None, "variant": None,
                "estimated_weight_g": 150, "confidence": 0.9,
                "weight_confidence": 0.8, "validation_issues": [],
            }],
        }

    def get_scan_context(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.context)


class FakeClient:
    def __init__(self, document, on_get=None):
        self.document = document
        self.on_get = on_get
        self.calls = []
        self.closed = False

    def get_food(self, fdc_id, *, deadline):
        self.calls.append((fdc_id, deadline))
        if self.on_get:
            self.on_get()
        return deepcopy(self.document)

    def close(self):
        self.closed = True


class FdcProfilePreviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.sql = SqliteDatabase(":memory:")
        self.source = NutritionProfileSourceRepository(self.sql)
        self.source.save_source_policy(reviewed_policy())
        self.confirmation = FakeConfirmation()
        self.context = FakeScanContext()
        self.clients = []

    def tearDown(self):
        self.sql.close()

    def service(self, on_get=None):
        def factory():
            client = FakeClient(detail_document(), on_get=on_get)
            self.clients.append(client)
            return client
        return FdcProfilePreviewService(
            confirmation_repository=self.confirmation,
            scan_context_repository=self.context,
            source_repository=self.source,
            detail_client_factory=factory,
            clock=lambda: 1000.0,
            monotonic=lambda: 20.0,
        )

    def configure_bok_choy(self, *, source_state, source_preparation):
        source_name = "Cabbage, chinese (pak-choi)"
        source_identity = {
            "name": source_name, "food_state": source_state,
            "preparation_method": source_preparation, "components_scope": "food_only",
            "brand": None, "variant": None,
        }
        policy = reviewed_policy()
        policy["policy_id"] = "policy-usda-fdc-170390"
        policy["accepted_names"] = ["青江菜", source_name]
        policy["target_identity"] = {key: source_identity[key] for key in
                                      ("food_state", "preparation_method", "components_scope", "brand", "variant")}
        policy["source_spec"].update({
            "source_id": "usda-fdc-170390", "fdc_id": "170390",
            "source_url": "https://api.nal.usda.gov/fdc/v1/food/170390",
            "table_id": "fdc-170390-per-100g", "food_identity": source_identity,
        })
        self.source.save_source_policy(policy)
        self.confirmation.confirmation["confirmed_items"][0]["confirmed_fdc_id"] = "170390"
        self.context.context["items"][0].update({
            "name_zh": "青江菜", "food_state": "prepared",
            "preparation_method": "stir_fried", "components_scope": "food_only",
        })

    def test_raw_bok_choy_reference_cannot_preview_stir_fried_estimated_portion(self):
        self.configure_bok_choy(source_state="raw", source_preparation="mixed")
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(
                authenticated_user_id="user-1", confirmation_id="confirm-1",
                scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "identity_mismatch")
        self.assertEqual(self.clients, [])
        self.assertIsNone(self.source.get_profile_for_user("user-1", "preview-profile"))

    def test_boiled_bok_choy_reference_cannot_preview_stir_fried_scan(self):
        self.configure_bok_choy(source_state="prepared", source_preparation="boiled")
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(
                authenticated_user_id="user-1", confirmation_id="confirm-1",
                scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "identity_mismatch")
        self.assertEqual(self.clients, [])

    def test_success_uses_server_owned_id_policy_identity_and_weight(self):
        result = self.service().preview(
            authenticated_user_id="user-1", confirmation_id="confirm-1",
            scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["fdc_id"], "171688")
        self.assertEqual(result["weight_g"], 150)
        self.assertEqual(result["preview"]["portion"]["values"]["calories"], 78.0)
        self.assertFalse(result["profile_written"])
        self.assertFalse(result["photo_confidence_changed"])
        self.assertEqual(self.clients[0].calls[0][0], "171688")
        self.assertTrue(self.clients[0].closed)

    def test_unknown_server_weight_fails_without_provider_call(self):
        self.context.context["items"][0]["estimated_weight_g"] = None
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                                   scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "invalid_portion")
        self.assertEqual(self.clients, [])

    def test_policy_withdrawal_during_fetch_is_rejected(self):
        def withdraw():
            self.source.withdraw_source_policy("usda-fdc-171688", expected_revision=0)
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service(on_get=withdraw).preview(
                authenticated_user_id="user-1", confirmation_id="confirm-1",
                scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "source_unavailable")

    def test_confirmation_revision_change_during_fetch_is_rejected(self):
        original = self.confirmation.get_confirmation
        calls = {"count": 0}

        def changed(**kwargs):
            calls["count"] += 1
            result = original(**kwargs)
            if calls["count"] > 1:
                result["issued_scan_revision"] = 2
            return result

        self.confirmation.get_confirmation = changed
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(
                authenticated_user_id="user-1", confirmation_id="confirm-1",
                scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "revision_conflict")

    def test_scan_identity_change_during_fetch_is_rejected(self):
        original = self.context.get_scan_context
        calls = {"count": 0}

        def changed(**kwargs):
            calls["count"] += 1
            result = original(**kwargs)
            if calls["count"] > 1:
                result["items"][0]["estimated_weight_g"] = 175
            return result

        self.context.get_scan_context = changed
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(
                authenticated_user_id="user-1", confirmation_id="confirm-1",
                scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "authorization_changed")

    def test_item_revision_mismatch_and_wrong_policy_id_fail_closed(self):
        self.confirmation.confirmation["confirmed_items"][0]["item_revision"] = 2
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                                   scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "revision_conflict")

        self.confirmation.confirmation["confirmed_items"][0]["item_revision"] = 1
        self.confirmation.confirmation["confirmed_items"][0]["confirmed_fdc_id"] = "171689"
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                                   scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "source_unavailable")

    def test_stale_context_and_unconfirmed_item_do_not_fetch(self):
        self.context.context["status"] = "superseded"
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                                   scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "stale_revision")
        self.assertEqual(self.clients, [])

        self.context.context["status"] = "active"
        self.confirmation.confirmation["confirmed_items"] = []
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                                   scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "confirmation_required")
        self.assertEqual(self.clients, [])

    def test_scan_identity_mismatch_is_rejected_before_provider_call(self):
        self.context.context["items"][0]["food_state"] = "prepared"
        with self.assertRaises(FdcProfilePreviewError) as caught:
            self.service().preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                                   scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "identity_mismatch")
        self.assertEqual(self.clients, [])

    def test_provider_document_id_mismatch_is_rejected_and_never_persisted(self):
        def factory():
            payload = detail_document()
            payload["payload"]["fdcId"] = 171689
            client = FakeClient(payload)
            self.clients.append(client)
            return client

        service = FdcProfilePreviewService(
            confirmation_repository=self.confirmation,
            scan_context_repository=self.context,
            source_repository=self.source,
            detail_client_factory=factory,
            clock=lambda: 1000.0,
            monotonic=lambda: 20.0,
        )
        with self.assertRaises(FdcProfilePreviewError) as caught:
            service.preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                            scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "source_conflict")
        self.assertIsNone(self.source.get_profile_for_user("user-1", "preview-profile"))

    def test_malformed_provider_document_maps_to_typed_error(self):
        def factory():
            client = FakeClient({"payload": None})
            self.clients.append(client)
            return client

        service = FdcProfilePreviewService(
            confirmation_repository=self.confirmation,
            scan_context_repository=self.context,
            source_repository=self.source,
            detail_client_factory=factory,
            clock=lambda: 1000.0,
            monotonic=lambda: 20.0,
        )
        with self.assertRaises(FdcProfilePreviewError) as caught:
            service.preview(authenticated_user_id="user-1", confirmation_id="confirm-1",
                            scan_id="scan-1", issued_scan_revision=1, item_id="scan-1:0")
        self.assertEqual(caught.exception.code, "detail_invalid")


if __name__ == "__main__":
    unittest.main()
