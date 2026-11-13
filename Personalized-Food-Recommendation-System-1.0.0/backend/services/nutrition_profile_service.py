"""Offline nutrition contracts. Callers must establish source/food identity first.

These functions do not authorize a source, persist a profile, or evaluate medical
risk. Partial profiles must not enter legacy consumers which replace null by zero.
"""

from decimal import Decimal, DecimalException, localcontext
import json
import math
import re

from services.nutrient_service import NUTRITION_FIELDS


PROFILE_VERSION = "NutritionProfileV1"
NUTRIENTS = tuple(NUTRITION_FIELDS)
UNITS = {field: "kcal" if field == "calories" else "mg" if field == "sodium" else "g"
         for field in NUTRIENTS}
REQUIRED_POINTS = ("calories", "protein", "carbs", "fat")
PORTION_SOURCES = {"unknown", "vision_estimate", "user_adjusted", "user_weighed", "label_weight", "assumed"}
DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
MASS_IN_GRAMS = {"g": Decimal(1), "mg": Decimal("0.001"), "ug": Decimal("0.000001")}


class NutritionProfileError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _decimal(value, *, positive=False, strings=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str) if strings else (int, float)):
        raise NutritionProfileError("invalid_number", "Expected a finite nonnegative number")
    if isinstance(value, int) and value.bit_length() > 1024:
        raise NutritionProfileError("invalid_number", "Numeric value exceeds the supported range")
    if isinstance(value, float) and not math.isfinite(value):
        raise NutritionProfileError("invalid_number", "Nonfinite numeric value")
    text = str(value)
    if len(text) > 128 or (isinstance(value, str) and not DECIMAL_TEXT.fullmatch(text)):
        raise NutritionProfileError("invalid_number", "Invalid decimal representation")
    try:
        number = Decimal(text)
        if not number.is_finite() or number < 0 or (positive and number <= 0):
            raise NutritionProfileError("invalid_number", "Number is outside the permitted range")
        # Guard both enormous exponents and values which would serialize as zero.
        _number(number)
        return Decimal(0) if number == 0 else number
    except DecimalException as error:
        raise NutritionProfileError("invalid_number", "Invalid decimal value") from error


def _number(value):
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result) or (value != 0 and result == 0):
        raise NutritionProfileError("numeric_range", "Calculation exceeds the serializable numeric range")
    return result


def _json_copy(value, *, max_bytes=64 * 1024):
    if not isinstance(value, dict):
        raise NutritionProfileError("invalid_metadata", "Metadata must be a server-provided object")
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=True)
        if len(encoded) > max_bytes:
            raise ValueError("Metadata too large")
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise NutritionProfileError("invalid_metadata", "Invalid metadata") from error


def _basis_weight(basis, basis_weight_g, basis_volume_ml):
    if basis not in ("per_100g", "per_serving", "per_100ml"):
        raise NutritionProfileError("invalid_basis", "Unsupported nutrition basis")
    try:
        weight = None if basis_weight_g is None else _decimal(basis_weight_g, positive=True, strings=True)
        volume = None if basis_volume_ml is None else _decimal(basis_volume_ml, positive=True, strings=True)
    except NutritionProfileError as error:
        raise NutritionProfileError("invalid_basis", "Basis requires a positive finite amount") from error
    if basis == "per_100g":
        if (weight is not None and weight != 100) or volume is not None:
            raise NutritionProfileError("invalid_basis", "A per_100g column must describe exactly 100g")
        weight = Decimal(100)
    elif basis == "per_100ml":
        # An audited adapter must supply the explicit weight of this same 100ml.
        if weight is None or volume != 100:
            raise NutritionProfileError("invalid_basis", "100ml requires an evidenced weight for the same volume")
    elif weight is None:
        raise NutritionProfileError("invalid_basis", "Serving weight is unknown; cannot normalize to 100g")
    return weight, volume


