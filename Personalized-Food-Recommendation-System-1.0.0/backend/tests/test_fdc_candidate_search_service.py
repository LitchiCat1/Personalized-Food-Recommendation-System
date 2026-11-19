from copy import deepcopy
import unittest
from unittest.mock import Mock

from services.fdc_candidate_search_service import (
    FdcCandidateSearchError,
    FdcCandidateSearchService,
    MAX_SEARCH_CANDIDATES_PER_ITEM,
    MAX_SEARCH_ITEMS,
    MAX_SEARCH_REQUESTS,
    SEARCH_DEADLINE_SECONDS,
    SEARCH_PAGE_SIZE,
)
from services.fooddata_central_client import FoodDataCentralClientError


def _item(index, **changes):
    item = {
        "item_id": f"scan-1:{index}", "item_revision": 0,
        "name_zh": "糯米腸", "confidence": 0.92, "weight_confidence": 0.8,
        "estimated_weight_g": 120, "food_state": "prepared",
        "preparation_method": "steamed", "components_scope": "food_only",
        "brand": None, "variant": None, "validation_issues": [],
    }
    item.update(changes)
    return item


class _ScanRepository:
    def __init__(self, items):
        self.context = {"items": items, "expires_at": 1200.0}
        self.calls = []

    def get_scan_context(self, **kwargs):
        self.calls.append(kwargs)
        return self.context


class _SnapshotRepository:
    def __init__(self):
        self.document = None
        self.get_calls = []
        self.save_calls = []

    def get_snapshot(self, **kwargs):
        self.get_calls.append(kwargs)
        return self.document

    def save_candidates(self, **kwargs):
        self.save_calls.append(kwargs)
        snapshot = {"items": [
            {"item_id": item_id, "candidates": candidates}
            for item_id, candidates in kwargs["candidates_by_item"].items()
        ]}
        self.document = {
            "scan_id": kwargs["scan_id"], "scan_revision": kwargs["scan_revision"],
            "snapshot_digest": "a" * 64, "snapshot": snapshot, "status": "active",
        }
        return self.document


class _FdcClient:
    def __init__(self, *, candidates=None, error=None):
        self.candidates = candidates or []
        self.error = error
        self.calls = []
        self.closed = False

    def search_foods(self, query, *, deadline, page_size):
        self.calls.append({"query": query, "deadline": deadline, "page_size": page_size})
        if self.error:
            raise self.error
        return {"candidates": list(self.candidates)}

    def close(self):
        self.closed = True


