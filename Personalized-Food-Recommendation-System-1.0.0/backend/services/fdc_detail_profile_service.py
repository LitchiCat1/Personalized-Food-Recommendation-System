"""Convert one server-owned USDA FDC detail replay into a nutrition profile.

This module is deliberately a pure continuation boundary.  It accepts only
server-owned detail/spec/identity inputs, never performs HTTP or persistence,
and does not carry image confidence through the result.  Provider values are
adapted into the existing audited evidence contract before a profile or
portion is calculated.
"""

from copy import deepcopy
import math

from services.fooddata_central_adapter import (
    FoodDataCentralAdapterError,
    build_reviewed_fooddata_central_source,
)
from services.nutrition_evidence_service import (
    NUTRIENTS,
    NutritionEvidenceError,
    SCHEMA_VERSION as NUTRITION_EXTRACTION_SCHEMA_VERSION,
    validate_and_build_nutrition_profiles,
)
from services.nutrition_profile_service import (
    NutritionProfileError,
    calculate_portion,
)


class FdcDetailProfileError(ValueError):
    """Stable error boundary for the future route/coordinator."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FdcDetailProfileError(code, message)


def _item_id(value):
    if (not isinstance(value, str) or not value or len(value) > 128
            or value.strip() != value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail("invalid_item", "item_id is invalid")
    return value


_SOURCE_IDENTITY_FIELDS = {"name", "food_state", "preparation_method", "components_scope", "brand", "variant"}
_RECOGNITION_IDENTITY_FIELDS = {"name_zh", "food_state", "preparation_method", "components_scope", "brand", "variant"}
_IDENTITY_ENUMS = {
    "food_state": {"prepared", "raw", "dry", "unknown"},
    "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised", "steamed", "mixed", "unknown"},
    "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides", "unknown"},
}


def _source_identity(value):
    """Require the exact identity supplied by the reviewed FDC record."""
    fields = _SOURCE_IDENTITY_FIELDS
    if not isinstance(value, dict) or set(value) != fields:
        _fail("invalid_identity", "A canonical FDC source identity is required")
    if not isinstance(value["name"], str) or not value["name"].strip() or value["name"].strip() != value["name"]:
        _fail("invalid_identity", "FDC source identity name is invalid")
    for field, allowed in _IDENTITY_ENUMS.items():
        if value[field] not in allowed:
            _fail("invalid_identity", f"FDC source identity {field} is invalid")
    for field in ("brand", "variant"):
        if value[field] is not None and (not isinstance(value[field], str) or not value[field].strip()):
            _fail("invalid_identity", f"FDC source identity {field} is invalid")
    return deepcopy(value)


def _recognition_identity(value):
    """Require the scan identity without treating unknown as a wildcard."""
    if not isinstance(value, dict) or set(value) != _RECOGNITION_IDENTITY_FIELDS:
        _fail("invalid_identity", "A canonical scan recognition identity is required")
    if (not isinstance(value["name_zh"], str) or not value["name_zh"].strip()
            or value["name_zh"].strip() != value["name_zh"]):
        _fail("invalid_identity", "Scan recognition name is invalid")
    for field, allowed in _IDENTITY_ENUMS.items():
        if value[field] is not None and value[field] not in allowed:
            _fail("invalid_identity", f"Scan recognition identity {field} is invalid")
    for field in ("brand", "variant"):
        if value[field] is not None and (not isinstance(value[field], str) or not value[field].strip()):
            _fail("invalid_identity", f"Scan recognition identity {field} is invalid")
    return deepcopy(value)


def _assert_identity_compatible(recognition, source):
    """Names are display labels; all other identity fields are exact keys."""
    for field in ("food_state", "preparation_method", "components_scope", "brand", "variant"):
        # Deliberately compare None and "unknown" as ordinary values.  Neither
        # is a wildcard that can authorize an incompatible FDC record.
        if recognition[field] != source[field]:
            _fail("identity_mismatch", f"Scan and FDC source identities differ in {field}")


def _weight(value):
    # The continuation must never silently turn an unknown image portion into
    # a 100 g serving.  The profile itself remains per 100 g.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("invalid_portion", "A positive food weight is required")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail("invalid_portion", "A positive food weight is required")
    if numeric <= 0 or not math.isfinite(numeric):
        _fail("invalid_portion", "A positive food weight is required")
    return value


def build_fdc_detail_profile(*, document, spec, confirmed_item_identity, item_id,
                             weight_g, portion_source="vision_estimate"):
    """Build one profile and calculated portion from a fixed FDC detail replay.

    ``document``, ``spec`` and ``confirmed_item_identity`` must have already
    been loaded from authenticated server state.  This function still checks
    their internal bindings so callers cannot accidentally combine a detail
    document with another candidate's policy or identity.
    """
    item_id = _item_id(item_id)
    recognition_identity = _recognition_identity(confirmed_item_identity)
    if not isinstance(spec, dict) or not isinstance(spec.get("food_identity"), dict):
        _fail("invalid_identity", "A reviewed FDC spec is required")
    source_identity = _source_identity(spec["food_identity"])
    _assert_identity_compatible(recognition_identity, source_identity)
    _weight(weight_g)

    try:
        source = build_reviewed_fooddata_central_source(
            document, spec=spec, eligible_item_ids=[item_id])
        table = source["tables"][0]
        columns = table["columns"]
        # Prefer kcal when the fixed adapter supplied it; otherwise kJ is still
        # a valid energy basis and the profile service converts it to kcal.
        column_id = "per_100g_kcal" if "per_100g_kcal" in columns else "per_100g_kj"
        rows = table["rows"]
        selections = {
            nutrient: ({"row_id": "fdc-" + nutrient}
                       if "fdc-" + nutrient in rows else None)
            for nutrient in NUTRIENTS
        }
        extraction = {
            "schema_version": NUTRITION_EXTRACTION_SCHEMA_VERSION,
            "items": [{
                "item_id": item_id,
                "status": "candidate",
                "source_id": source["source_id"],
                "table_id": table["table_id"],
                "column_id": column_id,
                "nutrients": selections,
            }],
        }
        entry = validate_and_build_nutrition_profiles(
            extraction,
            expected_items=[{
                "item_id": item_id,
                "name": source_identity["name"],
                "food_state": source_identity["food_state"],
                "preparation_method": source_identity["preparation_method"],
                "components_scope": source_identity["components_scope"],
                "brand": source_identity["brand"],
                "variant": source_identity["variant"],
            }],
            source_blocks=[source],
        )[0]
        profile = entry.get("nutrition_profile")
        if entry.get("status") != "candidate" or not isinstance(profile, dict):
            _fail("invalid_output", "FDC detail did not produce a nutrition profile")
        if not profile.get("has_required_point_values"):
            _fail("missing_core", "FDC detail is missing required core nutrients")
        profile["source_details"].update({
            "provider_kind": spec.get("provider_kind", "usda_fdc_api"),
            "fdc_id": str(document["payload"]["fdcId"]),
        })
        portion = calculate_portion(profile, weight_g, portion_source=portion_source)
    except FdcDetailProfileError:
        raise
    except FoodDataCentralAdapterError as error:
        raise FdcDetailProfileError(error.code, str(error)) from error
    except NutritionEvidenceError as error:
        raise FdcDetailProfileError(error.code, str(error)) from error
    except NutritionProfileError as error:
        raise FdcDetailProfileError(error.code, str(error)) from error

    return {
        "item_id": item_id,
        "recognition_identity": deepcopy(recognition_identity),
        "source_identity": deepcopy(source_identity),
        "source_block": deepcopy(source),
        "nutrition_profile": deepcopy(profile),
        "portion": deepcopy(portion),
        # Deliberately no confidence field: nutrition enrichment cannot raise
        # or otherwise mutate the vision recognition confidence.
    }


__all__ = ["FdcDetailProfileError", "build_fdc_detail_profile"]