def _measurement(field, raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"value", "unit", "comparison", "evidence", "label_rounding"}:
        raise NutritionProfileError("invalid_measurement", "Unexpected nutrient measurement fields")
    if not {"value", "unit", "comparison"} <= set(raw):
        raise NutritionProfileError("invalid_measurement", "Nutrient value, unit and comparison are required")
    comparison = raw["comparison"]
    if comparison not in ("exact", "less_than"):
        raise NutritionProfileError("invalid_measurement", "Unsupported comparison")
    number = _decimal(raw["value"], positive=comparison == "less_than", strings=True)
    unit = raw["unit"]
    if field == "calories":
        if unit not in ("kcal", "kJ"):
            raise NutritionProfileError("invalid_unit", "Energy must use kcal or kJ")
        standard = number if unit == "kcal" else number / Decimal("4.184")
    else:
        if not isinstance(unit, str) or unit not in MASS_IN_GRAMS:
            raise NutritionProfileError("invalid_unit", "Nutrient mass must use g, mg or ug")
        standard = number * MASS_IN_GRAMS[unit]
        if field == "sodium":
            standard *= 1000
    rounding = raw.get("label_rounding")
    if rounding is not None and not isinstance(rounding, bool):
        raise NutritionProfileError("invalid_measurement", "Label rounding must be boolean or unknown")
    normalized = {"value": str(number), "unit": unit, "comparison": comparison, "label_rounding": rounding}
    if "evidence" in raw:
        normalized["evidence"] = _json_copy(raw["evidence"])
    return normalized, standard


def _consistency(points, bounds):
    tolerance_g = Decimal(5)
    grams = {field: value / 1000 if field == "sodium" else value
             for field, value in points.items() if field != "calories" and value is not None}
    if any(value > 100 + tolerance_g for value in grams.values()):
        raise NutritionProfileError("source_conflict", "Nutrient mass exceeds the 100g basis")
    macros = [points[field] for field in ("protein", "carbs", "fat")]
    if sum(value for value in macros if value is not None) > 100 + tolerance_g:
        raise NutritionProfileError("source_conflict", "Macronutrient mass exceeds the 100g basis")
    for subset, whole in (("sugar", "carbs"), ("saturated_fat", "fat"), ("trans_fat", "fat")):
        part, total = points[subset], points[whole]
        if part is not None and total is not None and part > total + max(Decimal(1), total * Decimal("0.05")):
            raise NutritionProfileError("source_conflict", f"{subset} exceeds {whole}")
        if part is not None and bounds[whole] is not None and part >= bounds[whole]:
            raise NutritionProfileError("source_conflict", f"{subset} contradicts the upper bound for {whole}")
    warnings = []
    calories = points["calories"]
    if calories is not None and calories > 1000:
        raise NutritionProfileError("source_conflict", "Energy exceeds a plausible 100g food basis")
    if calories is not None and all(value is not None for value in macros):
        approximate = 4 * macros[0] + 4 * macros[1] + 9 * macros[2]
        if abs(calories - approximate) > max(Decimal(20), calories * Decimal("0.2")):
            warnings.append("energy_macro_discrepancy")
    return warnings


def build_nutrition_profile(nutrients, *, basis, basis_weight_g=None, basis_volume_ml=None, source_details=None):
    """Normalize already grounded raw cells, without inferring any missing field.

    source_details and evidence are server adapter data. This function is not a
    source authentication boundary and must never authorize client-supplied data.
    """
    if not isinstance(nutrients, dict) or set(nutrients) != set(NUTRIENTS):
        raise NutritionProfileError("invalid_measurement", "All nine nullable nutrient keys are required")
    metadata = _json_copy({} if source_details is None else source_details)
    try:
        with localcontext() as context:
            context.prec = 50
            weight, volume = _basis_weight(basis, basis_weight_g, basis_volume_ml)
            points, bounds, originals = {}, {}, {}
            for field in NUTRIENTS:
                parsed = _measurement(field, nutrients[field])
                originals[field] = parsed[0] if parsed is not None else None
                value = parsed[1] * 100 / weight if parsed is not None else None
                points[field] = value if parsed and parsed[0]["comparison"] == "exact" else None
                bounds[field] = value if parsed and parsed[0]["comparison"] == "less_than" else None
            warnings = _consistency(points, bounds)
            missing = [field for field in NUTRIENTS if points[field] is None]
            result = {
                "schema_version": PROFILE_VERSION,
                "basis": basis,
                "basis_weight_g": _number(weight),
                "basis_volume_ml": _number(volume),
                "source_basis": {"basis": basis, "weight_g": str(weight),
                                 "volume_ml": str(volume) if volume is not None else None},
                "source_nutrients": originals,
                "source_details": metadata,
                "units": dict(UNITS),
                "per_100g": {field: _number(points[field]) for field in NUTRIENTS},
                "upper_bounds_per_100g": {field: _number(bounds[field]) for field in NUTRIENTS},
                "bound_comparison": "less_than",
                "missing_nutrition_fields": missing,
                "bounded_nutrition_fields": [field for field in NUTRIENTS if bounds[field] is not None],
                "has_required_point_values": all(points[field] is not None for field in REQUIRED_POINTS),
                "nutrition_status": "complete" if not missing else "partial" if any(value is not None for value in points.values()) else "unknown",
                "validation_warnings": warnings,
            }
            _json_copy(result, max_bytes=768 * 1024)
            return result
    except DecimalException as error:
        raise NutritionProfileError("numeric_range", "Nutrition calculation exceeds the supported range") from error


