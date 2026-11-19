"""System source selection leaves confirmation and source authority explicit."""

from copy import deepcopy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from repositories.fdc_candidate_confirmation_repository import FdcCandidateConfirmationRepository
from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.fdc_profile_preview_repository import FdcProfilePreviewRepository
from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_profile_preview_service import FdcProfilePreviewService
from services.fdc_reviewed_selection_service import FdcReviewedSelectionService, FdcReviewedSelectionError
from services.nutrition_source_admission_service import source_policy_digest
from test_api_routes import ApiTestBase
from test_fdc_profile_preview_service import FakeClient, detail_document


ROOT = Path(__file__).resolve().parents[1]
ITEM = {"item_id": "scan-reviewed:0", "item_revision": 0, "name_zh": "蘋果",
        "confidence": 0.9, "weight_confidence": 0.65, "estimated_weight_g": 150,
        "food_state": "raw", "preparation_method": "mixed", "components_scope": "food_only",
        "brand": None, "variant": "with_skin", "validation_issues": []}


def reviewed_source(fdc_id="171688"):
    document = json.loads((ROOT / "config" / "nutrition_source_candidates" /
                           f"usda-fdc-{fdc_id}.json").read_text(encoding="utf-8"))
    policy = document["policy"]
    return {"policy": policy, "admission_review": document["admission_review"], "candidate": {
        "fdcId": fdc_id, "description": policy["source_spec"]["food_identity"]["name"],
        "dataType": "SR Legacy" if fdc_id == "171688" else "Foundation",
        "brandOwner": None, "foodCategory": None,
    }}


class SelectionFixture:
    def prepare(self):
        self.now = [1000.0]
        self.sql = SqliteDatabase(":memory:")
        self.addCleanup(self.sql.close)
        network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.scan = NutritionScanContextRepository(self.sql, clock=lambda: self.now[0])
        self.snapshots = FdcCandidateSnapshotRepository(
            self.sql, scan_context_repository=self.scan, clock=lambda: self.now[0])
        self.sources = NutritionProfileSourceRepository(self.sql)
        self.entries = [reviewed_source(), reviewed_source("1750340")]
        for entry in self.entries:
            self.sources.save_source_policy(entry["policy"])
        self.health = {name: {"status": "available"} for name in ("TFDA", "USDA FNDDS")}
        self.lookup = Mock(return_value={"status": "no_local_mapping"})

    def service(self, entries=None):
        return FdcReviewedSelectionService(
            scan_context_repository=self.scan, snapshot_repository=self.snapshots,
            source_repository=self.sources, local_lookup_factory=lambda _owner: self.lookup,
            official_health=self.health, reviewed_sources=self.entries if entries is None else entries)

    def save_scan(self, suffix="", **changes):
        scan_id = "scan-reviewed" + suffix
        self.scan.save_scan_context(user_id="user-a", scan_id=scan_id, scan_revision=0,
            items=[dict(ITEM, item_id=scan_id + ":0", **changes)], ttl_seconds=120)
        return {"authenticated_user_id": "user-a", "scan_id": scan_id, "scan_revision": 0}


