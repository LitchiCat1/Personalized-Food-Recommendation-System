"""Verify one offline replay captured from the USDA FoodData Central API."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.fooddata_central_adapter import RETRIEVAL_VERSION, build_reviewed_fooddata_central_source
from services.nutrition_evidence_service import NUTRIENTS, validate_and_build_nutrition_profiles
from services.nutrition_profile_service import calculate_portion


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _selected_nutrients(payload):
    numbers = {"calories": "957", "protein": "203", "carbs": "205", "fat": "204",
               "sodium": "307", "fiber": "291", "sugar": "269"}
    rows = {}
    for row in payload.get("foodNutrients", []):
        nutrient = row.get("nutrient") or {}
        number = str(nutrient.get("number", ""))
        for name, preferred in numbers.items():
            if number == preferred:
                rows[name] = {"number": number, "value": row.get("amount"),
                              "unit": nutrient.get("unitName")}
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--comparison-input", type=Path)
    parser.add_argument("--observed-hash", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    source_url = "https://api.nal.usda.gov/fdc/v1/food/" + str(payload["fdcId"])
    identity = {"name": payload["description"], "food_state": "raw", "preparation_method": "mixed",
                "components_scope": "food_only", "brand": None, "variant": None}
    document = {"url": source_url, "payload": payload,
                "content_hash": hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest(),
                "retrieved_at": "2026-11-14T00:00:00+08:00", "retrieval_version": RETRIEVAL_VERSION}
    spec = {"source_id": "usda-fdc-" + str(payload["fdcId"]), "source_url": source_url,
            "adapter_version": "usda-fdc-json-v1", "table_id": "fdc-" + str(payload["fdcId"]) + "-per-100g",
            "food_identity": identity, "preferred_energy_number": "957",
            "preferred_nutrient_numbers": {"carbs": "205", "sugar": "269"}}
    source = build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["probe-item"])
    table = source["tables"][0]
    selected = {nutrient: ({"row_id": "fdc-" + nutrient} if "fdc-" + nutrient in table["rows"] else None)
                for nutrient in NUTRIENTS}
    profile = validate_and_build_nutrition_profiles(
        {"schema_version": "NutritionExtractionV1", "items": [{
            "item_id": "probe-item", "status": "candidate", "source_id": source["source_id"],
            "table_id": table["table_id"], "column_id": "per_100g_kcal", "nutrients": selected,
        }]},
        expected_items=[{"item_id": "probe-item", **{key: identity[key] for key in
                         ("food_state", "preparation_method", "components_scope", "brand", "variant")}}],
        source_blocks=[source],
    )[0]["nutrition_profile"]
    portion = calculate_portion(profile, 150, portion_source="vision_estimate")
    comparison = None
    if args.comparison_input is not None:
        other = json.loads(args.comparison_input.read_text(encoding="utf-8-sig"))
        other_hash = hashlib.sha256(_canonical(other).encode("utf-8")).hexdigest()
        identity_fields = ("fdcId", "description", "dataType")
        comparison = {
            "payload_sha256": other_hash,
            "payload_hash_equal": other_hash == document["content_hash"],
            "food_identity_equal": all(other.get(field) == payload.get(field) for field in identity_fields),
            "food_nutrient_row_count_equal": len(other.get("foodNutrients", [])) == len(payload["foodNutrients"]),
            "selected_nutrients_equal": _selected_nutrients(other) == _selected_nutrients(payload),
            "selected_nutrients": _selected_nutrients(other),
        }
        changed_metadata_rows = []
        for index, (left, right) in enumerate(zip(payload.get("foodNutrients", []), other.get("foodNutrients", []))):
            changed = [key for key in sorted(set(left) | set(right)) if left.get(key) != right.get(key)]
            if changed:
                changed_metadata_rows.append({"index": index, "changed_keys": changed})
        comparison["changed_rows"] = changed_metadata_rows
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "live_usda_fdc_api_payload_replayed_offline",
        "replay_count": 1 + (1 if comparison is not None else 0),
        "fdc_id": payload["fdcId"], "description": payload["description"],
        "data_type": payload["dataType"], "food_nutrient_rows": len(payload["foodNutrients"]),
        "payload_sha256": document["content_hash"], "source_url": source_url,
        "adapter_version": source["adapter_version"], "selected_rows": sorted(table["rows"]),
        "selected_nutrients": _selected_nutrients(payload),
        "per_100g": profile["per_100g"],
        "portion_150g": {"values": portion["values"],
                          "missing_nutrition_fields": portion["missing_nutrition_fields"]},
        "comparison": comparison,
        "observed_payload_hashes": sorted(set(args.observed_hash) | {document["content_hash"]}),
        "observed_hash_variant_count": len(set(args.observed_hash) | {document["content_hash"]}),
        "hash_policy": "per_retrieval_provenance_only; compare food identity and selected nutrient values separately",
        "profile_fields_with_values": sorted(key for key, value in profile["per_100g"].items() if value is not None),
        "profile_fields_null": sorted(key for key, value in profile["per_100g"].items() if value is None),
        "validated": True,
        "limitations": ["Captured with a server-side USDA API key; the key is not persisted in this report",
                        "No production registry policy or user record was changed",
                        "Food identity and preparation compatibility remain server-review responsibilities"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("fdc_id", "data_type", "selected_rows", "validated")}))


if __name__ == "__main__":
    main()
