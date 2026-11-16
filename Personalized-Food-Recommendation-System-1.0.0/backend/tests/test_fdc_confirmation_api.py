import unittest
from unittest.mock import patch

from repositories.fdc_candidate_confirmation_repository import FdcCandidateConfirmationRepositoryError
from test_api_routes import ApiTestBase


class _ConfirmationStub:
    def __init__(self):
        self.calls = []

    def record_confirmation(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "confirmation_id": "confirmation-1",
            "status": "confirmed_pending_revision",
            "scan_id": kwargs["scan_id"],
            "scan_revision": kwargs["scan_revision"],
            "snapshot_digest": "a" * 64,
            "items": [{"item_id": "scan-1:0", "status": "confirmed_pending_revision",
                       "confirmed_fdc_id": "12345"}],
            "requires_new_scan_revision": True,
            "issued_scan_revision": kwargs["scan_revision"] + 1,
            "requires_detail_replay": True,
            "photo_confidence_changed": False,
            "replayed": False,
        }


class FdcConfirmationApiTests(ApiTestBase):
    def _body(self, **changes):
        body = {
            "user_id": "user-a", "scan_id": "scan-1", "scan_revision": 0,
            "idempotency_key": "confirmation-1",
            "confirmation": {
                "schema_version": "FdcCandidateConfirmationV1",
                "snapshot_digest": "a" * 64, "scan_revision": 0,
                "items": [{"item_id": "scan-1:0", "decision": "confirm",
                            "candidate_fdc_id": "12345"}],
            },
        }
        body.update(changes)
        return body

    def test_requires_authentication_before_feature_gate(self):
        response = self.client.post("/nutrition/fdc/confirmation", json=self._body())
        self.assertEqual(response.status_code, 401)

    def test_default_feature_off_is_fail_closed(self):
        with self.mock_auth("user-a"):
            response = self.client.post("/nutrition/fdc/confirmation", json=self._body(),
                                        headers=self.auth_headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "feature_disabled")

    def test_user_binding_and_unknown_fields_are_rejected_before_repository(self):
        stub = _ConfirmationStub()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_confirmation_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", stub):
            wrong_user = self.client.post("/nutrition/fdc/confirmation",
                                          json=self._body(user_id="user-b"), headers=self.auth_headers())
            extra = self.client.post("/nutrition/fdc/confirmation",
                                     json=self._body(snapshot={"forged": True}), headers=self.auth_headers())
        self.assertEqual(wrong_user.status_code, 403)
        self.assertEqual(extra.status_code, 400)
        self.assertEqual(stub.calls, [])

    def test_enabled_route_passes_only_envelope_and_keeps_new_revision_pending(self):
        stub = _ConfirmationStub()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_confirmation_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", stub):
            response = self.client.post("/nutrition/fdc/confirmation", json=self._body(),
                                        headers=self.auth_headers())
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["status"], "confirmed_pending_revision")
        self.assertTrue(payload["requires_new_scan_revision"])
        self.assertEqual(payload["issued_scan_revision"], 1)
        self.assertTrue(payload["requires_detail_replay"])
        self.assertFalse(payload["photo_confidence_changed"])
        self.assertEqual(len(stub.calls), 1)
        self.assertNotIn("snapshot", stub.calls[0])
        self.assertEqual(stub.calls[0]["authenticated_user_id"], "user-a")

    def test_repository_error_maps_to_stable_http_error(self):
        class ErrorStub:
            def record_confirmation(self, **kwargs):
                raise FdcCandidateConfirmationRepositoryError("snapshot_mismatch", "private detail")

        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_confirmation_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", ErrorStub()):
            response = self.client.post("/nutrition/fdc/confirmation", json=self._body(),
                                        headers=self.auth_headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "snapshot_mismatch")


if __name__ == "__main__":
    unittest.main()
