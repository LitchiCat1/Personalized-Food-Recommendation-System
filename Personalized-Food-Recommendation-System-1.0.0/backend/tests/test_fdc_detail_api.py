import unittest
from unittest.mock import patch

from repositories.fdc_candidate_confirmation_repository import FdcCandidateConfirmationRepositoryError
from services.fooddata_central_client import FoodDataCentralClientError
from test_api_routes import ApiTestBase


class _ConfirmationStub:
    def __init__(self, confirmed=True):
        self.confirmed = confirmed
        self.calls = []

    def get_confirmation(self, **kwargs):
        self.calls.append(kwargs)
        if not self.confirmed:
            return None
        return {
            "confirmation_id": kwargs["confirmation_id"],
            "scan_id": kwargs["scan_id"],
            "issued_scan_revision": kwargs["issued_scan_revision"],
            "confirmed_items": [{
                "item_id": "scan-1:0", "confirmed_fdc_id": "12345",
            }],
        }


class _DetailClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or {"url": "https://api.nal.usda.gov/fdc/v1/food/12345",
                                 "payload": {"fdcId": 12345}}
        self.error = error
        self.closed = False

    def get_food(self, fdc_id, *, deadline):
        self.calls.append((fdc_id, deadline))
        if self.error:
            raise self.error
        return self.result

    def close(self):
        self.closed = True


class FdcDetailApiTests(ApiTestBase):
    def _body(self, **changes):
        body = {
            "confirmation_id": "confirmation-1",
            "scan_id": "scan-1",
            "issued_scan_revision": 1,
            "item_id": "scan-1:0",
        }
        body.update(changes)
        return body

    def test_requires_authentication_before_feature_gate(self):
        response = self.client.post("/nutrition/fdc/detail", json=self._body())
        self.assertEqual(response.status_code, 401)

    def test_default_feature_off_does_not_read_confirmation_or_provider(self):
        stub = _ConfirmationStub()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_candidate_confirmation_repository", stub):
            response = self.client.post("/nutrition/fdc/detail", json=self._body(), headers=self.auth_headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "feature_disabled")
        self.assertEqual(stub.calls, [])

    def test_enabled_route_uses_server_confirmed_id_and_never_client_id(self):
        confirmation = _ConfirmationStub()
        client = _DetailClient()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_detail_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", confirmation), \
                patch.object(self.app_module, "_build_fdc_detail_client", return_value=client):
            forged = self.client.post("/nutrition/fdc/detail",
                                      json=self._body(fdc_id="99999"), headers=self.auth_headers())
            response = self.client.post("/nutrition/fdc/detail",
                                        json=self._body(), headers=self.auth_headers())
        self.assertEqual(forged.status_code, 400)
        self.assertEqual(forged.get_json()["error"]["code"], "invalid_request")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.calls[0][0], "12345")
        self.assertNotIn("fdc_id", confirmation.calls[0])
        payload = response.get_json()
        self.assertEqual(payload["fdc_id"], "12345")
        self.assertFalse(payload["photo_confidence_changed"])
        self.assertFalse(payload["profile_written"])
        self.assertTrue(client.closed)

    def test_missing_confirmation_and_revision_mismatch_fail_closed(self):
        missing = _ConfirmationStub(confirmed=False)
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_detail_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", missing):
            response = self.client.post("/nutrition/fdc/detail", json=self._body(), headers=self.auth_headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "detail_not_found")

        class ErrorStub(_ConfirmationStub):
            def get_confirmation(self, **kwargs):
                raise FdcCandidateConfirmationRepositoryError("revision_conflict", "private")

        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_detail_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", ErrorStub()):
            response = self.client.post("/nutrition/fdc/detail", json=self._body(), headers=self.auth_headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "revision_conflict")

    def test_unconfirmed_item_never_calls_provider(self):
        confirmation = _ConfirmationStub()
        confirmation.get_confirmation = lambda **kwargs: {
            "confirmation_id": "confirmation-1", "scan_id": "scan-1", "issued_scan_revision": 1,
            "confirmed_items": [],
        }
        client = _DetailClient()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_detail_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", confirmation), \
                patch.object(self.app_module, "_build_fdc_detail_client", return_value=client):
            response = self.client.post("/nutrition/fdc/detail", json=self._body(), headers=self.auth_headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "confirmation_required")
        self.assertEqual(client.calls, [])

    def test_provider_id_mismatch_is_sanitized(self):
        confirmation = _ConfirmationStub()
        client = _DetailClient(error=FoodDataCentralClientError("response_mismatch", "private"))
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_detail_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_confirmation_repository", confirmation), \
                patch.object(self.app_module, "_build_fdc_detail_client", return_value=client):
            response = self.client.post("/nutrition/fdc/detail", json=self._body(), headers=self.auth_headers())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "detail_invalid")


if __name__ == "__main__":
    unittest.main()