def _checked_profile(profile):
    if not isinstance(profile, dict) or profile.get("schema_version") != PROFILE_VERSION:
        raise NutritionProfileError("invalid_profile", "Unsupported profile contract")
    original_basis = profile.get("source_basis")
    if not isinstance(original_basis, dict):
        raise NutritionProfileError("invalid_profile", "Original source basis is missing")
    rebuilt = build_nutrition_profile(
        profile.get("source_nutrients"), basis=original_basis.get("basis"),
        basis_weight_g=original_basis.get("weight_g"), basis_volume_ml=original_basis.get("volume_ml"),
        source_details=profile.get("source_details"),
    )
    # JSON tokens distinguish booleans from numbers; Python dict equality does not.
    original_json = json.dumps(_json_copy(profile, max_bytes=768 * 1024), sort_keys=True, allow_nan=False)
    rebuilt_json = json.dumps(rebuilt, sort_keys=True, allow_nan=False)
    if original_json != rebuilt_json:
        raise NutritionProfileError("invalid_profile", "Canonical profile disagrees with its original cells")
    return rebuilt


def profile_from_local_food(food, *, source_details=None):
    """Adapt TFDA/USDA or the selected custom table; matching stays with callers."""
    if not isinstance(food, dict) or food.get("nutrition_basis_status") in ("conflicting", "invalid"):
        raise NutritionProfileError("invalid_profile", "Local nutrition profile is invalid or conflicting")
    unit = food.get("unit")
    basis = {"per 100g": "per_100g", "per serving": "per_serving"}.get(unit) if isinstance(unit, str) else None
    nutrients = {}
    for field in NUTRIENTS:
        value = food.get(field)
        if value is not None:
            _decimal(value)  # Local JSON never silently coerces numeric strings.
        nutrients[field] = None if value is None else {"value": value, "unit": UNITS[field], "comparison": "exact"}
    return build_nutrition_profile(
        nutrients, basis=basis, basis_weight_g=food.get("serving_size_g") if basis == "per_serving" else None,
        source_details=source_details,
    )


def validate_profile_consistency(primary, corroborating_profiles):
    """Cross-check different units/bases of the same server-verified food table."""
    primary = _checked_profile(primary)
    if not isinstance(corroborating_profiles, list):
        raise NutritionProfileError("invalid_profile", "Corroboration requires a profile list")
    profiles = [primary, *[_checked_profile(other) for other in corroborating_profiles]]
    with localcontext() as context:
        context.prec = 50
        normalized = [_portion_decimals(profile, Decimal(100)) for profile in profiles]
        strongest_points, strongest_bounds = {}, {}
        for field in NUTRIENTS:
            values = [points[field] for points, _bounds in normalized if points[field] is not None]
            bounds = [upper[field] for _points, upper in normalized if upper[field] is not None]
            strongest_points[field] = max(values) if values else None
            strongest_bounds[field] = min(bounds) if bounds else None
            if values and bounds and max(values) >= min(bounds):
                raise NutritionProfileError("source_conflict", f"Source point/bound disagree for {field}")
            if len(values) > 1:
                left, right = min(values), max(values)
                absolute = Decimal(2) if field in ("calories", "sodium") else Decimal("0.2")
                tolerance = max(absolute, max(left, right) * Decimal("0.05"))
                if abs(left - right) > tolerance:
                    raise NutritionProfileError("source_conflict", f"Source units/bases disagree for {field}")
        # Reject visible contradictions across sparse columns, without merging
        # their values into the selected profile or filling any missing field.
        _consistency(strongest_points, strongest_bounds)
    return True


def _portion_decimals(profile, weight):
    points, bounds = {}, {}
    if profile is None or weight is None:
        return {field: None for field in NUTRIENTS}, {field: None for field in NUTRIENTS}
    original = profile["source_basis"]
    source_weight, _ = _basis_weight(original["basis"], original["weight_g"], original["volume_ml"])
    for field in NUTRIENTS:
        raw = _measurement(field, profile["source_nutrients"][field])
        # Calculate directly from the original cells, never from display numbers.
        value = raw[1] * weight / source_weight if raw is not None else None
        points[field] = value if raw and raw[0]["comparison"] == "exact" else None
        bounds[field] = value if raw and raw[0]["comparison"] == "less_than" else None
    return points, bounds


