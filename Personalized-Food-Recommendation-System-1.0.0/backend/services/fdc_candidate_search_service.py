"""Create immutable FDC candidate snapshots from authenticated scan context."""

import math
import secrets
import threading
import time
from contextlib import contextmanager, nullcontext

from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepositoryError
from repositories.scan_context_repository import ScanContextRepositoryError
from services.food_identity_service import requires_food_identity_confirmation, web_identity_ready
from services.food_query_normalization_service import (
    FoodQueryNormalizationError,
    build_fdc_search_query_plan,
)
from services.fooddata_central_client import FoodDataCentralClientError
from services.fooddata_central_selection_service import FdcCandidateSelectionError
from services.vision_food_service import VISION_FOOD_MIN_CONFIDENCE


MAX_SEARCH_ITEMS = 4
MAX_SEARCH_REQUESTS = 12
MAX_SEARCH_CANDIDATES_PER_ITEM = 10
SEARCH_DEADLINE_SECONDS = 25
SEARCH_PAGE_SIZE = 5
SEARCH_RESERVATION_LEASE_SECONDS = 60
SEARCH_RESERVATION_WAIT_SECONDS = 30
SEARCH_RESERVATION_POLL_SECONDS = 0.05


class FdcCandidateSearchError(ValueError):
    """Sanitized, stable candidate-search error for the HTTP boundary."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FdcCandidateSearchError(code, message)


def _eligible_for_search(item):
    if item.get("identity_confirmation_source") is not None or "identity_confirmation_id" in item:
        return web_identity_ready(item, minimum_confidence=VISION_FOOD_MIN_CONFIDENCE)
    confidence = item.get("confidence")
    return (not isinstance(confidence, bool) and isinstance(confidence, (int, float))
            and math.isfinite(confidence) and confidence >= VISION_FOOD_MIN_CONFIDENCE
            and not item.get("validation_issues")
            and not requires_food_identity_confirmation(item.get("name_zh")))


class FdcCandidateSearchService:
    """Search only true local misses, persisting one snapshot per scan revision."""

    _locks_guard = threading.Lock()
    _scan_locks = {}

    def __init__(self, *, scan_context_repository, snapshot_repository,
                 local_lookup_factory, client_factory, official_health,
                 clock=time.monotonic,
                 reservation_lease_seconds=SEARCH_RESERVATION_LEASE_SECONDS,
                 reservation_wait_seconds=SEARCH_RESERVATION_WAIT_SECONDS,
                 reservation_poll_seconds=SEARCH_RESERVATION_POLL_SECONDS):
        for value in (reservation_lease_seconds, reservation_wait_seconds,
                      reservation_poll_seconds):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError("FDC search reservation timings must be positive finite numbers")
        self.scan_context_repository = scan_context_repository
        self.snapshot_repository = snapshot_repository
        self.local_lookup_factory = local_lookup_factory
        self.client_factory = client_factory
        self.official_health = official_health
        self.clock = clock
        self.reservation_lease_seconds = reservation_lease_seconds
        self.reservation_wait_seconds = reservation_wait_seconds
        self.reservation_poll_seconds = reservation_poll_seconds

    @classmethod
    @contextmanager
    def _serialized_scan(cls, scan_id, scan_revision):
        key = (scan_id, scan_revision)
        with cls._locks_guard:
            entry = cls._scan_locks.get(key)
            if entry is None:
                entry = [threading.Lock(), 0]
                cls._scan_locks[key] = entry
            entry[1] += 1
        lock = entry[0]
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with cls._locks_guard:
                entry[1] -= 1
                if entry[1] == 0:
                    cls._scan_locks.pop(key, None)

    def _existing_snapshot(self, *, user_id, scan_id, scan_revision):
        try:
            document = self.snapshot_repository.get_snapshot(
                user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                include_inactive=True)
        except FdcCandidateSnapshotRepositoryError as error:
            raise FdcCandidateSearchError(error.code, str(error)) from error
        if document is not None and document.get("status") != "active":
            _fail("snapshot_unavailable", "FDC candidate snapshot is no longer active")
        return document

    def create_snapshot(self, *, authenticated_user_id, scan_id, scan_revision):
        """Return the immutable snapshot, replaying it without another provider call."""
        durable = getattr(self.snapshot_repository, "durable", False)
        serializer = nullcontext() if durable else self._serialized_scan(scan_id, scan_revision)
        with serializer:
            existing = self._existing_snapshot(
                user_id=authenticated_user_id, scan_id=scan_id,
                scan_revision=scan_revision)
            if existing is not None:
                return existing

            reserve_search = getattr(self.snapshot_repository, "reserve_search", None)
            if not durable or not callable(reserve_search):
                return self._create_snapshot(
                    authenticated_user_id=authenticated_user_id, scan_id=scan_id,
                    scan_revision=scan_revision)

            lease_owner = secrets.token_urlsafe(24)
            wait_deadline = time.monotonic() + self.reservation_wait_seconds
            reservation = reserve_search(
                user_id=authenticated_user_id, scan_id=scan_id,
                scan_revision=scan_revision, lease_owner=lease_owner,
                lease_seconds=self.reservation_lease_seconds,
            )
            if not reservation["owner"]:
                observed_owner = reservation["lease_owner"]
                while True:
                    existing = self._existing_snapshot(
                        user_id=authenticated_user_id, scan_id=scan_id,
                        scan_revision=scan_revision)
                    if existing is not None:
                        return existing
                    current = self.snapshot_repository.get_search_reservation(
                        user_id=authenticated_user_id, scan_id=scan_id,
                        scan_revision=scan_revision)
                    if current is None:
                        reservation = reserve_search(
                            user_id=authenticated_user_id, scan_id=scan_id,
                            scan_revision=scan_revision, lease_owner=lease_owner,
                            lease_seconds=self.reservation_lease_seconds,
                        )
                        if reservation["owner"]:
                            break
                        observed_owner = reservation["lease_owner"]
                    elif current["status"] == "failed":
                        if current["lease_owner"] == observed_owner:
                            _fail(current.get("error_code") or "upstream_error",
                                  "The concurrent FDC candidate search failed")
                        observed_owner = current["lease_owner"]
                    else:
                        if current["lease_owner"] != observed_owner:
                            observed_owner = current["lease_owner"]
                        if not current["lease_active"]:
                            reservation = reserve_search(
                                user_id=authenticated_user_id, scan_id=scan_id,
                                scan_revision=scan_revision, lease_owner=lease_owner,
                                lease_seconds=self.reservation_lease_seconds,
                            )
                            if reservation["owner"]:
                                break
                            observed_owner = reservation["lease_owner"]
                    remaining = wait_deadline - time.monotonic()
                    if remaining <= 0:
                        _fail("single_flight_timeout", "Another FDC search is still in progress")
                    time.sleep(min(self.reservation_poll_seconds, remaining))

            existing = self._existing_snapshot(
                user_id=authenticated_user_id, scan_id=scan_id,
                scan_revision=scan_revision)
            if existing is not None:
                self.snapshot_repository.release_search(
                    user_id=authenticated_user_id, scan_id=scan_id,
                    scan_revision=scan_revision, lease_owner=lease_owner,
                )
                return existing
            try:
                return self._create_snapshot(
                    authenticated_user_id=authenticated_user_id, scan_id=scan_id,
                    scan_revision=scan_revision, reservation_owner=lease_owner)
            except Exception as error:
                error_code = getattr(error, "code", "upstream_error")
                self.snapshot_repository.fail_search(
                    user_id=authenticated_user_id, scan_id=scan_id,
                    scan_revision=scan_revision, lease_owner=lease_owner,
                    error_code=error_code,
                )
                raise

    def _create_snapshot(self, *, authenticated_user_id, scan_id, scan_revision,
                         reservation_owner=None):
        try:
            context = self.scan_context_repository.get_scan_context(
                user_id=authenticated_user_id, scan_id=scan_id,
                scan_revision=scan_revision, include_inactive=False)
        except ScanContextRepositoryError as error:
            raise FdcCandidateSearchError(error.code, str(error)) from error
        if context is None:
            _fail("scan_unavailable", "The server-owned scan context is unavailable")

        if any(not isinstance(self.official_health.get(source), dict)
               or self.official_health[source].get("status") != "available"
               for source in ("TFDA", "USDA FNDDS")):
            _fail("local_unavailable", "Official nutrition databases are not available")

        items = context["items"]
        candidates_by_item = {item["item_id"]: [] for item in items}
        no_hit_item_ids = []
        try:
            local_lookup = self.local_lookup_factory(authenticated_user_id)
        except Exception as error:
            raise FdcCandidateSearchError(
                "local_lookup_unavailable", "Local nutrition lookup is unavailable") from error
        search_items = []
        for item in items:
            if not _eligible_for_search(item):
                continue
            try:
                local = local_lookup(item)
            except Exception as error:
                raise FdcCandidateSearchError(
                    getattr(error, "code", "local_lookup_unavailable"),
                    "Local nutrition lookup could not complete") from error
            if not isinstance(local, dict) or local.get("status") not in {
                    "matched", "source_conflict", "incomplete_profile", "incompatible", "no_local_mapping"}:
                _fail("invalid_local_result", "Local nutrition lookup returned an invalid result")
            if local["status"] == "no_local_mapping":
                search_items.append(item)

        if len(search_items) > MAX_SEARCH_ITEMS:
            _fail("search_budget_exceeded", "Too many unmatched scan items for one FDC search")

        if search_items:
            try:
                client = self.client_factory()
            except Exception as error:
                raise FdcCandidateSearchError("provider_unavailable", "FDC search is not configured") from error
            deadline = self.clock() + SEARCH_DEADLINE_SECONDS
            calls = 0
            try:
                for item in search_items:
                    plan = build_fdc_search_query_plan(item, scan_revision=scan_revision)
                    by_id = {}
                    confirmed_no_hits = bool(plan["queries"])
                    for query in plan["queries"]:
                        if calls >= MAX_SEARCH_REQUESTS:
                            _fail("search_budget_exceeded", "FDC search request budget was exceeded")
                        calls += 1
                        result = client.search_foods(
                            query, deadline=deadline, page_size=SEARCH_PAGE_SIZE)
                        confirmed_no_hits = confirmed_no_hits and result.get("confirmed_no_hits") is True
                        for candidate in result["candidates"]:
                            prior = by_id.get(candidate["fdcId"])
                            if prior is not None and prior != candidate:
                                _fail("invalid_response", "FDC search returned conflicting candidate metadata")
                            by_id[candidate["fdcId"]] = candidate
                    candidates_by_item[item["item_id"]] = sorted(
                        by_id.values(), key=lambda candidate: candidate["fdcId"]
                    )[:MAX_SEARCH_CANDIDATES_PER_ITEM]
                    if confirmed_no_hits and not by_id:
                        no_hit_item_ids.append(item["item_id"])
            except (FoodQueryNormalizationError, FoodDataCentralClientError,
                    FdcCandidateSelectionError) as error:
                raise FdcCandidateSearchError(
                    getattr(error, "code", "upstream_error"), str(error)) from error
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

        try:
            save_arguments = dict(
                user_id=authenticated_user_id,
                scan_id=scan_id,
                scan_revision=scan_revision,
                candidates_by_item=candidates_by_item,
            )
            if no_hit_item_ids:
                save_arguments["no_hit_item_ids"] = no_hit_item_ids
            if reservation_owner is not None:
                save_arguments["reservation_owner"] = reservation_owner
            return self.snapshot_repository.save_candidates(**save_arguments)
        except FdcCandidateSnapshotRepositoryError as error:
            raise FdcCandidateSearchError(error.code, str(error)) from error

    def get_snapshot(self, *, authenticated_user_id, scan_id, scan_revision):
        try:
            document = self.snapshot_repository.get_snapshot(
                user_id=authenticated_user_id, scan_id=scan_id,
                scan_revision=scan_revision, include_inactive=False)
        except FdcCandidateSnapshotRepositoryError as error:
            raise FdcCandidateSearchError(error.code, str(error)) from error
        if document is None:
            _fail("snapshot_unavailable", "The server-owned FDC candidate snapshot is unavailable")
        return document


__all__ = ["FdcCandidateSearchError", "FdcCandidateSearchService"]
