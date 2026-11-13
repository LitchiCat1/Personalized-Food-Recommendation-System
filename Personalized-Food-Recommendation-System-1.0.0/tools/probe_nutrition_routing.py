"""Reproduce local nutrition routing gaps without network or user databases."""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.nutrition_database_service import load_usda_foods, NutritionDatasetUnavailable
from services.food_service import build_custom_food_doc
from services.nutrition_label_service import (
    build_custom_food_search_result, extract_number, normalize_nutrition_payload,
    scale_nutrition_per_100g,
)
from services.vision_nutrition_service import find_vision_food_matches, food_identity


class Storage:
    def __init__(self, foods=()):
        self.foods = list(foods)

    def get_custom_foods(self, _user_id):
        return self.foods


def match(database, name, storage=None, user_id=None, **fields):
    return find_vision_food_matches(
        storage or Storage(), database, {"name_zh": name, **fields},
        user_id, build_custom_food_search_result,
    )


def summarize(matches):
    return [{key: row.get(key) for key in
             ("key", "name_zh", "source", "unit", "calories", "sodium", "match_notes")}
            for row in matches]


def profile(**fields):
    return dict(name_zh="routing-probe", source="TFDA", unit="per 100g",
                calories=100, protein=5, fat=2, carbs=15, sodium=20, **fields)


