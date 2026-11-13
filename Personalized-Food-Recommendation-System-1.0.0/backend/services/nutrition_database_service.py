"""Offline official nutrition data, also usable by the photo evaluation script."""

import json
import hashlib
import math
from pathlib import Path


CORE_NUTRIENTS = ("calories", "protein", "carbs", "fat", "sodium")
OPTIONAL_NUTRIENTS = ("fiber", "sugar", "saturated_fat", "trans_fat")
DATASET_FILES = {"TFDA": "nutrition_db_tw.json", "USDA FNDDS": "nutrition_db_usda.json"}


class NutritionDatasetUnavailable(ValueError):
    """A local dataset cannot be used; this is distinct from a food lookup miss."""

    def __init__(self, health):
        self.health = health
        super().__init__(f"{health['source']} nutrition dataset unavailable: {health['reason']}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Nonfinite JSON number")


def _valid_profile(key, food, source):
    if not isinstance(key, str) or not key.strip() or not isinstance(food, dict):
        return False
    if not isinstance(food.get("name_zh"), str) or not food["name_zh"].strip():
        return False
    if food.get("source") != source or food.get("unit") != "per 100g":
        return False
    aliases = food.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
        return False
    if any(field not in food for field in CORE_NUTRIENTS):
        return False
    # Null is an explicit missing observation, not a malformed database. Matching
    # must still reject a profile missing core values rather than inventing zero.
    for field in CORE_NUTRIENTS + OPTIONAL_NUTRIENTS:
        value = food.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                return False
            try:
                if not math.isfinite(value):
                    return False
            except OverflowError:
                return False
    return True


def load_official_nutrition_dataset(base_dir, source, *, expected_sha256=None):
    """Load one official layer independently, with explicit health and identity.

    The existing source manifests hash their *input* archives, so that hash must
    never be presented as verification of these converted JSON files.
    """
    filename = DATASET_FILES[source]
    health = {
        "source": source,
        "status": "unavailable",
        "reason": None,
        "record_count": 0,
        "incomplete_core_profiles": 0,
        "sha256": None,
        "hash_verification": "not_configured" if expected_sha256 is None else "pending",
        "validation_schema_version": 1,
    }

    def unavailable(reason):
        health["reason"] = reason
        return {"foods": {}, "health": health}

    try:
        raw = (Path(base_dir) / filename).read_bytes()
    except FileNotFoundError:
        return unavailable("missing_file")
    except OSError:
        return unavailable("read_error")
    health["sha256"] = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if health["sha256"] != expected_sha256:
            health["hash_verification"] = "mismatch"
            return unavailable("checksum_mismatch")
        health["hash_verification"] = "verified"
    try:
        foods = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return unavailable("invalid_json")
    if not isinstance(foods, dict) or not foods:
        return unavailable("invalid_shape")
    if not all(_valid_profile(key, food, source) for key, food in foods.items()):
        return unavailable("invalid_profile")
    health.update(status="available", record_count=len(foods),
                  incomplete_core_profiles=sum(any(food[field] is None for field in CORE_NUTRIENTS)
                                               for food in foods.values()))
    return {"foods": foods, "health": health}


def build_nutrition_dataset_context(health):
    available = all(health.get(source, {}).get("status") == "available" for source in DATASET_FILES)
    return {
        "nutrition_dataset_health": health,
        "official_layers_available": available,
        "automatic_web_fallback_enabled": False,
        "web_fallback_block_reason": "feature_not_enabled" if available else "official_dataset_unavailable",
    }


def load_usda_foods(base_dir):
    result = load_official_nutrition_dataset(base_dir, "USDA FNDDS")
    if result["health"]["status"] != "available":
        raise NutritionDatasetUnavailable(result["health"])
    return result["foods"]