class FdcReviewedSelectionTests(SelectionFixture, unittest.TestCase):
    def setUp(self):
        self.prepare()

    def test_unique_generic_match_keeps_name_weight_and_confidences_without_confirmation(self):
        request = self.save_scan()
        service = self.service()
        document, selection = service.select(**request)
        self.assertEqual(document["snapshot"]["items"][0]["candidates"][0]["fdcId"], "171688")
        self.assertEqual(document["snapshot"]["items"][0]["recognition_identity"]["name_zh"], "蘋果")
        self.assertEqual(selection["items"], [{"item_id": ITEM["item_id"], "weight_g": 150, "reason": "reviewed_match"}])
        self.assertTrue(selection["user_confirmation_required"])
        self.assertFalse(selection["photo_confidence_changed"])
        self.assertEqual(service.select(**request), (document, selection))
        saved = self.scan.get_scan_context(user_id="user-a", scan_id=request["scan_id"], scan_revision=0)
        self.assertEqual(saved["items"], [ITEM])
        self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS n FROM nutrition_scan_contexts")["n"], 1)

    def test_incompatible_unknown_low_confidence_and_weight_must_not_select(self):
        for index, changes in enumerate([
            {"variant": None}, {"variant": "without_skin"}, {"food_state": "prepared"},
            {"preparation_method": "unknown"}, {"brand": "visible-brand"},
            {"components_scope": "with_sides"}, {"confidence": 0.1},
            {"name_zh": "炒菜葉"}, {"validation_issues": ["uncertain"]},
            {"estimated_weight_g": None},
        ]):
            with self.subTest(changes=changes):
                document, selection = self.service().select(**self.save_scan(str(index), **changes))
                self.assertEqual(document["snapshot"]["items"][0]["candidates"], [])
                self.assertNotEqual(selection["items"][0]["reason"], "reviewed_match")

    def test_any_local_hit_conflict_partial_or_incompatible_stops_selection(self):
        for index, status in enumerate(("matched", "source_conflict", "incomplete_profile", "incompatible")):
            with self.subTest(status=status):
                self.lookup.return_value = {"status": status}
                document, selection = self.service().select(**self.save_scan(str(index)))
                self.assertEqual(document["snapshot"]["items"][0]["candidates"], [])
                self.assertEqual(selection["items"][0]["reason"], "local_priority")

    def test_unhealthy_or_failed_local_lookup_cannot_be_a_miss(self):
        request = self.save_scan()
        self.health["TFDA"]["status"] = "unavailable"
        with self.assertRaises(FdcReviewedSelectionError) as caught:
            self.service().select(**request)
        self.assertEqual(caught.exception.code, "local_unavailable")
        self.lookup.assert_not_called()
        self.health["TFDA"]["status"] = "available"
        self.lookup.side_effect = RuntimeError("private backend error")
        with self.assertRaises(FdcReviewedSelectionError) as caught:
            self.service().select(**request)
        self.assertEqual(caught.exception.code, "local_lookup_unavailable")

    def test_withdrawn_uninstalled_and_changed_policies_are_excluded(self):
        generic = self.entries[0]["policy"]
        current = self.sources.get_source_policy("usda-fdc-171688")
        self.sources.withdraw_source_policy("usda-fdc-171688", expected_revision=current["revision"])
        document, _ = self.service().select(**self.save_scan("withdrawn"))
        self.assertEqual(document["snapshot"]["items"][0]["candidates"], [])
        changed = deepcopy(generic)
        changed["compatibility_review"] += " Modified."
        self.sources.save_source_policy(changed, expected_revision=current["revision"] + 1)
        document, _ = self.service().select(**self.save_scan("changed"))
        self.assertEqual(document["snapshot"]["items"][0]["candidates"], [])
        self.assertEqual(self.service([]).select(**self.save_scan("empty"))[0]["snapshot"]["items"][0]["candidates"], [])

    def test_multiple_reviewed_matches_do_not_use_registry_order(self):
        duplicate = deepcopy(self.entries[0])
        policy = duplicate["policy"]
        policy["policy_id"] = "alternate-generic"
        spec = policy["source_spec"]
        spec.update(source_id="usda-fdc-12345", fdc_id="12345",
                    source_url="https://api.nal.usda.gov/fdc/v1/food/12345", table_id="fdc-12345-per-100g")
        duplicate["candidate"]["fdcId"] = "12345"
        duplicate["admission_review"].update(source_id="usda-fdc-12345", policy_sha256=source_policy_digest(policy))
        self.sources.save_source_policy(policy)
        for index, entries in enumerate(([self.entries[0], duplicate], [duplicate, self.entries[0]])):
            document, selection = self.service(entries).select(**self.save_scan(str(index)))
            self.assertEqual(selection["items"][0]["reason"], "ambiguous_reviewed_source")
            self.assertEqual(document["snapshot"]["items"][0]["candidates"], [])

    def test_raw_search_snapshot_cannot_be_rewritten_as_reviewed_selection(self):
        request = self.save_scan()
        raw = dict(self.entries[0]["candidate"], fdcId="99999")
        self.snapshots.save_candidates(user_id="user-a", scan_id=request["scan_id"], scan_revision=0,
                                       candidates_by_item={ITEM["item_id"]: [raw]})
        with self.assertRaises(ValueError) as caught:
            self.service().select(**request)
        self.assertEqual(caught.exception.code, "snapshot_conflict")


