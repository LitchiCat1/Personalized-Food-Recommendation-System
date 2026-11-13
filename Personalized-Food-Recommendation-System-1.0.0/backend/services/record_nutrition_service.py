"""Versioned record snapshots; public input never establishes source authority."""

from copy import deepcopy
from decimal import Decimal
import json
import math

from services.nutrition_profile_service import (
    NUTRIENTS, UNITS, NutritionProfileError, aggregate_nutrition_coverage,
    build_nutrition_profile, calculate_portion,
)


def _copy_json(value):
    try:
        text = json.dumps(value, allow_nan=False, ensure_ascii=True)
        if len(text) > 1024 * 1024:
            raise ValueError("Record snapshot too large")
        return json.loads(text)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise NutritionProfileError("invalid_record", "Invalid record snapshot") from error


def _coverage_item(food):
    return {
        "item_id": food.get("item_id"), "profile": food.get("nutrition_profile"),
        "weight_g": food.get("weight_g"), "portion_source": food.get("portion_source", "unknown"),
        "included": food.get("included", True), "exclusion_reason": food.get("exclusion_reason"),
    }


def enrich_record_nutrition(record):
    """Rebuild trusted stored snapshots, leaving legacy values uninterpreted."""
    result = deepcopy(record)
    if result.get("nutrition_contract_version") != 2:
        result["nutrition_contract_version"] = 1
        result["nutrition_context"] = {"status": "legacy_unknown"}
        return result
    foods = result.get("foods")
    if not isinstance(foods, list) or not foods or len(foods) > 200:
        raise NutritionProfileError("invalid_record", "A v2 record needs 1 to 200 food items")
    coverage = aggregate_nutrition_coverage([_coverage_item(food) for food in foods])
    for food in foods:
        portion = calculate_portion(food.get("nutrition_profile"), food.get("weight_g"),
                                    portion_source=food.get("portion_source", "unknown"))
        food.update(portion["values"])
        food["nutrition_intake"] = portion
        food["missing_nutrition_fields"] = portion["missing_nutrition_fields"]
    context = result.get("nutrition_context")
    if not isinstance(context, dict):
        raise NutritionProfileError("invalid_record", "nutrition_context must be an object")
    context["coverage"] = coverage
    context["unresolved_item_ids"] = [food["item_id"] for food in foods
                                      if food.get("included", True) and
                                      food["missing_nutrition_fields"]]
    context["contract_version"] = 2
    context["visual_completeness"] = "not_verified"
    for field in NUTRIENTS:
        # Numeric totals are known sums, never an assertion of complete intake.
        result[f"total_{field}"] = coverage["nutrients"][field]["known_sum"]
    result["contains_fried_food"] = any(food.get("included", True) and food.get("is_fried") is True
                                         for food in foods)
    return result


