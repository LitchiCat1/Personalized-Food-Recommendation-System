from copy import deepcopy
import unittest
from unittest.mock import patch

from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepositoryError
from test_api_routes import ApiTestBase


SNAPSHOT_DOCUMENT = {
    "scan_id": "scan-1",
    "scan_revision": 0,
    "snapshot_digest": "a" * 64,
    "expires_at": 1120.0,
    "snapshot": {
        "schema_version": "FdcCandidateSnapshotV1",
        "scan_revision": 0,
        "item_set_digest": "b" * 64,
        "snapshot_digest": "a" * 64,
        "items": [{
            "item_id": "scan-1:0",
            "item_revision": 0,
            "identity_digest": "c" * 64,
            "recognition_identity": {
                "name_zh": "糯米腸",
                "food_state": "prepared",
                "preparation_method": "steamed",
                "components_scope": "food_only",
                "brand": None,
                "variant": None,
            },
            "candidates": [{
                "fdcId": "12345",
                "description": "Glutinous rice sausage",
                "dataType": "Foundation",
                "brandOwner": None,
                "foodCategory": "Prepared foods",
            }],
        }],
    },
}


class _CandidateSearchServiceStub:
    def __init__(self, result=SNAPSHOT_DOCUMENT):
        self.result = deepcopy(result)
        self.create_calls = []
        self.get_calls = []

    def create_snapshot(self, **kwargs):
        self.create_calls.append(kwargs)
        return deepcopy(self.result)

    def get_snapshot(self, **kwargs):
        self.get_calls.append(kwargs)
        return deepcopy(self.result)


class FdcCandidatesApiTests(ApiTestBase):
    def _body(self, **changes):
        body = {"scan_id": "scan-1", "scan_revision": 0}
        body.update(changes)
        return body

    def _assert_reference_only(self, payload):
        document = payload.get("snapshot", payload)
        self.assertEqual(document["scan_id"], "scan-1")
        self.assertEqual(document["scan_revision"], 0)
        self.assertEqual(document["snapshot_digest"], "a" * 64)
        self.assertEqual(document["expires_at"], 1120.0)

        snapshot = document.get("snapshot", document)
        self.assertEqual(snapshot["items"][0]["item_id"], "scan-1:0")
        self.assertEqual(snapshot["items"][0]["item_revision"], 0)
        self.assertEqual(snapshot["items"][0]["recognition_identity"]["name_zh"], "糯米腸")
        self.assertEqual(snapshot["items"][0]["candidates"][0]["fdcId"], "12345")
        self.assertEqual(
            set(snapshot["items"][0]),
            {"item_id", "item_revision", "identity_digest", "recognition_identity", "candidates"},
        )

        forbidden = {
            "nutrition", "nutrition_profile", "nutrition_per_100g", "calories", "protein",
            "carbs", "fat", "sodium", "fiber", "sugar", "saturated_fat", "trans_fat",
        }

        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)

    def test_post_and_get_require_authentication_before_feature_gate(self):
        service = _CandidateSearchServiceStub()
        with patch.object(self.app_module, "fdc_candidate_route_enabled", True, create=True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service, create=True):
            post = self.client.post("/nutrition/fdc/candidates", json=self._body())
            get = self.client.get("/nutrition/fdc/candidates?scan_id=scan-1&scan_revision=0")

        self.assertEqual(post.status_code, 401)
        self.assertEqual(get.status_code, 401)
        self.assertEqual(service.create_calls, [])
        self.assertEqual(service.get_calls, [])


    def test_feature_off_rejects_before_service_access(self):
        service = _CandidateSearchServiceStub()
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", False, create=True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service, create=True):
            post = self.client.post(
                "/nutrition/fdc/candidates", json=self._body(), headers=self.auth_headers())
            get = self.client.get(
                "/nutrition/fdc/candidates?scan_id=scan-1&scan_revision=0",
                headers=self.auth_headers(),
            )

        for response in (post, get):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["error"]["code"], "feature_disabled")
        self.assertEqual(service.create_calls, [])
        self.assertEqual(service.get_calls, [])

    def test_post_passes_only_authenticated_owner_and_scan_references(self):
        service = _CandidateSearchServiceStub()
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", True, create=True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service, create=True):
            response = self.client.post(
                "/nutrition/fdc/candidates", json=self._body(), headers=self.auth_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.create_calls, [{
            "authenticated_user_id": "user-a", "scan_id": "scan-1", "scan_revision": 0,
        }])
        self.assertEqual(service.get_calls, [])
        self._assert_reference_only(response.get_json())

    def test_get_is_owner_bound_and_returns_reference_only_snapshot(self):
        service = _CandidateSearchServiceStub()
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", True, create=True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service, create=True):
            response = self.client.get(
                "/nutrition/fdc/candidates?scan_id=scan-1&scan_revision=0",
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.get_calls, [{
            "authenticated_user_id": "user-a", "scan_id": "scan-1", "scan_revision": 0,
        }])
        self.assertEqual(service.create_calls, [])
        self._assert_reference_only(response.get_json())

    def test_wrong_owner_is_forbidden_without_leaking_repository_details(self):
        class WrongOwnerService(_CandidateSearchServiceStub):
            def get_snapshot(self, **kwargs):
                self.get_calls.append(kwargs)
                raise FdcCandidateSnapshotRepositoryError("wrong_user", "private storage detail")

        service = WrongOwnerService()
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", True, create=True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service, create=True):
            response = self.client.get(
                "/nutrition/fdc/candidates?scan_id=scan-1&scan_revision=0",
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "wrong_user")
        self.assertNotIn("private storage detail", response.get_data(as_text=True))
        self.assertEqual(service.get_calls, [{
            "authenticated_user_id": "user-a", "scan_id": "scan-1", "scan_revision": 0,
        }])

    def test_client_supplied_items_candidates_or_fdc_ids_are_rejected(self):
        service = _CandidateSearchServiceStub()
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", True, create=True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service, create=True):
            responses = [
                self.client.post("/nutrition/fdc/candidates", json=self._body(items=[]),
                                 headers=self.auth_headers()),
                self.client.post("/nutrition/fdc/candidates", json=self._body(candidates=[]),
                                 headers=self.auth_headers()),
                self.client.post("/nutrition/fdc/candidates", json=self._body(fdc_id="99999"),
                                 headers=self.auth_headers()),
                self.client.post("/nutrition/fdc/candidates", json=self._body(candidate_fdc_id="99999"),
                                 headers=self.auth_headers()),
                self.client.get(
                    "/nutrition/fdc/candidates?scan_id=scan-1&scan_revision=0&fdc_id=99999",
                    headers=self.auth_headers(),
                ),
            ]

        self.assertTrue(all(response.status_code == 400 for response in responses),
                        [response.status_code for response in responses])
        self.assertEqual(service.create_calls, [])
        self.assertEqual(service.get_calls, [])


if __name__ == "__main__":
    unittest.main()