class FdcReviewedSelectionHttpTests(SelectionFixture, ApiTestBase):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.app_module._fdc_candidate_limiter.reset()

    def test_authenticated_scan_only_route_and_explicit_confirmation_preview_flow(self):
        self.save_scan()
        confirmations = FdcCandidateConfirmationRepository(
            self.sql, snapshot_repository=self.snapshots, clock=lambda: self.now[0])
        previews = FdcProfilePreviewRepository(self.sql, source_repository=self.sources, clock=lambda: self.now[0])
        # Synthetic transport fixture with original description; not a real-source capture claim.
        document = detail_document()
        document["payload"]["description"] = self.entries[0]["candidate"]["description"]
        numbers = {"1008": "208", "1003": "203", "1005": "205", "1004": "204",
                   "1093": "307", "1079": "291", "2000": "269", "1258": "606", "1257": "605"}
        for row in document["payload"]["foodNutrients"]:
            row["nutrient"]["number"] = numbers[row["nutrient"]["number"]]
        document["content_hash"] = hashlib.sha256(json.dumps(document["payload"], ensure_ascii=True,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        detail = FakeClient(document)
        preview_service = FdcProfilePreviewService(confirmation_repository=confirmations,
            scan_context_repository=self.scan, source_repository=self.sources,
            detail_client_factory=lambda: detail, clock=lambda: self.now[0])
        with ExitStack() as stack:
            stack.enter_context(self.mock_auth("user-a"))
            for name, value in {
                "fdc_reviewed_selection_route_enabled": True, "fdc_reviewed_selection_service": self.service(),
                "fdc_confirmation_route_enabled": True, "fdc_candidate_confirmation_repository": confirmations,
                "fdc_profile_preview_route_enabled": True, "fdc_profile_preview_service": preview_service,
                "fdc_profile_preview_repository": previews,
            }.items():
                stack.enter_context(patch.object(self.app_module, name, value))
            body = {"scan_id": "scan-reviewed", "scan_revision": 0}
            result = self.client.post("/nutrition/fdc/reviewed-selection", json=body, headers=self.auth_headers())
            self.assertEqual(result.status_code, 200, result.get_data(as_text=True))
            selected = result.get_json()
            self.assertEqual(selected["selection"]["items"][0]["weight_g"], 150)
            self.assertEqual(detail.calls, [])
            self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS n FROM nutrition_fdc_candidate_confirmations")["n"], 0)
            for extra in ({"fdc_id": "1750340"}, {"weight_g": 999}, {"nutrients": {"calories": 0}}):
                bad = self.client.post("/nutrition/fdc/reviewed-selection", json={**body, **extra}, headers=self.auth_headers())
                self.assertEqual(bad.status_code, 400)
            confirmation_body = {**body, "idempotency_key": "explicit-food-portion-choice", "confirmation": {
                "schema_version": "FdcCandidateConfirmationV1", "scan_revision": 0,
                "snapshot_digest": selected["snapshot"]["snapshot_digest"], "items": [{
                    "item_id": ITEM["item_id"], "decision": "confirm", "candidate_fdc_id": "171688"}]}}
            confirmed = self.client.post("/nutrition/fdc/confirmation", json=confirmation_body, headers=self.auth_headers())
            self.assertEqual(confirmed.status_code, 202, confirmed.get_data(as_text=True))
            value = confirmed.get_json()
            self.assertEqual(value["issued_scan_revision"], 1)
            replay = self.client.post("/nutrition/fdc/confirmation", json=confirmation_body, headers=self.auth_headers())
            self.assertEqual(replay.get_json()["confirmation_id"], value["confirmation_id"])
            result = self.client.post("/nutrition/fdc/profile-preview", json={
                "confirmation_id": value["confirmation_id"], "scan_id": "scan-reviewed",
                "issued_scan_revision": 1, "item_id": ITEM["item_id"]}, headers=self.auth_headers())
            self.assertEqual(result.status_code, 200, result.get_data(as_text=True))
            self.assertEqual(result.get_json()["preview"]["portion"]["values"]["calories"], 78)
            self.assertEqual(len(detail.calls), 1)
            self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS n FROM nutrition_profiles")["n"], 0)

    def test_auth_feature_owner_and_expiry_guards(self):
        self.save_scan()
        body = {"scan_id": "scan-reviewed", "scan_revision": 0}
        self.assertEqual(self.client.post("/nutrition/fdc/reviewed-selection", json=body).status_code, 401)
        with self.mock_auth(), patch.object(self.app_module, "fdc_reviewed_selection_route_enabled", False):
            self.assertEqual(self.client.post("/nutrition/fdc/reviewed-selection", json=body,
                                             headers=self.auth_headers()).status_code, 503)
        with patch.object(self.app_module, "fdc_reviewed_selection_route_enabled", True), \
                patch.object(self.app_module, "fdc_reviewed_selection_service", self.service()):
            with self.mock_auth("user-b"):
                self.assertEqual(self.client.post("/nutrition/fdc/reviewed-selection", json=body,
                                                 headers=self.auth_headers()).status_code, 403)
            self.now[0] += 121
            with self.mock_auth():
                self.assertEqual(self.client.post("/nutrition/fdc/reviewed-selection", json=body,
                                                 headers=self.auth_headers()).status_code, 409)