def calculate_portion(profile, weight_g, *, portion_source="unknown"):
    """Return nullable intake values. Missing weight never defaults to 100g."""
    if not isinstance(portion_source, str) or portion_source not in PORTION_SOURCES:
        raise NutritionProfileError("invalid_portion", "Unsupported portion source")
    if profile is not None:
        profile = _checked_profile(profile)
    weight = None if weight_g is None else _decimal(weight_g, positive=True)
    try:
        with localcontext() as context:
            context.prec = 50
            points, bounds = _portion_decimals(profile, weight)
            return {
                "weight_g": _number(weight), "portion_source": portion_source,
                "values": {field: _number(points[field]) for field in NUTRIENTS},
                "upper_bounds": {field: _number(bounds[field]) for field in NUTRIENTS},
                "bound_comparison": "less_than",
                "missing_nutrition_fields": [field for field in NUTRIENTS if points[field] is None],
            }
    except DecimalException as error:
        raise NutritionProfileError("numeric_range", "Portion calculation exceeds the supported range") from error


def aggregate_nutrition_coverage(items):
    """Known sums for all included items, including unmatched/unknown portions.

    Exclusion is explicit (not_consumed); bound-only items are unresolved point
    values. Coverage says nothing about missed foods or medical safety.
    """
    if not isinstance(items, list) or len(items) > 10000:
        raise NutritionProfileError("invalid_items", "Expected a bounded item list")
    seen, included, excluded = set(), [], []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str) or not item["item_id"].strip():
            raise NutritionProfileError("invalid_items", "Each item needs a nonempty item_id")
        identifier = item["item_id"]
        if identifier in seen:
            raise NutritionProfileError("invalid_items", "Duplicate item_id")
        seen.add(identifier)
        if not isinstance(item.get("included", True), bool):
            raise NutritionProfileError("invalid_items", "included must be boolean")
        if item.get("included", True) is False:
            if item.get("exclusion_reason") != "not_consumed":
                raise NutritionProfileError("invalid_items", "Exclusion requires an explicit not_consumed decision")
            excluded.append(identifier)
        else:
            included.append(item)
    try:
        with localcontext() as context:
            context.prec = 50
            accumulators = {field: {"sum": Decimal(0), "bounds": Decimal(0), "known": 0, "bounded": 0}
                            for field in NUTRIENTS}
            for item in included:
                profile = item.get("profile")
                if profile is not None:
                    profile = _checked_profile(profile)
                portion_source = item.get("portion_source", "unknown")
                if not isinstance(portion_source, str) or portion_source not in PORTION_SOURCES:
                    raise NutritionProfileError("invalid_portion", "Unsupported portion source")
                weight = None if item.get("weight_g") is None else _decimal(item["weight_g"], positive=True)
                points, bounds = _portion_decimals(profile, weight)
                for field, row in accumulators.items():
                    if points[field] is not None:
                        _number(points[field])
                        row["sum"] += points[field]
                        row["known"] += 1
                    if bounds[field] is not None:
                        _number(bounds[field])
                        row["bounds"] += bounds[field]
                        row["bounded"] += 1
            coverage = {}
            denominator = len(included)
            for field, row in accumulators.items():
                has_total_bound = row["bounded"] > 0 and row["known"] + row["bounded"] == denominator
                coverage[field] = {
                    "known_sum": _number(row["sum"]), "known_items": row["known"],
                    "eligible_items": denominator, "unresolved_items": denominator - row["known"],
                    "bounded_items": row["bounded"], "known_bounds_sum": _number(row["bounds"]),
                    "total_upper_bound": _number(row["sum"] + row["bounds"]) if has_total_bound else None,
                    "upper_bound_comparison": "less_than" if has_total_bound else None,
                    "status": ("complete" if denominator > 0 and row["known"] == denominator else
                               "partial" if row["known"] or row["bounded"] else "unknown"),
                }
            return {"schema_version": "NutritionCoverageV1", "nutrients": coverage,
                    "included_item_ids": [item["item_id"] for item in included], "excluded_item_ids": excluded}
    except DecimalException as error:
        raise NutritionProfileError("numeric_range", "Coverage calculation exceeds the supported range") from error