def normalize_v2_record(data, *, existing=None, resolve_food=None):
    """Accept server-local identities, existing snapshots, or explicit manual input.

    Web profiles need a future authenticated profile repository. Until then the
    public API cannot turn arbitrary client JSON into an official/web reference.
    """
    payload = _copy_json(data)
    if type(payload.get("nutrition_contract_version")) is not int or payload["nutrition_contract_version"] != 2:
        raise NutritionProfileError("invalid_contract", "nutrition_contract_version must be integer 2")
    foods = payload.get("foods")
    if not isinstance(foods, list) or not foods or len(foods) > 200:
        raise NutritionProfileError("invalid_record", "A record needs 1 to 200 food items")
    old_foods = {food["item_id"]: food for food in (existing or {}).get("foods", [])
                 if isinstance(food, dict) and "item_id" in food}
    seen, normalized = set(), []
    for incoming in foods:
        if not isinstance(incoming, dict):
            raise NutritionProfileError("invalid_record", "Food must be an object")
        identifier = incoming.get("item_id")
        name = incoming.get("name")
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 160 or identifier in seen:
            raise NutritionProfileError("invalid_record", "Unique nonempty item_id required")
        if not isinstance(name, str) or not name.strip() or len(name) > 300:
            raise NutritionProfileError("invalid_record", "Food name required")
        seen.add(identifier)
        old = old_foods.get(identifier)
        if old is not None and name.strip() != old.get("name"):
            raise NutritionProfileError("profile_identity_changed", "Changing food identity requires a new item")
        food = {"item_id": identifier, "name": name.strip(),
                "weight_g": incoming.get("weight_g"),
                "portion_source": incoming.get("portion_source", "unknown"),
                "included": incoming.get("included", True),
                "exclusion_reason": incoming.get("exclusion_reason")}
        if "user_entered_nutrients" in incoming:
            nutrients = incoming["user_entered_nutrients"]
            if not isinstance(nutrients, dict) or set(nutrients) != set(NUTRIENTS):
                raise NutritionProfileError("invalid_record", "Manual input requires all nine nutrient fields")
            food["nutrition_profile"] = build_nutrition_profile(
                {key: None if value is None else
                 value if isinstance(value, dict) else {"value": value, "unit": UNITS[key], "comparison": "exact"}
                 for key, value in nutrients.items()}, basis="per_100g",
                source_details={"source_type": "user_modified", "food_name": food["name"]})
            food["source"] = "user_modified"
            food["original_nutrition_profile"] = (old.get("original_nutrition_profile") or old.get("nutrition_profile")) if old else None
            food["is_fried"] = old.get("is_fried", False) if old else incoming.get("is_fried", False)
            food["allergens"] = deepcopy(old.get("allergens", [])) if old else []
            food["gi"] = old.get("gi") if old else None
            if old:
                food["original_food_identity"] = deepcopy(old.get("original_food_identity") or {
                    key: old[key] for key in ("name", "food_key", "source", "allergens", "is_fried", "gi") if key in old})
        elif old is not None:
            if food["name"] != old.get("name") or incoming.get("food_key", old.get("food_key")) != old.get("food_key"):
                raise NutritionProfileError("profile_identity_changed", "Changing food identity requires new manual input or a new item")
            if "nutrition_profile" in incoming and incoming["nutrition_profile"] != old.get("nutrition_profile"):
                raise NutritionProfileError("untrusted_profile", "Existing source snapshot cannot be overwritten")
            for key in ("nutrition_profile", "original_nutrition_profile", "original_food_identity", "food_key", "source", "is_fried", "allergens", "gi"):
                if key in old:
                    food[key] = deepcopy(old[key])
        elif incoming.get("food_key") is not None:
            key = incoming["food_key"]
            if not isinstance(key, str) or not key or resolve_food is None:
                raise NutritionProfileError("invalid_record", "A valid local food_key is required")
            source = resolve_food(key)
            if source is None:
                raise NutritionProfileError("unknown_food", "Local food identity does not exist")
            if food["name"] != source["name"]:
                raise NutritionProfileError("profile_identity_changed", "Food name must match the selected source identity")
            food.update(deepcopy(source))
            food["food_key"] = key
        else:
            if incoming.get("nutrition_profile") is not None:
                raise NutritionProfileError("untrusted_profile", "Client profiles cannot establish source authority")
            food.update({"nutrition_profile": None, "source": "unresolved", "is_fried": False,
                         "allergens": [], "gi": None})
        if type(food.get("is_fried", False)) is not bool:
            raise NutritionProfileError("invalid_record", "is_fried must be boolean")
        # Validate numbers even on excluded items; omitted weight remains null.
        calculate_portion(food.get("nutrition_profile"), food["weight_g"], portion_source=food["portion_source"])
        normalized.append(food)
    if set(old_foods) - seen:
        raise NutritionProfileError("missing_items", "Keep existing items; exclude uneaten items explicitly")
    if existing is not None:
        context = deepcopy(existing["nutrition_context"])
        previous = context.get("revision", 0)
        if type(payload.get("base_revision")) is not int or payload["base_revision"] != previous:
            raise NutritionProfileError("stale_revision", "Record changed; reload before editing")
        context["revision"] = previous + 1
    else:
        supplied = payload.get("nutrition_context", {})
        if not isinstance(supplied, dict):
            raise NutritionProfileError("invalid_record", "nutrition_context must be an object")
        context = {key: supplied[key] for key in ("scan_id", "recognition_context") if key in supplied}
        context.update({"revision": 0, "recognition_context_authority": "client_supplied"})
    recognition = context.get("recognition_context", {})
    if not isinstance(recognition, dict):
        raise NutritionProfileError("invalid_record", "recognition_context must be an object")
    recognition_items = recognition.get("items", [])
    if not isinstance(recognition_items, list) or any(not isinstance(item, dict) or item.get("item_id") not in seen
                                                      for item in recognition_items):
        raise NutritionProfileError("missing_items", "Every recognition item must remain in the record")
    return enrich_record_nutrition({"nutrition_contract_version": 2, "foods": normalized,
                                    "nutrition_context": context})


def aggregate_record_coverage(records):
    """Aggregate complete record scopes; historical unknown remains explicit."""
    rows = {key: {"sum": Decimal(0), "bounds": Decimal(0), "known": 0, "eligible": 0,
                  "bounded": 0, "legacy": 0} for key in NUTRIENTS}
    for record in records:
        if record.get("nutrition_contract_version") == 2:
            coverage = enrich_record_nutrition(record)["nutrition_context"]["coverage"]["nutrients"]
            for field, row in rows.items():
                source = coverage[field]
                row["sum"] += Decimal(str(source["known_sum"]))
                row["bounds"] += Decimal(str(source["known_bounds_sum"]))
                row["known"] += source["known_items"]
                row["eligible"] += source["eligible_items"]
                row["bounded"] += source["bounded_items"]
        else:
            count = max(1, len(record.get("foods") or []))
            for field, row in rows.items():
                value = record.get(f"total_{field}")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    try:
                        if not math.isfinite(value) or value < 0:
                            raise NutritionProfileError("numeric_range", "Invalid legacy record sum")
                        row["sum"] += Decimal(str(value))
                    except (OverflowError, ValueError) as error:
                        raise NutritionProfileError("numeric_range", "Invalid legacy record sum") from error
                row["eligible"] += count
                row["legacy"] += count
    result = {}
    for field, row in rows.items():
        denominator = row["eligible"]
        total_bound = row["bounded"] > 0 and row["known"] + row["bounded"] == denominator and not row["legacy"]
        result[field] = {
            "known_sum": float(row["sum"]), "known_bounds_sum": float(row["bounds"]),
            "known_items": row["known"], "eligible_items": denominator,
            "unresolved_items": denominator - row["known"], "bounded_items": row["bounded"],
            "legacy_items": row["legacy"],
            "total_upper_bound": float(row["sum"] + row["bounds"]) if total_bound else None,
            "upper_bound_comparison": "less_than" if total_bound else None,
            "status": ("legacy_unknown" if row["legacy"] else
                       "complete" if denominator and row["known"] == denominator else
                       "partial" if row["known"] or row["bounded"] else "unknown"),
        }
        if any(value is not None and not math.isfinite(value) for value in
               (result[field]["known_sum"], result[field]["known_bounds_sum"], result[field]["total_upper_bound"])):
            raise NutritionProfileError("numeric_range", "Record sums exceed supported range")
    return {"schema_version": "NutritionCoverageV1", "nutrients": result}
