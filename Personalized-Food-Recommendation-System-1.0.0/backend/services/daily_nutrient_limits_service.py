"""User-entered daily limits; does not change clinical or per-meal screening."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation


OVERRIDES_FIELD = "daily_nutrient_limit_overrides"
CONDITION_NUTRIENTS = {
    "diabetes": ("carbs", "sugar"),
    "gout": ("carbs", "fat", "saturated_fat"),
    "hyperlipidemia": ("carbs", "fat", "saturated_fat"),
    "hypertension": ("carbs", "sodium"),
    "kidney_disease": ("carbs", "fat", "saturated_fat", "protein", "sodium"),
}

# These bounds only validate input, not recommended intake.
_SPECS = {
    "carbs": {"unit": "g", "min": 0, "max": 1000, "step": 1, "precision": 1},
    "sugar": {"unit": "g", "min": 0, "max": 500, "step": 1, "precision": 1},
    "fat": {"unit": "g", "min": 0, "max": 500, "step": 1, "precision": 1},
    "saturated_fat": {"unit": "g", "min": 0, "max": 500, "step": 1, "precision": 1},
    "protein": {"unit": "g", "min": 0, "max": 500, "step": 1, "precision": 1},
    "sodium": {"unit": "mg", "min": 0, "max": 10000, "step": 1, "precision": 0},
}


def daily_nutrient_limit_specs():
    return {condition: {nutrient: deepcopy(_SPECS[nutrient]) for nutrient in nutrients}
            for condition, nutrients in CONDITION_NUTRIENTS.items()}


def _validated_value(condition, nutrient, value):
    spec = _SPECS[nutrient]
    error = ValueError(f"{condition}/{nutrient}: enter a number between {spec['min']} and {spec['max']} {spec['unit']} "
                       f"with at most {spec['precision']} decimal places.")
    if type(value) not in (int, float):
        raise error
    try:
        amount = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise error from None
    if (not amount.is_finite() or not spec["min"] <= amount <= spec["max"]
            or amount != amount.quantize(Decimal(1).scaleb(-spec["precision"]))):
        raise error
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def normalize_daily_nutrient_limit_overrides(raw, *, strict=False):
    """Validate stored settings independently of the current condition selection."""
    if not isinstance(raw, dict):
        if strict:
            raise ValueError(f"{OVERRIDES_FIELD} must be an object.")
        return {}
    result = {}
    for condition, overrides in raw.items():
        if condition not in CONDITION_NUTRIENTS or not isinstance(overrides, dict):
            if strict:
                raise ValueError("Unknown condition or invalid daily limit settings.")
            continue
        values = {}
        for nutrient, value in overrides.items():
            if nutrient not in CONDITION_NUTRIENTS[condition]:
                if strict:
                    raise ValueError(f"{condition}/{nutrient}: unsupported daily limit.")
                continue
            try:
                values[nutrient] = _validated_value(condition, nutrient, value)
            except ValueError:
                if strict:
                    raise
        if values:
            result[condition] = values
    return result


def _candidate_values(condition, energy, ideal_weight):
    return {
        "carbs": (energy * {"diabetes": 0.475, "kidney_disease": 0.60}.get(condition, 0.50)) / 4.0,
        "sugar": min((energy * 0.05) / 4.0, 25.0),
        "fat": (energy * (0.325 if condition == "kidney_disease" else 0.25)) / 9.0,
        "saturated_fat": (energy * (0.07 if condition == "hyperlipidemia" else 0.10)) / 9.0,
        "protein": ideal_weight * 0.6,
        "sodium": 1500.0 if condition == "kidney_disease" else 2000.0,
    }


def resolve_daily_nutrient_limits(targets, conditions, energy, ideal_weight, overrides):
    """Use the existing branch priority before replacing applicable candidates."""
    selected = conditions & CONDITION_NUTRIENTS.keys()
    disabled_fat = ("kidney_disease" if selected & {"gout", "hyperlipidemia"} else None)
    disabled_saturated_fat = {"gout", "kidney_disease"} if "hyperlipidemia" in selected else set()
    settings, candidates = {}, {}
    for condition in sorted(selected):
        defaults = _candidate_values(condition, energy, ideal_weight)
        settings[condition] = {}
        for nutrient in CONDITION_NUTRIENTS[condition]:
            default = defaults[nutrient]
            custom = overrides.get(condition, {}).get(nutrient)
            active = not ((nutrient == "fat" and condition == disabled_fat)
                          or (nutrient == "saturated_fat" and condition in disabled_saturated_fat))
            spec = _SPECS[nutrient]
            precision = spec["precision"]
            settings[condition][nutrient] = {**spec, "default_value": round(default, precision),
                "value": custom if custom is not None else round(default, precision),
                "source": "custom" if custom is not None else "default", "active": active}
            if active:
                candidates.setdefault(nutrient, []).append((condition, default, custom))

    effective = dict(targets)
    sources = {}
    for nutrient, entries in candidates.items():
        precision = _SPECS[nutrient]["precision"]
        using_custom = any(custom is not None for _, _, custom in entries)
        values = [(condition, custom if custom is not None else (round(default, precision) if using_custom else default))
                  for condition, default, custom in entries]
        if using_custom:
            effective[nutrient] = min(value for _, value in values)
        sources[nutrient] = [condition for condition, value in values if value == effective[nutrient]]
    for values in settings.values():
        for nutrient, spec in values.items():
            spec["effective_value"] = round(effective[nutrient], spec["precision"])
            spec["effective_condition_ids"] = sources[nutrient]
    return effective, settings
