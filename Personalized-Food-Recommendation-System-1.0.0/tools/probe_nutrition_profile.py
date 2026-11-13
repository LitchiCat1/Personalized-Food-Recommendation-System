"""Replay profile/coverage contracts offline, without AI or user databases."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.nutrition_database_service import load_official_nutrition_dataset
from services.nutrition_profile_service import (
    NUTRIENTS, UNITS, NutritionProfileError, aggregate_nutrition_coverage,
    build_nutrition_profile, calculate_portion, profile_from_local_food,
)


def nutrients(**values):
    return {field: None if values.get(field) is None else {
        "value": values[field], "unit": UNITS[field], "comparison": "exact",
    } for field in NUTRIENTS}


def main():
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_profile_contracts", "network_calls": 0,
        "production_partial_profiles_enabled": False,
        "limits": ["No real source adapters, image calls, persistence or medical-risk integration.",
                   "Synthetic examples and consistency inventory are not accuracy measurements.",
                   "Existing production lookup policy is unchanged by this pure-service stage."],
    }
    official = {}
    for source in ("TFDA", "USDA FNDDS"):
        dataset = load_official_nutrition_dataset(ROOT / "backend", source)
        counts, conflicts, warnings, missing_fields = Counter(), [], Counter(), Counter()
        for key, food in dataset["foods"].items():
            missing_fields.update(field for field in NUTRIENTS if food.get(field) is None)
            try:
                profile = profile_from_local_food(food)
                counts[profile["nutrition_status"]] += 1
                warnings.update(profile["validation_warnings"])
            except NutritionProfileError as error:
                counts[error.code] += 1
                conflicts.append({"key": key, "name": food["name_zh"], "food_code": food.get("code"),
                                  "code": error.code, "reason": str(error),
                                  "snapshot_nutrients": {field: food.get(field) for field in NUTRIENTS}})
        official[source] = {"dataset_health": dataset["health"], "profile_results": dict(counts),
                            "warning_counts": dict(warnings), "snapshot_missing_fields": dict(missing_fields),
                            "source_consistency_review": conflicts}
    report["official_snapshot_consistency_inventory"] = official
    serving = build_nutrition_profile(nutrients(calories=400, protein=20, carbs=40, fat=10, sodium=600),
                                      basis="per_serving", basis_weight_g=200)
    report["serving_to_100g_to_intake"] = {"per_100g": serving["per_100g"],
                                         "portion": calculate_portion(serving, 150, portion_source="user_weighed")}
    bound_raw = nutrients(sodium=None)
    bound_raw["sodium"] = {"value": "0.1", "unit": "g", "comparison": "less_than"}
    bounded = build_nutrition_profile(bound_raw, basis="per_100g")
    entries = [{"item_id": "known", "profile": serving, "weight_g": 100},
               {"item_id": "bounded", "profile": bounded, "weight_g": 100}]
    report["known_plus_bound"] = aggregate_nutrition_coverage(entries)["nutrients"]["sodium"]
    report["unknown_item_removes_total_upper_bound"] = aggregate_nutrition_coverage(
        [*entries, {"item_id": "unresolved", "profile": None, "weight_g": None}])["nutrients"]["sodium"]
    report["unknown_weight"] = calculate_portion(serving, None)
    target = ROOT / "docs/food-nutrition-evaluation/2026-11-13/profile-contracts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "official_profile_counts": {
        source: data["profile_results"] for source, data in official.items()}}, ensure_ascii=True))


if __name__ == "__main__":
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network prohibited in offline profile probe")):
        main()