def main():
    tfda_path = ROOT / "backend/nutrition_db_tw.json"
    usda_path = ROOT / "backend/nutrition_db_usda.json"
    tfda = json.loads(tfda_path.read_text(encoding="utf-8"))
    usda = load_usda_foods(ROOT / "backend")
    database = dict(tfda, **usda)
    chinese = re.compile(r"[\u3400-\u9fff]")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_repaired_local_routing",
        "network_calls": 0,
        "production_code_modified": True,
        "limits": ["Synthetic inputs demonstrate missing guards, not production incidence.",
                   "No third-layer implementation or end-to-end intake accuracy tested."],
        "database_sha256_lf": {
            path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for path in (tfda_path, usda_path)
        },
        "inventory": {
            "tfda_count": len(tfda), "usda_count": len(usda),
            "usda_chinese_name_count": sum(bool(chinese.search(row["name_zh"])) for row in usda.values()),
            "usda_chinese_alias_count": sum(any(chinese.search(alias) for alias in row.get("aliases", [])) for row in usda.values()),
        },
    }

    report["state_and_scope"] = []
    for name, fields in [
        ("泡麵", {"food_state": "dry"}),
        ("泡麵", {"food_state": "prepared", "components_scope": "noodles_only"}),
        ("泡麵", {"food_state": "prepared", "components_scope": "whole_dish_with_broth"}),
        ("白飯", {"food_state": "raw"}),
        ("炒高麗菜", {"food_state": "prepared"}),
        ("水餃(韭菜)", {"food_state": "prepared"}),
    ]:
        report["state_and_scope"].append({
            "name": name, "input": fields, "identity": food_identity(name),
            "matches": summarize(match(database, name, **fields)),
        })

    custom = {
        "food_id": "routing-custom", "name_zh": "白飯", "unit": "per 100g",
        "nutrition_per_100g": {"calories": 123, "protein": 2, "fat": 1, "carbs": 25, "sodium": 10},
    }
    report["custom_order"] = summarize(match(database, "白飯", Storage([custom]), "isolated-user"))
    per_serving = {"calories": 400, "protein": 10, "fat": 10, "carbs": 60, "sodium": 600}
    custom_doc = build_custom_food_doc(
        {"name_zh": "routing-custom-basis", "user_id": "isolated-user", "unit": "per serving",
         "serving_size_g": 200, "nutrition_per_serving": per_serving},
        normalize_nutrition_payload, scale_nutrition_per_100g, extract_number,
    )
    report["custom_basis"] = {
        "input_per_serving_calories": 400, "serving_size_g": 200,
        "builder_unit": custom_doc["unit"],
        "builder_per100g_calories": custom_doc["nutrition_per_100g"]["calories"],
        "expected_per100g_calories": 200,
        "matches": summarize(match({}, "routing-custom-basis", Storage([custom_doc]), "isolated-user")),
    }
    report["dry_usda_only"] = summarize(match(usda, "泡麵", food_state="dry"))
    usda_cabbage_key = "usda_fndds:2709891"
    report["cabbage_official_subset"] = summarize(match(
        {"甘藍平均值": tfda["甘藍平均值"], usda_cabbage_key: usda[usda_cabbage_key]},
        "炒高麗菜", food_state="prepared",
    ))
    milk_key = "usda_fndds:2705385"
    report["bilingual_lookup_control"] = {
        "source_key": milk_key, "source_name": usda[milk_key]["name_en"],
        "chinese_plus_exact_english": summarize(match(
            {milk_key: usda[milk_key]}, "全脂牛奶", name_en="Milk, whole", food_state="prepared")),
        "english_name_control": summarize(match({milk_key: usda[milk_key]}, "Milk, whole", food_state="prepared")),
        "limits": "Isolated matching-path control, not permission for automatic translation/equivalence.",
    }

    report["numeric_guards"] = []
    for label, field, value in [
        ("boolean_core", "calories", True), ("negative_core", "calories", -5),
        ("nonfinite_core", "calories", math.nan),
        ("negative_serving", "serving_size_g", -100),
        ("boolean_serving", "serving_size_g", True),
        ("nonnumeric_serving", "serving_size_g", "bad"),
    ]:
        food = profile()
        food[field] = value
        if field == "serving_size_g":
            food["unit"] = "per serving"
        try:
            rows = match({"probe": food}, "routing-probe")
            chosen = rows[0] if rows else {}
            report["numeric_guards"].append({
                "case": label, "accepted": bool(rows),
                "calories_repr": repr(chosen.get("calories")),
                "finite_calories": math.isfinite(chosen["calories"]) if rows else None,
            })
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            report["numeric_guards"].append({"case": label, "exception": type(exc).__name__})

    with tempfile.TemporaryDirectory() as directory:
        try:
            report["missing_usda_file"] = {"loader_result": load_usda_foods(directory),
                                           "raises": False, "explicit_unavailable_status": False}
        except NutritionDatasetUnavailable as error:
            report["missing_usda_file"] = {"raises": True, "explicit_unavailable_status": True,
                                           "health": error.health}

    report["actual_data_invalid_core_count"] = sum(
        any(isinstance(row.get(field), bool) or
            (isinstance(row.get(field), (int, float)) and
             (not math.isfinite(row[field]) or row[field] < 0))
            for field in ("calories", "protein", "fat", "carbs", "sodium"))
        for row in database.values()
    )
    audit_path = ROOT / "docs/food-nutrition-evaluation/2026-11-13/vision-original.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not isinstance(audit.get("results"), list):
        raise ValueError("Unexpected prior vision evidence shape")
    report["historical_unmatched_payload_observation"] = []
    for row in audit["results"]:
        parsed_items = row.get("parsed", {}).get("items", [])
        for rejected in row.get("response", {}).get("rejected_detections", []):
            if rejected.get("nutrition_status") != "unmatched":
                continue
            originals = [item for item in parsed_items if item.get("name_zh") == rejected.get("label")]
            report["historical_unmatched_payload_observation"].append({
                "filename": row["filename"], "repeat": row.get("repeat"), "label": rejected["label"],
                "original_item_count": len(originals),
                "original_has_weight": any(item.get("estimated_weight_g") is not None for item in originals),
                "response_has_weight": "estimated_weight_g" in rejected,
                "response_has_food_state": "food_state" in rejected,
                "response_has_item_id": "item_id" in rejected,
            })
            break
        if len(report["historical_unmatched_payload_observation"]) >= 3:
            break
    output = ROOT / "docs/food-nutrition-evaluation/2026-11-13/routing-repaired.json"
    output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.relative_to(ROOT)), "inventory": report["inventory"],
                      "numeric_guards": report["numeric_guards"],
                      "actual_data_invalid_core_count": report["actual_data_invalid_core_count"]}, ensure_ascii=True))


if __name__ == "__main__":
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")), \
            patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network forbidden")), \
            patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")):
        main()
