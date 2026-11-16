"""Durable orchestration for the nutrition enrichment pipeline.

This module is deliberately independent of the HTTP layer.  It accepts only
server-owned scan items and profile references, validates their durable
authorities, then coordinates the request lease, quota reservation and one
provider call.  The provider result is persisted before quota finalisation so
that a crash cannot cause a second paid call on retry.
"""

from copy import deepcopy
import hashlib
import json
import math
import time

from repositories.nutrition_enrichment_repository import (
    NutritionEnrichmentRepositoryError,
)
from repositories.nutrition_quota_repository import (
    NutritionQuotaRepositoryError,
)
from services.nutrition_enrichment_guard_service import (
    build_enrichment_request_fingerprint,
)


RETRYABLE_STATUSES = frozenset({"timeout", "rate_limited", "upstream_error", "busy"})
TERMINAL_STATUSES = frozenset({
    "accepted", "partial", "complete", "success", "invalid_output", "source_conflict", "not_found",
})
ALL_STATUSES = RETRYABLE_STATUSES | TERMINAL_STATUSES
MAX_IDEMPOTENCY_KEY = 256
MAX_WAIT_SECONDS = 30.0


class NutritionEnrichmentCoordinatorError(ValueError):
    """Typed orchestration error; the HTTP route owns status-code mapping."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise NutritionEnrichmentCoordinatorError(code, message)


def _text(value, field, maximum=256):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _finite(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_request", f"{field} is invalid")
    return float(value)


def _profile_refs(profiles):
    if profiles is None:
        return []
    if not isinstance(profiles, (list, tuple)):
        _fail("invalid_request", "profiles must be an array")
    result = []
    for profile in profiles:
        if not isinstance(profile, dict):
            _fail("invalid_request", "profile references must be objects")
        required = {"profile_id", "profile_hash", "source_id", "profile_revision"}
        if set(profile) != required:
            _fail("invalid_request", "profile reference fields are invalid")
        digest = _text(profile["profile_hash"], "profile_hash", 64).lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            _fail("invalid_request", "profile_hash is invalid")
        revision = profile["profile_revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            _fail("invalid_request", "profile_revision is invalid")
        result.append({"profile_id": _text(profile["profile_id"], "profile_id"),
                       "profile_hash": digest,
                       "source_id": _text(profile["source_id"], "source_id"),
                       "profile_revision": revision})
    ids = [profile["profile_id"] for profile in result]
    if len(ids) != len(set(ids)):
        _fail("invalid_request", "profile IDs must be unique")
    return sorted(result, key=lambda profile: profile["profile_id"])


def _canonical_request(*, user_id, scan_id, scan_revision, items, profiles,
                       source_policy_id, source_policy_revision, request_kind):
    # The fingerprint helper performs the same field validation.  Keeping a
    # canonical payload beside it makes the durable request inspectable and
    # guarantees that the stored body is the one used for idempotency.
    normalized_items = sorted((deepcopy(item) for item in items), key=lambda item: item["item_id"])
    return {
        "request_kind": request_kind,
        "user_id": user_id,
        "scan_id": scan_id,
        "scan_revision": scan_revision,
        "items": normalized_items,
        "profiles": profiles,
        "source_policy": {"policy_id": source_policy_id, "policy_revision": source_policy_revision},
    }


def _error_document(error, code=None):
    return {"code": code or getattr(error, "code", "upstream_error"),
            "message": str(error)[:1024]}


def _valid_route_result(value, *, expected_item_ids=None):
    """Check the minimum persisted route contract before accepting a result.

    Provider output is untrusted even after the extraction model has returned
    JSON. The route layer normally rebuilds this envelope, while this second
    check protects direct coordinator users and prevents malformed complete
    results from being replayed as successful nutrition data.
    """
    if not isinstance(value, dict) or value.get("schema_version") != "NutritionEnrichmentRouteV1":
        return False
    items = value.get("items")
    coverage = value.get("nutrition_coverage")
    if not isinstance(items, list) or not items or not isinstance(coverage, dict):
        return False
    if coverage.get("schema_version") != "NutritionCoverageV1" or not isinstance(coverage.get("nutrients"), dict):
        return False
    ids = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str) or not item["item_id"]:
            return False
        ids.append(item["item_id"])
    if len(ids) != len(set(ids)):
        return False
    if expected_item_ids is not None and set(ids) != set(expected_item_ids):
        return False
    included = coverage.get("included_item_ids")
    if included is not None and (not isinstance(included, list) or set(included) != set(ids)):
        return False
    return True


def _status_from_result(result, *, expected_item_ids=None):
    """Normalise ``enrich_nutrition`` output into repository statuses."""
    if not isinstance(result, dict):
        return "invalid_output", None
    explicit = result.get("status")
    # A provider budget is a bounded terminal failure for this exact request;
    # it must not be persisted as an unknown repository status or retried in a
    # tight loop.  Keep the original code in the error envelope below.
    if explicit == "budget_exceeded":
        return "invalid_output", result
    if isinstance(explicit, str) and explicit in ALL_STATUSES:
        payload = result.get("result", result)
        if explicit in {"accepted", "partial", "complete", "success"}:
            if not _valid_route_result(payload, expected_item_ids=expected_item_ids):
                return "invalid_output", result
        return explicit, payload
    if not _valid_route_result(result, expected_item_ids=expected_item_ids):
        return "invalid_output", result
    items = result.get("items")
    if not isinstance(items, list) or not items:
        return "invalid_output", result
    statuses = [item.get("status") for item in items if isinstance(item, dict)]
    if len(statuses) != len(items):
        return "invalid_output", result
    if any(status in RETRYABLE_STATUSES for status in statuses):
        return next(status for status in statuses if status in RETRYABLE_STATUSES), result
    if all(status in {"not_found", "no_usable_source", "needs_source_review"} for status in statuses):
        return "not_found", result
    if any(status in {"source_conflict"} for status in statuses):
        return "source_conflict", result
    if any(status in {"invalid_output", "local_error", "numeric_range"} for status in statuses):
        return "invalid_output", result
    if all(status in {"accepted", "complete"} for status in statuses):
        return "complete", result
    if any(status in {"accepted", "partial", "complete"} for status in statuses):
        return "partial", result
    return "invalid_output", result


class NutritionEnrichmentCoordinator:
    """Coordinate one durable, idempotent enrichment request.

    ``provider`` is the already-authorized web/provider stage.  The route must
    perform TFDA/USDA local lookup first and only construct this coordinator
    when a paid third-layer call is actually needed; otherwise a local hit
    would unnecessarily consume a web quota reservation.
    """

    def __init__(self, *, scan_context_repository=None, profile_repository=None,
                 request_repository, quota_repository, provider, clock=time.time,
                 wait_timeout=0.0, authority_consumed=False):
        if request_repository is None or quota_repository is None or not callable(provider):
            _fail("invalid_configuration", "request, quota and provider dependencies are required")
        if not callable(clock):
            _fail("invalid_configuration", "clock must be callable")
        wait_timeout = _finite(wait_timeout, "wait_timeout")
        if wait_timeout < 0 or wait_timeout > MAX_WAIT_SECONDS:
            _fail("invalid_configuration", "wait_timeout is outside the permitted range")
        self.scan_context_repository = scan_context_repository
        self.profile_repository = profile_repository
        self.request_repository = request_repository
        self.quota_repository = quota_repository
        self.provider = provider
        self.clock = clock
        self.wait_timeout = wait_timeout
        if not isinstance(authority_consumed, bool):
            _fail("invalid_configuration", "authority_consumed must be boolean")
        self.authority_consumed = authority_consumed

    def _validate_authorities(self, *, user_id, scan_id, scan_revision, items,
                              profiles, source_policy_id, source_policy_revision):
        if self.scan_context_repository is not None:
            try:
                context = self.scan_context_repository.assert_complete_item_set(
                    user_id=user_id, scan_id=scan_id, scan_revision=scan_revision, items=items,
                    include_inactive=self.authority_consumed)
                if self.authority_consumed and context.get("status") != "consumed":
                    _fail("scan_unavailable", "Consumed scan authority is unavailable")
            except Exception as error:
                _fail(getattr(error, "code", "scan_unavailable"), str(error))
        else:
            context = None
        if self.profile_repository is not None:
            try:
                resolver = getattr(self.profile_repository,
                                   "resolve_source_policy_reference", None)
                source = (resolver(source_policy_id, revision=source_policy_revision)
                          if callable(resolver) else
                          self.profile_repository.get_source_policy(
                              source_policy_id, revision=source_policy_revision))
            except Exception as error:
                _fail(getattr(error, "code", "source_unavailable"), str(error))
            if source is None:
                _fail("source_unavailable", "Source policy is missing or withdrawn")
            for reference in profiles:
                try:
                    document = self.profile_repository.get_profile_for_user(
                        user_id, reference["profile_id"], revision=reference["profile_revision"])
                except Exception as error:
                    _fail(getattr(error, "code", "profile_unavailable"), str(error))
                if (document is None
                        or document.get("profile_hash") != reference["profile_hash"]
                        or document.get("source_id") != reference["source_id"]
                        or document.get("source_id") != source.get("source_id")):
                    _fail("profile_conflict", "Profile reference is stale")
        return context

    def _reservation_id(self, request_id, attempts):
        return f"{request_id}:{int(attempts)}"

    def _reconcile_previous_reservation(self, *, request_id, attempts, user_id):
        if attempts <= 1:
            return
        previous_id = self._reservation_id(request_id, attempts - 1)
        try:
            previous = self.quota_repository.get_reservation(previous_id, user_id=user_id)
            if previous and previous.get("status") == "pending":
                self.quota_repository.release(user_id=user_id, reservation_id=previous_id)
        except NutritionQuotaRepositoryError as error:
            if error.code not in {"not_found", "already_completed"}:
                raise

    def _reconcile_terminal_quota(self, *, request_id, attempts, user_id, status):
        reservation_id = self._reservation_id(request_id, attempts)
        try:
            reservation = self.quota_repository.get_reservation(reservation_id, user_id=user_id)
            if reservation and reservation.get("status") == "pending":
                if status in RETRYABLE_STATUSES:
                    self.quota_repository.release(user_id=user_id, reservation_id=reservation_id, status=status)
                else:
                    self.quota_repository.commit(user_id=user_id, reservation_id=reservation_id, status=status)
        except NutritionQuotaRepositoryError as error:
            if error.code not in {"not_found", "already_completed"}:
                raise

    def run(self, *, user_id, scan_id, scan_revision, items, idempotency_key,
            source_policy_id, source_policy_revision, profiles=(), request_kind="nutrition_enrichment",
            wait_timeout=None):
        user_id = _text(user_id, "user_id")
        scan_id = _text(scan_id, "scan_id")
        idempotency_key = _text(idempotency_key, "idempotency_key", MAX_IDEMPOTENCY_KEY)
        source_policy_id = _text(source_policy_id, "source_policy_id")
        if isinstance(scan_revision, bool) or not isinstance(scan_revision, int) or scan_revision < 0:
            _fail("invalid_request", "scan_revision is invalid")
        if isinstance(source_policy_revision, bool) or not isinstance(source_policy_revision, int) or source_policy_revision < 0:
            _fail("invalid_request", "source_policy_revision is invalid")
        if self.profile_repository is not None:
            # Only a repository that exposes the explicit resolver can safely
            # canonicalise a policy-id alias before fingerprinting.  Legacy
            # repository doubles expose get_source_policy() only; deferring
            # their lookup to _validate_authorities preserves the TOCTOU test
            # that checks withdrawal during the provider call.
            resolver = getattr(self.profile_repository,
                               "resolve_source_policy_reference", None)
            if callable(resolver):
                try:
                    source = resolver(source_policy_id, revision=source_policy_revision)
                except Exception as error:
                    _fail(getattr(error, "code", "source_unavailable"), str(error))
                if source is None or source.get("status") not in (None, "active"):
                    _fail("source_unavailable", "Source policy is missing or withdrawn")
                # Canonicalise aliases before fingerprinting so a retry using
                # the source id and one using the policy id share one durable request.
                source_policy_id = source.get("policy_id") or source.get("source_id")
                source_policy_id = _text(source_policy_id, "source_policy_id")
        profiles = _profile_refs(profiles)
        # Fingerprinting validates the full server-owned item schema.
        fingerprint = build_enrichment_request_fingerprint(
            user_id=user_id, scan_id=scan_id, scan_revision=scan_revision, items=items,
            profiles=profiles, source_policy_id=source_policy_id,
            source_policy_revision=source_policy_revision, request_kind=request_kind)
        payload = _canonical_request(user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                                     items=items, profiles=profiles, source_policy_id=source_policy_id,
                                     source_policy_revision=source_policy_revision, request_kind=request_kind)
        lease = self.request_repository.begin(
            user_id=user_id, idempotency_key=idempotency_key, fingerprint=fingerprint,
            request=payload, request_revision=scan_revision)
        if not lease.owner:
            timeout = self.wait_timeout if wait_timeout is None else _finite(wait_timeout, "wait_timeout")
            if timeout < 0 or timeout > MAX_WAIT_SECONDS:
                _fail("invalid_request", "wait_timeout is outside the permitted range")
            try:
                outcome = lease.wait(timeout=timeout)
            except NutritionEnrichmentRepositoryError as error:
                if error.code == "single_flight_timeout":
                    return {"request_id": lease.request_id, "status": "pending", "result": None,
                            "error": None, "replayed": False}
                raise NutritionEnrichmentCoordinatorError(error.code, str(error)) from error
            try:
                document = lease.get() or {}
                # Retryable outcomes normally release quota in the owner
                # process.  Reconcile them too so a release failure/crash does
                # not leave a reservation charged forever.
                self._reconcile_terminal_quota(request_id=lease.request_id,
                                               attempts=document.get("attempts", 1),
                                               user_id=user_id, status=outcome.status)
            except NutritionQuotaRepositoryError as error:
                raise NutritionEnrichmentCoordinatorError(error.code, str(error)) from error
            return {"request_id": lease.request_id, "status": outcome.status,
                    "result": outcome.result, "error": outcome.error, "replayed": True}

        document = lease.get() or {}
        attempts = int(document.get("attempts", 1))
        reservation_id = self._reservation_id(lease.request_id, attempts)
        # Validate only after begin.  This lets a completed request replay even
        # after its source policy has been withdrawn, while a newly-created
        # owner still cannot call a provider without current authorities.
        try:
            self._validate_authorities(user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                                       items=items, profiles=profiles, source_policy_id=source_policy_id,
                                       source_policy_revision=source_policy_revision)
        except NutritionEnrichmentCoordinatorError as authority_error:
            try:
                outcome = lease.complete("source_conflict", None,
                                         error=_error_document(authority_error, authority_error.code))
            except Exception:
                raise
            return {"request_id": lease.request_id, "status": outcome.status,
                    "result": None, "error": outcome.error, "replayed": False}
        try:
            self._reconcile_previous_reservation(request_id=lease.request_id, attempts=attempts, user_id=user_id)
            self.quota_repository.reserve(user_id=user_id, reservation_id=reservation_id)
        except NutritionQuotaRepositoryError as error:
            # Keep the request retryable and durable; the next call can reclaim
            # the lease after the quota window changes.
            try:
                outcome = lease.complete("busy", None, error=_error_document(error, "quota_unavailable"))
            except Exception:
                raise NutritionEnrichmentCoordinatorError(error.code, str(error)) from error
            return {"request_id": lease.request_id, "status": outcome.status,
                    "result": None, "error": outcome.error, "replayed": False}

        try:
            provider_result = self.provider(deepcopy(payload))
            status, result = _status_from_result(
                provider_result,
                expected_item_ids={item["item_id"] for item in items},
            )
            error = None if status not in RETRYABLE_STATUSES else {"code": status, "message": status}
        except Exception as provider_error:
            code = getattr(provider_error, "code", "upstream_error")
            status = "invalid_output" if code == "budget_exceeded" else (code if code in ALL_STATUSES else "upstream_error")
            result = None
            error = _error_document(provider_error, code)

        # The source registry can be withdrawn while a paid provider call is
        # running.  Re-read it before accepting the result; this is the second
        # half of the TOCTOU check and prevents saving a result under stale
        # rights.  The same check covers scan expiry/revocation.
        if status not in RETRYABLE_STATUSES:
            try:
                self._validate_authorities(user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                                           items=items, profiles=profiles, source_policy_id=source_policy_id,
                                           source_policy_revision=source_policy_revision)
            except NutritionEnrichmentCoordinatorError as authority_error:
                status = "source_conflict"
                result = None
                error = _error_document(authority_error, authority_error.code)

        try:
            outcome = lease.complete(status, result, error=error)
        except NutritionEnrichmentRepositoryError as error_update:
            raise NutritionEnrichmentCoordinatorError(error_update.code, str(error_update)) from error_update
        try:
            if status in RETRYABLE_STATUSES:
                self.quota_repository.release(user_id=user_id, reservation_id=reservation_id, status=status)
            else:
                self.quota_repository.commit(user_id=user_id, reservation_id=reservation_id, status=status)
        except Exception:
            # The request result is already durable.  A replay will reconcile
            # this reservation without invoking the provider again.
            pass
        return {"request_id": lease.request_id, "status": outcome.status,
                "result": outcome.result, "error": outcome.error, "replayed": False}


__all__ = ["NutritionEnrichmentCoordinator", "NutritionEnrichmentCoordinatorError"]
