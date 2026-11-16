import unittest
from unittest.mock import Mock, patch

from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_candidate_search_service import FdcCandidateSearchService
from test_api_routes import ApiTestBase


ITEM = {
    "item_id": "integration-scan:0", "item_revision": 0,
    "name_zh": "糯米腸", "confidence": 0.92,
    "weight_confidence": 0.8, "estimated_weight_g": 120,
    "food_state": "prepared", "preparation_method": "steamed",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [],
}


class _FakeFdcSearchClient:
    def __init__(self):
        self.calls = []
        self.closed = False

    def search_foods(self, query, *, deadline, page_size):
        self.calls.append({"query": query, "deadline": deadline, "page_size": page_size})
        return {"candidates": [{
            "fdcId": "12345",
            "description": "Glutinous rice sausage",
            "dataType": "Foundation",
            "brandOwner": None,
            "foodCategory": "Prepared foods",
        }]}

    def close(self):
        self.closed = True


class FdcCandidatesHttpIntegrationTests(ApiTestBase):
    def test_high_confidence_generic_items_persist_empty_snapshot_without_provider(self):
        sql = SqliteDatabase(":memory:")
        self.addCleanup(sql.close)
        scan = NutritionScanContextRepository(sql)
        snapshots = FdcCandidateSnapshotRepository(sql, scan_context_repository=scan)
        items = [dict(ITEM, item_id=f"integration-scan:{index}", name_zh="炒菜葉",
                      confidence=0.99, estimated_weight_g=weight)
                 for index, weight in enumerate((40, 70))]
        scan.save_scan_context(user_id="user-a", scan_id="integration-scan", scan_revision=0,
                               items=items, ttl_seconds=120)
        local_lookup = Mock(side_effect=AssertionError("generic items must not enter local search"))
        client_factory = Mock(side_effect=AssertionError("provider must not be constructed"))
        service = FdcCandidateSearchService(
            scan_context_repository=scan, snapshot_repository=snapshots,
            local_lookup_factory=lambda _user_id: local_lookup,
            client_factory=client_factory,
            official_health={source: {"status": "available"} for source in ("TFDA", "USDA FNDDS")},
        )
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service):
            first = self.client.post(
                "/nutrition/fdc/candidates", json={"scan_id": "integration-scan", "scan_revision": 0},
                headers=self.auth_headers())
            replay = self.client.post(
                "/nutrition/fdc/candidates", json={"scan_id": "integration-scan", "scan_revision": 0},
                headers=self.auth_headers())
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(replay.status_code, 200, replay.get_data(as_text=True))
        payload = first.get_json()
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(replay.get_json(), payload)
        snapshot_items = payload["snapshot"]["snapshot"]["items"]
        self.assertEqual([item["item_id"] for item in snapshot_items],
                         ["integration-scan:0", "integration-scan:1"])
        self.assertEqual([item["recognition_identity"]["name_zh"] for item in snapshot_items],
                         ["炒菜葉", "炒菜葉"])
        self.assertEqual([item["candidates"] for item in snapshot_items], [[], []])
        self.assertEqual(scan.get_scan_context(user_id="user-a", scan_id="integration-scan",
                                               scan_revision=0)["items"], items)
        persisted = snapshots.get_snapshot(user_id="user-a", scan_id="integration-scan", scan_revision=0)
        self.assertEqual(persisted["snapshot_digest"], payload["snapshot"]["snapshot_digest"])
        local_lookup.assert_not_called()
        client_factory.assert_not_called()

    def test_sqlite_backed_route_searches_once_persists_and_reads_same_reference(self):
        sql = SqliteDatabase(":memory:")
        self.addCleanup(sql.close)
        scan = NutritionScanContextRepository(sql)
        snapshots = FdcCandidateSnapshotRepository(sql, scan_context_repository=scan)
        scan.save_scan_context(
            user_id="user-a", scan_id="integration-scan", scan_revision=0,
            items=[ITEM], ttl_seconds=120,
        )

        client = _FakeFdcSearchClient()
        local_lookup_calls = []

        def local_lookup_factory(authenticated_user_id):
            self.assertEqual(authenticated_user_id, "user-a")

            def lookup(item):
                local_lookup_calls.append(item["item_id"])
                return {"status": "no_local_mapping"}

            return lookup

        service = FdcCandidateSearchService(
            scan_context_repository=scan,
            snapshot_repository=snapshots,
            local_lookup_factory=local_lookup_factory,
            client_factory=lambda: client,
            official_health={
                "TFDA": {"status": "available"},
                "USDA FNDDS": {"status": "available"},
            },
        )

        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_search_service", service):
            first = self.client.post(
                "/nutrition/fdc/candidates",
                json={"scan_id": "integration-scan", "scan_revision": 0},
                headers=self.auth_headers(),
            )
            self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
            first_payload = first.get_json()
            first_digest = first_payload["snapshot"]["snapshot_digest"]
            provider_call_count = len(client.calls)

            read = self.client.get(
                "/nutrition/fdc/candidates?scan_id=integration-scan&scan_revision=0",
                headers=self.auth_headers(),
            )
            self.assertEqual(read.status_code, 200, read.get_data(as_text=True))
            read_payload = read.get_json()

            replay = self.client.post(
                "/nutrition/fdc/candidates",
                json={"scan_id": "integration-scan", "scan_revision": 0},
                headers=self.auth_headers(),
            )
            self.assertEqual(replay.status_code, 200, replay.get_data(as_text=True))
            replay_payload = replay.get_json()

            with self.mock_auth("user-b"):
                wrong_owner = self.client.get(
                    "/nutrition/fdc/candidates?scan_id=integration-scan&scan_revision=0",
                    headers=self.auth_headers(),
                )

        persisted = snapshots.get_snapshot(
            user_id="user-a", scan_id="integration-scan", scan_revision=0)
        self.assertEqual(first_payload["status"], "available")
        self.assertEqual(read_payload, first_payload)
        self.assertEqual(replay_payload, first_payload)
        self.assertEqual(replay_payload["snapshot"]["snapshot_digest"], first_digest)
        self.assertEqual(len(client.calls), provider_call_count)
        self.assertEqual(len(local_lookup_calls), 1)
        self.assertTrue(client.closed)
        self.assertEqual(persisted["snapshot_digest"], first_digest)
        self.assertEqual(wrong_owner.status_code, 403)
        self.assertEqual(wrong_owner.get_json()["error"]["code"], "wrong_user")

        for key in ("nutrition", "nutrition_profile", "nutrition_per_100g", "calories",
                    "protein", "carbs", "fat", "sodium", "fiber", "sugar"):
            self.assertNotIn(key, first_payload)
            self.assertNotIn(key, first_payload["snapshot"])
        item = first_payload["snapshot"]["snapshot"]["items"][0]
        self.assertEqual(item["item_id"], ITEM["item_id"])
        self.assertEqual(item["candidates"][0]["fdcId"], "12345")


if __name__ == "__main__":
    unittest.main()
