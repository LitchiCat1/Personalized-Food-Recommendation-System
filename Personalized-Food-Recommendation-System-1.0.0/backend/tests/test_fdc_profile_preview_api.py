import unittest
from unittest.mock import patch

from repositories.fdc_profile_preview_repository import FdcProfilePreviewRepositoryError
from services.fdc_profile_preview_service import FdcProfilePreviewError
from test_api_routes import ApiTestBase


class _PreviewServiceStub:
    def __init__(self):
        self.calls = []

    def preview(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "preview", **kwargs, "preview": {
            "nutrition_profile": {"profile_hash": "a" * 64},
            "portion": {"weight_g": 150},
            "source_block": {"content_hash": "b" * 64},
            "recognition_identity": {"name_zh": "蘋果"},
            "source_identity": {"name_zh": "蘋果"},
        }}


class _PreviewRepositoryStub:
    def __init__(self):
        self.save_calls = []
        self.accept_calls = []

    def save_preview(self, preview, **kwargs):
        self.save_calls.append((preview, kwargs))
        return {
            "preview_id": "server-preview-1", "confirmation_id": preview["confirmation_id"],
            "scan_id": preview["scan_id"], "issued_scan_revision": preview["issued_scan_revision"],
            "item_id": preview["item_id"], "item_revision": 0, "snapshot_digest": "c" * 64,
            "source_id": "usda-fdc-12345", "source_policy_revision": 0, "fdc_id": "12345",
            "weight_g": 150,
            "profile": preview["preview"]["nutrition_profile"],
            "portion": preview["preview"]["portion"],
            "source_block": preview["preview"]["source_block"],
            "recognition_identity": preview["preview"]["recognition_identity"],
            "food_identity": preview["preview"]["source_identity"],
        }

    def accept_preview(self, **kwargs):
        self.accept_calls.append(kwargs)
        return {
            "status": "accepted", "preview_id": kwargs["preview_id"],
            "profile": {"profile_id": "profile-1", "profile_hash": "a" * 64},
            "portion": {"weight_g": 150}, "profile_hash": "a" * 64, "replayed": False,
        }


class FdcProfilePreviewApiTests(ApiTestBase):
    def _preview_body(self, **changes):
        body = {
            "confirmation_id": "confirmation-1", "scan_id": "scan-1",
            "issued_scan_revision": 1, "item_id": "scan-1:0",
        }
        body.update(changes)
        return body

    def test_preview_requires_authentication_before_feature_gate(self):
        response = self.client.post("/nutrition/fdc/profile-preview", json=self._preview_body())
        self.assertEqual(response.status_code, 401)

    def test_preview_default_feature_off_does_not_read_service_or_repository(self):
        service, repository = _PreviewServiceStub(), _PreviewRepositoryStub()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_profile_preview_service", service), \
                patch.object(self.app_module, "fdc_profile_preview_repository", repository):
            response = self.client.post("/nutrition/fdc/profile-preview", json=self._preview_body(),
                                        headers=self.auth_headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "feature_disabled")
        self.assertEqual(service.calls, [])
        self.assertEqual(repository.save_calls, [])

    def test_preview_enabled_uses_only_server_references_and_server_id(self):
        service, repository = _PreviewServiceStub(), _PreviewRepositoryStub()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_profile_preview_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_preview_service", service), \
                patch.object(self.app_module, "fdc_profile_preview_repository", repository):
            forged = self.client.post("/nutrition/fdc/profile-preview",
                                      json=self._preview_body(fdc_id="99999"), headers=self.auth_headers())
            response = self.client.post("/nutrition/fdc/profile-preview", json=self._preview_body(),
                                        headers=self.auth_headers())
        self.assertEqual(forged.status_code, 400)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.calls[0]["authenticated_user_id"], "user-a")
        self.assertNotIn("fdc_id", service.calls[0])
        self.assertEqual(repository.save_calls[0][1], {})
        self.assertEqual(response.get_json()["preview_id"], "server-preview-1")
        self.assertFalse(response.get_json()["profile_written"])

    def test_preview_errors_are_typed_and_provider_details_are_not_exposed(self):
        service = _PreviewServiceStub()
        service.preview = lambda **kwargs: (_ for _ in ()).throw(
            FdcProfilePreviewError("source_conflict", "private detail"))
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_profile_preview_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_preview_service", service), \
                patch.object(self.app_module, "fdc_profile_preview_repository", _PreviewRepositoryStub()):
            response = self.client.post("/nutrition/fdc/profile-preview", json=self._preview_body(),
                                        headers=self.auth_headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "source_conflict")

    def test_accept_requires_authentication_and_is_disabled_by_default(self):
        body = {"preview_id": "server-preview-1", "idempotency_key": "accept-1"}
        self.assertEqual(self.client.post("/nutrition/fdc/profile-accept", json=body).status_code, 401)
        with self.mock_auth("user-a"):
            response = self.client.post("/nutrition/fdc/profile-accept", json=body,
                                        headers=self.auth_headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "feature_disabled")

    def test_accept_enabled_does_not_accept_client_profile_or_fdc_data(self):
        repository = _PreviewRepositoryStub()
        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_profile_accept_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_preview_repository", repository):
            forged = self.client.post("/nutrition/fdc/profile-accept", json={
                "preview_id": "server-preview-1", "idempotency_key": "accept-1",
                "profile": {"calories": 1}, "fdc_id": "99999"}, headers=self.auth_headers())
            response = self.client.post("/nutrition/fdc/profile-accept", json={
                "preview_id": "server-preview-1", "idempotency_key": "accept-1"},
                headers=self.auth_headers())
        self.assertEqual(forged.status_code, 400)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(repository.accept_calls[0], {
            "authenticated_user_id": "user-a", "preview_id": "server-preview-1",
            "idempotency_key": "accept-1"})
        self.assertTrue(response.get_json()["profile_written"])

    def test_accept_repository_error_maps_without_private_details(self):
        class ErrorRepository:
            def accept_preview(self, **kwargs):
                raise FdcProfilePreviewRepositoryError("revision_conflict", "private detail")

        with self.mock_auth("user-a"), patch.object(self.app_module, "fdc_profile_accept_route_enabled", True), \
                patch.object(self.app_module, "fdc_profile_preview_repository", ErrorRepository()):
            response = self.client.post("/nutrition/fdc/profile-accept", json={
                "preview_id": "server-preview-1", "idempotency_key": "accept-1"},
                headers=self.auth_headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "revision_conflict")


if __name__ == "__main__":
    unittest.main()
