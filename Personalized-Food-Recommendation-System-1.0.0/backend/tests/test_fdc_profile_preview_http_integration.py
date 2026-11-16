import unittest
from unittest.mock import patch

from repositories.fdc_candidate_confirmation_repository import FdcCandidateConfirmationRepository
from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.fdc_profile_preview_repository import FdcProfilePreviewRepository
from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_profile_preview_service import FdcProfilePreviewService
from services.fooddata_central_selection_service import CONFIRMATION_SCHEMA_VERSION
from test_api_routes import ApiTestBase
from test_fdc_profile_preview_repository import CANDIDATE, ITEM
from test_fdc_profile_preview_service import FakeClient, detail_document, reviewed_policy


class FdcProfilePreviewHttpIntegrationTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.now = [1000.0]
        self.sql = SqliteDatabase(":memory:")
        self.scan = NutritionScanContextRepository(self.sql, clock=lambda: self.now[0])
        self.snapshots = FdcCandidateSnapshotRepository(
            self.sql, scan_context_repository=self.scan, clock=lambda: self.now[0])
        self.confirmations = FdcCandidateConfirmationRepository(
            self.sql, snapshot_repository=self.snapshots, clock=lambda: self.now[0])
        self.sources = NutritionProfileSourceRepository(self.sql)
        self.sources.save_source_policy(reviewed_policy())
        self.scan.save_scan_context(
            user_id="user-a", scan_id="scan-1", scan_revision=0,
            items=[ITEM], ttl_seconds=120)
        snapshot = self.snapshots.save_candidates(
            user_id="user-a", scan_id="scan-1", scan_revision=0,
            candidates_by_item={ITEM["item_id"]: [CANDIDATE]})["snapshot"]
        self.confirmation = self.confirmations.record_confirmation(
            authenticated_user_id="user-a", actor_id="user-a", scan_id="scan-1",
            scan_revision=0, idempotency_key="confirm-http",
            confirmation={
                "schema_version": CONFIRMATION_SCHEMA_VERSION,
                "snapshot_digest": snapshot["snapshot_digest"], "scan_revision": 0,
                "items": [{"item_id": ITEM["item_id"], "decision": "confirm",
                           "candidate_fdc_id": "171688"}],
            })
        self.preview_repo = FdcProfilePreviewRepository(
            self.sql, source_repository=self.sources, clock=lambda: self.now[0])
        self.preview_service = FdcProfilePreviewService(
            confirmation_repository=self.confirmations,
            scan_context_repository=self.scan,
            source_repository=self.sources,
            detail_client_factory=lambda: FakeClient(detail_document()),
            clock=lambda: self.now[0], monotonic=lambda: 20.0)

    def tearDown(self):
        self.sql.close()
        super().tearDown()

    def _preview_body(self, **changes):
        body = {
            "confirmation_id": self.confirmation["confirmation_id"],
            "scan_id": "scan-1", "issued_scan_revision": 1,
            "item_id": ITEM["item_id"],
        }
        body.update(changes)
        return body

    def test_real_route_preview_accept_and_replay_use_isolated_sqlite(self):
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_profile_preview_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_accept_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_preview_service", self.preview_service), \
                patch.object(self.app_module, "fdc_profile_preview_repository", self.preview_repo):
            preview_response = self.client.post(
                "/nutrition/fdc/profile-preview", json=self._preview_body(),
                headers=self.auth_headers())
            self.assertEqual(preview_response.status_code, 200)
            preview = preview_response.get_json()
            self.assertEqual(preview["status"], "preview_ready")
            self.assertEqual(preview["fdc_id"], "171688")
            self.assertEqual(preview["weight_g"], 150.0)
            self.assertEqual(preview["preview"]["portion"]["values"]["calories"], 78.0)
            self.assertFalse(preview["profile_written"])
            self.assertFalse(preview["photo_confidence_changed"])

            accept_response = self.client.post(
                "/nutrition/fdc/profile-accept",
                json={"preview_id": preview["preview_id"], "idempotency_key": "accept-http"},
                headers=self.auth_headers())
            self.assertEqual(accept_response.status_code, 200)
            accepted = accept_response.get_json()
            self.assertEqual(accepted["status"], "accepted")
            self.assertTrue(accepted["profile_written"])
            self.assertFalse(accepted["replayed"])

            replay_response = self.client.post(
                "/nutrition/fdc/profile-accept",
                json={"preview_id": preview["preview_id"], "idempotency_key": "accept-http"},
                headers=self.auth_headers())
            self.assertEqual(replay_response.status_code, 200)
            self.assertTrue(replay_response.get_json()["replayed"])

        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_profiles", ())['count'], 1)

    def test_confirmation_route_issues_revision_for_server_weight_preview_without_profile_write(self):
        scan_id = "scan-preview-flow"
        item = {**ITEM, "item_id": f"{scan_id}:0"}
        self.scan.save_scan_context(
            user_id="user-a", scan_id=scan_id, scan_revision=0, items=[item], ttl_seconds=120)
        snapshot = self.snapshots.save_candidates(
            user_id="user-a", scan_id=scan_id, scan_revision=0,
            candidates_by_item={item["item_id"]: [CANDIDATE]})["snapshot"]
        fake_client = FakeClient(detail_document())
        preview_service = FdcProfilePreviewService(
            confirmation_repository=self.confirmations,
            scan_context_repository=self.scan,
            source_repository=self.sources,
            detail_client_factory=lambda: fake_client,
            clock=lambda: self.now[0], monotonic=lambda: 20.0)
        confirmation_body = {
            "scan_id": scan_id, "scan_revision": 0, "idempotency_key": "confirm-preview-flow",
            "confirmation": {
                "schema_version": CONFIRMATION_SCHEMA_VERSION,
                "snapshot_digest": snapshot["snapshot_digest"], "scan_revision": 0,
                "items": [{"item_id": item["item_id"], "decision": "confirm",
                           "candidate_fdc_id": "171688"}],
            },
        }
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_confirmation_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_preview_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", self.confirmations), \
                patch.object(self.app_module, "fdc_profile_preview_service", preview_service), \
                patch.object(self.app_module, "fdc_profile_preview_repository", self.preview_repo):
            confirmation_response = self.client.post(
                "/nutrition/fdc/confirmation", json=confirmation_body, headers=self.auth_headers())
            self.assertEqual(confirmation_response.status_code, 202)
            issued = confirmation_response.get_json()
            self.assertEqual(issued["issued_scan_revision"], 1)
            self.assertFalse(issued["photo_confidence_changed"])

            forged_weight_response = self.client.post(
                "/nutrition/fdc/profile-preview",
                json={"confirmation_id": issued["confirmation_id"], "scan_id": scan_id,
                      "issued_scan_revision": 1, "item_id": item["item_id"], "weight_g": 1},
                headers=self.auth_headers())
            self.assertEqual(forged_weight_response.status_code, 400)
            self.assertEqual(fake_client.calls, [])

            preview_response = self.client.post(
                "/nutrition/fdc/profile-preview",
                json={"confirmation_id": issued["confirmation_id"], "scan_id": scan_id,
                      "issued_scan_revision": issued["issued_scan_revision"], "item_id": item["item_id"]},
                headers=self.auth_headers())

        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.get_json()
        self.assertEqual(preview["issued_scan_revision"], issued["issued_scan_revision"])
        self.assertEqual(preview["item_id"], item["item_id"])
        self.assertEqual(preview["fdc_id"], "171688")
        self.assertEqual(preview["weight_g"], 150.0)
        self.assertEqual(preview["preview"]["portion"]["weight_g"], 150.0)
        self.assertEqual(preview["preview"]["portion"]["values"]["calories"], 78.0)
        self.assertFalse(preview["profile_written"])
        self.assertFalse(preview["photo_confidence_changed"])
        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(fake_client.calls[0][0], "171688")
        self.assertTrue(fake_client.closed)
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_profiles", ())['count'], 0)
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_fdc_profile_previews", ())['count'], 1)

    def test_real_route_rejects_injected_provider_fields_before_service(self):
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_profile_preview_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_preview_service", self.preview_service):
            response = self.client.post(
                "/nutrition/fdc/profile-preview",
                json=self._preview_body(fdc_id="99999", weight_g=1,
                                        profile={"calories": 1}, document={}),
                headers=self.auth_headers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
