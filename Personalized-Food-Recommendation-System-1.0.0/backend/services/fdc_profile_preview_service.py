"""Server-owned, read-only USDA FDC profile preview orchestration.

This boundary joins an issued user confirmation, its active scan context and
an active reviewed source policy. It deliberately does not persist profiles
or write meal records; callers supply only references, never FDC documents,
policies, weights or candidate IDs.
"""

from copy import deepcopy
import math
import time

from repositories.fdc_candidate_confirmation_repository import (
    FdcCandidateConfirmationRepositoryError,
)
from repositories.scan_context_repository import ScanContextRepositoryError
from repositories.nutrition_profile_repository import NutritionRepositoryError
from services.fdc_detail_profile_service import (
    FdcDetailProfileError,
    build_fdc_detail_profile,
)
from services.fdc_source_policy_service import (
    FdcSourcePolicyError,
    validate_fdc_source_policy,
)


class FdcProfilePreviewError(ValueError):
    """Stable failure boundary for a future disabled-by-default route."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FdcProfilePreviewError(code, message)


def _identifier(value, field):
    if (not isinstance(value, str) or not value or len(value) > 256
            or value.strip() != value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _revision(value, field):
    if type(value) is not int or value < 0:
        _fail("invalid_request", f"{field} is invalid")
    return value


def _confirmed_item(confirmation, item_id):
    if not isinstance(confirmation, dict):
        _fail("confirmation_required", "A server-owned confirmation is required")
    items = confirmation.get("confirmed_items")
    if not isinstance(items, list):
        _fail("confirmation_required", "The confirmation has no confirmed items")
    matches = [item for item in items if isinstance(item, dict) and item.get("item_id") == item_id]
    if len(matches) != 1:
        _fail("confirmation_required", "The item has no unique confirmed FDC candidate")
    item = matches[0]
    fdc_id = item.get("confirmed_fdc_id")
    if (not isinstance(fdc_id, str) or not fdc_id.isascii() or not fdc_id.isdigit()
            or fdc_id.startswith("0") or len(fdc_id) > 18):
        _fail("confirmation_required", "The item has no canonical confirmed FDC ID")
    if type(item.get("item_revision")) is not int or item["item_revision"] < 0:
        _fail("revision_conflict", "The confirmation item revision is invalid")
    return deepcopy(item)


def _scan_item(context, *, item_id, expected_revision):
    if not isinstance(context, dict):
        _fail("stale_revision", "The issued scan context is unavailable")
    items = context.get("items")
    if not isinstance(items, list):
        _fail("scan_unavailable", "The issued scan context has no items")
    matches = [item for item in items if isinstance(item, dict) and item.get("item_id") == item_id]
    if len(matches) != 1:
        _fail("scan_unavailable", "The item is not uniquely present in the issued scan context")
    item = matches[0]
    if item.get("item_revision") != expected_revision:
        _fail("revision_conflict", "The confirmed item revision differs from the issued scan context")
    weight = item.get("estimated_weight_g")
    if (isinstance(weight, bool) or not isinstance(weight, (int, float))
            or not math.isfinite(weight) or weight <= 0):
        _fail("invalid_portion", "The issued scan context has no usable positive weight")
    identity = {
        "name_zh": item.get("name_zh"),
        "food_state": item.get("food_state"),
        "preparation_method": item.get("preparation_method"),
        "components_scope": item.get("components_scope"),
        "brand": item.get("brand"),
        "variant": item.get("variant"),
    }
    return deepcopy(item), identity, weight


def _load_policy(source_repository, fdc_id):
    source_id = "usda-fdc-" + fdc_id
    try:
        policy = source_repository.get_source_policy(source_id)
    except NutritionRepositoryError as error:
        raise FdcProfilePreviewError(error.code, str(error)) from error
    if not isinstance(policy, dict) or policy.get("status") != "active":
        _fail("source_unavailable", "The reviewed FDC source policy is unavailable")
    try:
        checked = validate_fdc_source_policy(policy.get("policy"))
    except FdcSourcePolicyError as error:
        raise FdcProfilePreviewError(error.code, str(error)) from error
    spec = checked["source_spec"]
    if not checked["rights"].get("extract_allowed"):
        _fail("rights_not_allowed", "The reviewed FDC policy does not allow detail retrieval")
    if type(policy.get("revision")) is not int or policy["revision"] < 0:
        _fail("invalid_policy", "The active FDC policy revision is invalid")
    if (policy.get("source_id") != source_id or spec.get("source_id") != source_id
            or spec.get("fdc_id") != fdc_id):
        _fail("source_conflict", "The active FDC policy is not bound to the confirmed ID")
    return policy, checked


def _assert_scan_compatible(recognition, policy):
    spec = policy["source_spec"]
    identity = spec["food_identity"]
    if recognition.get("name_zh") not in policy["accepted_names"]:
        _fail("identity_mismatch", "The scan name is not an exact reviewed alias")
    for field in ("food_state", "preparation_method", "components_scope", "brand", "variant"):
        if recognition.get(field) != identity.get(field):
            _fail("identity_mismatch", f"The scan and FDC policy differ in {field}")


def _snapshot_confirmation(confirmation):
    return {
        "confirmation_id": confirmation.get("confirmation_id"),
        "scan_id": confirmation.get("scan_id"),
        "issued_scan_revision": confirmation.get("issued_scan_revision"),
        "snapshot_digest": confirmation.get("snapshot_digest"),
        "confirmed_items": deepcopy(confirmation.get("confirmed_items")),
    }


def _snapshot_context(context):
    return {
        "scan_id": context.get("scan_id"),
        "scan_revision": context.get("scan_revision"),
        "item_set_hash": context.get("item_set_hash"),
        "items": deepcopy(context.get("items")),
        "status": context.get("status"),
    }


def _snapshot_policy(policy):
    return {
        "source_id": policy.get("source_id"),
        "policy_id": policy.get("policy_id"),
        "revision": policy.get("revision"),
        "status": policy.get("status"),
        "policy": deepcopy(policy.get("policy")),
    }


class FdcProfilePreviewService:
    """Resolve all preview inputs from authenticated server-owned repositories."""

    def __init__(self, *, confirmation_repository, scan_context_repository,
                 source_repository, detail_client_factory,
                 profile_builder=build_fdc_detail_profile, clock=time.time,
                 monotonic=time.monotonic):
        required = (
            (confirmation_repository, "get_confirmation"),
            (scan_context_repository, "get_scan_context"),
            (source_repository, "get_source_policy"),
        )
        if any(value is None or not hasattr(value, method) for value, method in required):
            _fail("storage_unavailable", "Server-owned confirmation, scan and source repositories are required")
        if not callable(detail_client_factory) or not callable(profile_builder):
            _fail("invalid_service", "Detail client and profile builder are required")
        if not callable(clock) or not callable(monotonic):
            _fail("invalid_clock", "Clock functions are required")
        self.confirmation_repository = confirmation_repository
        self.scan_context_repository = scan_context_repository
        self.source_repository = source_repository
        self.detail_client_factory = detail_client_factory
        self.profile_builder = profile_builder
        self.clock = clock
        self.monotonic = monotonic

    def _confirmation(self, *, user_id, confirmation_id, scan_id, revision):
        try:
            confirmation = self.confirmation_repository.get_confirmation(
                authenticated_user_id=user_id,
                confirmation_id=confirmation_id,
                scan_id=scan_id,
                issued_scan_revision=revision,
                now=self.clock(),
            )
        except FdcCandidateConfirmationRepositoryError as error:
            raise FdcProfilePreviewError(error.code, str(error)) from error
        if confirmation is None:
            _fail("confirmation_required", "The confirmation is unavailable")
        if (confirmation.get("confirmation_id") != confirmation_id
                or confirmation.get("scan_id") != scan_id
                or confirmation.get("issued_scan_revision") != revision):
            _fail("revision_conflict", "The confirmation binding does not match this preview")
        return confirmation

    def _context(self, *, user_id, scan_id, revision):
        try:
            context = self.scan_context_repository.get_scan_context(
                user_id=user_id, scan_id=scan_id, scan_revision=revision,
                include_inactive=False, now=self.clock(),
            )
        except ScanContextRepositoryError as error:
            raise FdcProfilePreviewError(error.code, str(error)) from error
        if context is None:
            _fail("stale_revision", "The issued scan context is unavailable")
        if (context.get("user_id") != user_id or context.get("scan_id") != scan_id
                or context.get("scan_revision") != revision or context.get("status") != "active"):
            _fail("stale_revision", "The issued scan context is no longer active")
        return context

    def preview(self, *, authenticated_user_id, confirmation_id, scan_id,
                issued_scan_revision, item_id):
        user_id = _identifier(authenticated_user_id, "authenticated_user_id")
        confirmation_id = _identifier(confirmation_id, "confirmation_id")
        scan_id = _identifier(scan_id, "scan_id")
        item_id = _identifier(item_id, "item_id")
        revision = _revision(issued_scan_revision, "issued_scan_revision")

        confirmation = self._confirmation(user_id=user_id, confirmation_id=confirmation_id,
                                         scan_id=scan_id, revision=revision)
        confirmed_item = _confirmed_item(confirmation, item_id)
        context = self._context(user_id=user_id, scan_id=scan_id, revision=revision)
        scan_item, recognition_identity, weight = _scan_item(
            context, item_id=item_id, expected_revision=confirmed_item["item_revision"])
        policy_document, policy = _load_policy(self.source_repository,
                                               confirmed_item["confirmed_fdc_id"])
        _assert_scan_compatible(recognition_identity, policy)

        client = self.detail_client_factory()
        try:
            try:
                document = client.get_food(
                    confirmed_item["confirmed_fdc_id"], deadline=self.monotonic() + 15)
            except Exception as error:
                code = getattr(error, "code", "detail_unavailable")
                raise FdcProfilePreviewError(code, "FDC detail retrieval failed") from error
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:
                    raise FdcProfilePreviewError("detail_unavailable", "FDC detail client cleanup failed") from error

        # Re-resolve every mutable authorization input after network I/O. A
        # policy withdrawal, revision, or scan supersession must invalidate
        # the fetched document instead of yielding a stale preview.
        current_confirmation = self._confirmation(
            user_id=user_id, confirmation_id=confirmation_id,
            scan_id=scan_id, revision=revision)
        current_context = self._context(user_id=user_id, scan_id=scan_id, revision=revision)
        current_confirmed_item = _confirmed_item(current_confirmation, item_id)
        current_scan_item, current_identity, current_weight = _scan_item(
            current_context, item_id=item_id,
            expected_revision=current_confirmed_item["item_revision"])
        current_policy_document, current_policy = _load_policy(
            self.source_repository, current_confirmed_item["confirmed_fdc_id"])
        if (_snapshot_confirmation(current_confirmation) != _snapshot_confirmation(confirmation)
                or _snapshot_context(current_context) != _snapshot_context(context)
                or _snapshot_policy(current_policy_document) != _snapshot_policy(policy_document)
                or current_confirmed_item != confirmed_item
                or current_scan_item != scan_item
                or current_identity != recognition_identity
                or current_weight != weight
                or current_policy != policy):
            _fail("authorization_changed", "Server-owned preview authorization changed during retrieval")
        if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
            _fail("detail_invalid", "The provider returned an invalid FDC detail document")
        returned_fdc_id = document["payload"].get("fdcId")
        if str(returned_fdc_id) != confirmed_item["confirmed_fdc_id"]:
            _fail("source_conflict", "Retrieved FDC document differs from the confirmed record")

        try:
            result = self.profile_builder(
                document=document,
                spec=policy["source_spec"],
                confirmed_item_identity=recognition_identity,
                item_id=item_id,
                weight_g=weight,
            )
        except FdcDetailProfileError as error:
            raise FdcProfilePreviewError(error.code, str(error)) from error
        return {
            "status": "preview",
            "user_id": user_id,
            "confirmation_id": confirmation_id,
            "scan_id": scan_id,
            "issued_scan_revision": revision,
            "item_id": item_id,
            "item_revision": scan_item["item_revision"],
            "snapshot_digest": confirmation.get("snapshot_digest"),
            "source_id": policy_document["source_id"],
            "source_policy_id": policy_document["policy_id"],
            "source_policy_revision": policy_document["revision"],
            "fdc_id": confirmed_item["confirmed_fdc_id"],
            "weight_g": weight,
            "preview": deepcopy(result),
            "photo_confidence_changed": False,
            "profile_written": False,
        }


__all__ = ["FdcProfilePreviewError", "FdcProfilePreviewService"]