class FdcCandidateSearchServiceTests(unittest.TestCase):
    def setUp(self):
        self.items = [_item(0)]
        self.scan = _ScanRepository(self.items)
        self.snapshots = _SnapshotRepository()
        self.lookup_calls = []
        self.client = _FdcClient(candidates=[{
            "fdcId": "12345", "description": "Glutinous rice sausage",
            "dataType": "Foundation", "brandOwner": None,
            "foodCategory": "Prepared foods",
        }])
        self.factory_calls = []

        def lookup_factory(user_id):
            self.factory_calls.append(user_id)

            def lookup(item):
                self.lookup_calls.append(item["item_id"])
                return {"status": "no_local_mapping"}
            return lookup

        self.service = FdcCandidateSearchService(
            scan_context_repository=self.scan,
            snapshot_repository=self.snapshots,
            local_lookup_factory=lookup_factory,
            client_factory=lambda: self.client,
            official_health={"TFDA": {"status": "available"},
                             "USDA FNDDS": {"status": "available"}},
            clock=lambda: 100.0,
        )

    def _create(self):
        return self.service.create_snapshot(
            authenticated_user_id="user-a", scan_id="scan-1", scan_revision=0)

    def test_true_local_miss_uses_server_name_plan_and_bounded_provider_args(self):
        result = self._create()

        self.assertEqual(self.factory_calls, ["user-a"])
        self.assertEqual(self.lookup_calls, ["scan-1:0"])
        self.assertEqual(self.scan.calls[0]["user_id"], "user-a")
        self.assertEqual(self.scan.calls[0]["scan_id"], "scan-1")
        self.assertEqual(self.scan.calls[0]["scan_revision"], 0)
        self.assertEqual([call["query"] for call in self.client.calls], [
            "糯米腸", "glutinous rice sausage", "Taiwanese glutinous rice sausage",
        ])
        self.assertTrue(all(call["deadline"] == 100 + SEARCH_DEADLINE_SECONDS
                            and call["page_size"] == SEARCH_PAGE_SIZE
                            for call in self.client.calls))
        self.assertTrue(self.client.closed)
        self.assertEqual(result["snapshot"]["items"][0]["candidates"][0]["fdcId"], "12345")
        self.assertEqual(len(self.snapshots.save_calls), 1)

    def test_local_matches_conflicts_incomplete_and_incompatible_never_search(self):
        statuses = ["matched", "source_conflict", "incomplete_profile", "incompatible"]
        self.scan.context["items"] = [_item(index, name_zh=f"食物{index}")
                                       for index in range(len(statuses))]

        def lookup_factory(user_id):
            self.factory_calls.append(user_id)
            def lookup(item):
                return {"status": statuses[int(item["item_id"].rsplit(":", 1)[1])]}
            return lookup

        self.service.local_lookup_factory = lookup_factory
        result = self._create()

        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.factory_calls, ["user-a"])
        self.assertEqual(len(result["snapshot"]["items"]), len(statuses))
        self.assertEqual(result["snapshot"]["items"][0]["candidates"], [])
        self.assertEqual(len(self.snapshots.save_calls), 1)
        self.assertNotIn("no_hit_item_ids", self.snapshots.save_calls[0])

    def test_every_query_must_confirm_zero_hits(self):
        zero = {"candidates": [], "confirmed_no_hits": True}
        for responses, expected in (
            ([zero, zero, zero], ["scan-1:0"]),
            ([zero, {"candidates": []}, zero], None),
            ([zero, zero, {"candidates": self.client.candidates}], None),
        ):
            with self.subTest(responses=responses):
                self.service.snapshot_repository = snapshots = _SnapshotRepository()
                self.client.search_foods = Mock(side_effect=responses)
                self._create()
                self.assertEqual(self.client.search_foods.call_count, 3)
                self.assertEqual(snapshots.save_calls[0].get("no_hit_item_ids"), expected)

    def test_low_confidence_and_validation_issues_do_not_enter_local_or_remote_search(self):
        self.scan.context["items"] = [
            _item(0, confidence=0.2),
            _item(1, validation_issues=["missing_state"]),
        ]
        result = self._create()

        self.assertEqual(self.lookup_calls, [])
        self.assertEqual(self.client.calls, [])
        self.assertEqual([item["candidates"] for item in result["snapshot"]["items"]], [[], []])

    def test_user_confirmed_specific_name_reruns_local_lookup_before_search(self):
        self.scan.context["items"] = [_item(
            0, name_zh="青江菜", confidence=0.42, identity_confirmation_required=False,
            identity_confirmation_source="user", identity_confirmation_id="server-confirmation",
        )]
        looked_up = []
        self.service.local_lookup_factory = lambda _user_id: lambda item: (
            looked_up.append(item["item_id"]) or {"status": "matched"})
        self.service.client_factory = lambda: self.fail("local hit must not create FDC client")

        result = self._create()

        self.assertEqual(looked_up, ["scan-1:0"])
        self.assertEqual(result["snapshot"]["items"][0]["candidates"], [])
        self.assertEqual(len(self.snapshots.save_calls), 1)

    def test_user_confirmed_bok_choy_local_miss_searches_only_bounded_alias_queries(self):
        self.scan.context["items"] = [_item(
            0, name_zh="青江菜", confidence=0.42, identity_confirmation_required=False,
            identity_confirmation_source="user", identity_confirmation_id="server-confirmation",
            brand=None,
        )]
        self.client.candidates = [{
            "fdcId": "2685572", "description": "Cabbage, bok choy, raw",
            "dataType": "Foundation", "brandOwner": None, "foodCategory": "Vegetables",
        }]
        looked_up = []
        self.service.local_lookup_factory = lambda _user_id: lambda item: (
            looked_up.append(item["item_id"]) or {"status": "no_local_mapping"})

        result = self._create()

        self.assertEqual(looked_up, ["scan-1:0"])
        self.assertEqual([call["query"] for call in self.client.calls], ["青江菜", "bok choy"])
        self.assertEqual(result["snapshot"]["items"][0]["candidates"], self.client.candidates)
        self.assertTrue(self.client.closed)

    def test_search_budget_overflow_fails_before_constructing_client(self):
        self.scan.context["items"] = [_item(index, name_zh=f"食物{index}")
                                       for index in range(MAX_SEARCH_ITEMS + 1)]
        client_factory_calls = []
        self.service.client_factory = lambda: client_factory_calls.append(True)

        with self.assertRaises(FdcCandidateSearchError) as error:
            self._create()

        self.assertEqual(error.exception.code, "search_budget_exceeded")
        self.assertEqual(client_factory_calls, [])
        self.assertEqual(self.snapshots.save_calls, [])

    def test_generic_items_never_construct_provider_or_enter_local_search(self):
        self.scan.context["items"] = [
            _item(index, name_zh=name, confidence=confidence)
            for index, (name, confidence) in enumerate((
                ("炒菜葉", 0.95), ("葉菜", 0.95), ("清炒綠色葉菜", 0.95), ("炒菜葉", 0.4)))
        ]
        original = deepcopy(self.scan.context["items"])
        self.service.client_factory = lambda: self.fail("provider factory called")
        result = self._create()
        self.assertFalse(self.lookup_calls or self.client.calls)
        self.assertEqual(self.scan.context["items"], original)
        self.assertEqual([row["candidates"] for row in result["snapshot"]["items"]], [[], [], [], []])

    def test_duplicate_generic_items_and_specific_control_keep_independent_ids(self):
        self.scan.context["items"] = [
            _item(0, name_zh="炒菜葉", estimated_weight_g=40),
            _item(1, name_zh="炒菜葉", estimated_weight_g=70),
            _item(2, name_zh="青江菜", estimated_weight_g=90),
        ]
        original = deepcopy(self.scan.context["items"])
        result = self._create()
        self.assertEqual(self.lookup_calls, ["scan-1:2"])
        self.assertEqual([call["query"] for call in self.client.calls], ["青江菜", "bok choy"])
        self.assertEqual(self.scan.context["items"], original)
        rows = result["snapshot"]["items"]
        self.assertEqual([row["item_id"] for row in rows], ["scan-1:0", "scan-1:1", "scan-1:2"])
        self.assertEqual([row["candidates"] for row in rows[:2]], [[], []])
        self.assertEqual(rows[2]["candidates"][0]["fdcId"], "12345")

    def test_specific_vegetable_names_reach_existing_search_without_renaming(self):
        names = ("大陸妹", "青江菜", "小白菜", "清炒青江菜")
        self.scan.context["items"] = [_item(index, name_zh=name) for index, name in enumerate(names)]
        self._create()
        expected = [query for name in names for query in
                    ([name, "bok choy"] if name == "青江菜" else [name])]
        self.assertEqual([call["query"] for call in self.client.calls], expected)

    def test_completed_snapshot_replay_skips_local_lookup_and_provider(self):
        first = self._create()
        lookup_count = len(self.lookup_calls)
        provider_count = len(self.client.calls)
        replay = self._create()

        self.assertEqual(replay, first)
        self.assertEqual(len(self.lookup_calls), lookup_count)
        self.assertEqual(len(self.client.calls), provider_count)
        self.assertEqual(len(self.snapshots.save_calls), 1)

    def test_candidate_list_and_total_request_limits_are_enforced(self):
        self.scan.context["items"] = [_item(index) for index in range(MAX_SEARCH_ITEMS)]
        many_candidates = [{
            "fdcId": str(10000 + index), "description": f"Food {index}",
            "dataType": "Foundation", "brandOwner": None, "foodCategory": None,
        } for index in range(MAX_SEARCH_CANDIDATES_PER_ITEM + 2)]
        self.client.candidates = many_candidates

        result = self._create()

        self.assertEqual(len(self.client.calls), MAX_SEARCH_REQUESTS)
        self.assertEqual(len(result["snapshot"]["items"][0]["candidates"]), MAX_SEARCH_CANDIDATES_PER_ITEM)
        self.assertTrue(all(call["deadline"] == 100 + SEARCH_DEADLINE_SECONDS
                            for call in self.client.calls))

    def test_provider_errors_are_wrapped_without_changing_stable_code(self):
        self.client.error = FoodDataCentralClientError("rate_limited", "USDA search is rate limited")

        with self.assertRaises(FdcCandidateSearchError) as error:
            self._create()

        self.assertEqual(error.exception.code, "rate_limited")
        self.assertNotIn("api_key", str(error.exception).lower())
        self.assertEqual(self.snapshots.save_calls, [])
        self.assertTrue(self.client.closed)


if __name__ == "__main__":
    unittest.main()
