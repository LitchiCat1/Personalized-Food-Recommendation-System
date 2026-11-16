"""Validate server-reviewed source policies for USDA FoodData Central detail.

This validator accepts a policy document, not search output. Its review record
is structural evidence only; callers must load policies from server-owned
configuration or the durable source-policy repository.
"""

from copy import deepcopy
from datetime import datetime
import re

from services.fooddata_central_adapter import ADAPTER_VERSION, RETRIEVAL_VERSION
from services.web_nutrition_service import NutritionSourceRegistry, WebNutritionError


PROVIDER_KIND = "usda_fdc_api"
TABLE_SUFFIX = "-per-100g"
_FDC_ID = re.compile(r"[1-9][0-9]{0,17}\Z")
_IDENTITY_FIELDS = {
    "name", "food_state", "preparation_method", "components_scope", "brand", "variant",
}
_TARGET_FIELDS = _IDENTITY_FIELDS - {"name"}
_IDENTITY_ENUMS = {
    "food_state": {"prepared", "raw", "dry"},
    "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted",
                           "braised", "steamed", "mixed"},
    "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides"},
}
_POLICY_FIELDS = {
    "policy_id", "accepted_names", "target_identity", "source_spec", "match_policy",
    "compatibility_review", "rights", "server_review",
}


class FdcSourcePolicyError(ValueError):
    """Stable validation error for FDC-specific reviewed source policy."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FdcSourcePolicyError(code, message)


def _text(value, limit=4096):
    return (isinstance(value, str) and 0 < len(value) <= limit
            and value.strip() == value
            and not any(ord(character) < 32 or ord(character) == 127 for character in value))


def _timestamp(value, field):
    if not _text(value, 64):
        _fail("invalid_review", f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        _fail("invalid_review", f"{field} is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("invalid_review", f"{field} must include a timezone")


def validate_fdc_source_spec(spec):
    """Validate the fixed, versioned identity for one FDC detail endpoint."""
    if not isinstance(spec, dict):
        _fail("invalid_spec", "FDC source_spec must be an object")
    fdc_id = spec.get("fdc_id")
    if not isinstance(fdc_id, str) or not _FDC_ID.fullmatch(fdc_id):
        _fail("invalid_fdc_id", "FDC ID must be a canonical positive numeric string")
    expected_url = f"https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"
    if spec.get("provider_kind") != PROVIDER_KIND:
        _fail("invalid_provider", "FDC source provider_kind must be usda_fdc_api")
    if spec.get("source_id") != f"usda-fdc-{fdc_id}":
        _fail("source_mismatch", "FDC source_id must be bound to its fixed FDC ID")
    if spec.get("source_url") != expected_url:
        _fail("source_mismatch", "FDC source URL must be the exact fixed detail endpoint")
    if spec.get("adapter_version") != ADAPTER_VERSION:
        _fail("invalid_version", "FDC adapter version is unsupported")
    if spec.get("retrieval_version") != RETRIEVAL_VERSION:
        _fail("invalid_version", "FDC retrieval version is unsupported")
    if spec.get("table_id") != f"fdc-{fdc_id}{TABLE_SUFFIX}":
        _fail("source_mismatch", "FDC table_id must be bound to the fixed ID and per-100g basis")

    identity = spec.get("food_identity")
    if not isinstance(identity, dict) or set(identity) != _IDENTITY_FIELDS:
        _fail("invalid_identity", "FDC source identity must use the canonical identity fields")
    if not _text(identity.get("name"), 300):
        _fail("invalid_identity", "FDC source identity name is required")
    for field, allowed in _IDENTITY_ENUMS.items():
        if identity.get(field) not in allowed:
            _fail("invalid_identity", f"FDC source identity {field} must be explicit and known")
    for field in ("brand", "variant"):
        value = identity.get(field)
        if value is not None and not _text(value, 300):
            _fail("invalid_identity", f"FDC source identity {field} must be text or null")
    return deepcopy(spec)


def validate_fdc_source_policy(policy):
    """Validate one explicitly approved FDC policy; never promote candidates.

    Generic source rights/compatibility checks are delegated to the existing
    registry so Tavily remains governed by its current, unchanged contract.
    """
    if not isinstance(policy, dict) or set(policy) != _POLICY_FIELDS:
        _fail("invalid_policy", "A canonical FDC source policy is required")
    spec = validate_fdc_source_spec(policy.get("source_spec"))

    target = policy.get("target_identity")
    if not isinstance(target, dict) or set(target) != _TARGET_FIELDS:
        _fail("invalid_identity", "FDC target identity must use the canonical target fields")
    source_identity = spec["food_identity"]
    for field in _TARGET_FIELDS:
        if source_identity[field] != target[field]:
            _fail("identity_mismatch", f"FDC target and source identity differ in {field}")
    names = policy.get("accepted_names")
    if not isinstance(names, (list, tuple)) or not names or len(names) > 16:
        _fail("invalid_policy", "Reviewed recognition aliases are required")
    if (any(not _text(name, 300) for name in names)
            or len(set(names)) != len(names)):
        _fail("invalid_policy", "Recognition aliases must be reviewed exact names")

    review = policy.get("server_review")
    review_fields = {"status", "provider_kind", "reviewer", "reviewed_at"}
    if not isinstance(review, dict) or set(review) != review_fields:
        _fail("invalid_review", "A server review record is required")
    if review.get("status") != "approved" or review.get("provider_kind") != PROVIDER_KIND:
        _fail("invalid_review", "FDC source policy is not explicitly approved")
    if not _text(review.get("reviewer"), 256):
        _fail("invalid_review", "A named FDC policy reviewer is required")
    _timestamp(review.get("reviewed_at"), "server_review.reviewed_at")

    try:
        NutritionSourceRegistry([policy])
    except WebNutritionError as error:
        _fail("invalid_policy", str(error))
    return deepcopy(policy)


__all__ = [
    "FdcSourcePolicyError", "PROVIDER_KIND", "validate_fdc_source_policy",
    "validate_fdc_source_spec",
]
