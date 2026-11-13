"""Import official USDA FNDDS 2021-2023 JSON; preserve per-100g values and IDs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile


DOWNLOAD_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_survey_food_json_2024-10-31.zip"
NUTRIENTS = {
    1008: ("calories", "kcal"), 1003: ("protein", "g"), 1004: ("fat", "g"),
    1005: ("carbs", "g"), 1093: ("sodium", "mg"), 1079: ("fiber", "g"),
    2000: ("sugar", "g"), 1258: ("saturated_fat", "g"), 1257: ("trans_fat", "g"),
    1051: ("water", "g"),
}

# Translations/reference links only. Nutrition is copied from the official record.
# These are generic US preparations, not measurements of a Taiwanese recipe.
LOCAL_NAMES = {
    2705901: ("熟五花肉（USDA參考）", ["滷肉", "滷五花肉", "滷豬肉", "控肉", "焢肉", "五花肉塊"]),
    2705849: ("燉牛肉（USDA參考）", ["滷牛腱", "紅燒牛肉", "燉牛肉", "牛腱", "牛肉塊"]),
    2705984: ("烤雞腿帶皮（USDA參考）", ["烤雞腿", "烤全雞腿"]),
    2705988: ("燉雞腿帶皮（USDA參考）", ["滷雞腿", "滷全雞腿"]),
    2706002: ("烤棒棒腿帶皮（USDA參考）", ["烤棒棒腿"]),
    2706014: ("燉棒棒腿帶皮（USDA參考）", ["滷棒棒腿"]),
    2708352: ("熟麵條（USDA參考）", ["熟麵條", "白麵條", "陽春麵條", "細麵條"]),
    2709152: ("沖泡泡麵含湯（USDA參考）", ["泡麵", "杯麵", "速食麵", "沖泡泡麵"]),
    2709891: ("炒高麗菜（USDA參考）", ["炒高麗菜", "清炒高麗菜"]),
    2709930: ("熟茄子加油（USDA參考）", ["炒茄子", "紅燒茄子", "醬燒茄子"]),
    2709949: ("熟萵苣（USDA參考）", ["炒大陸妹", "炒萵苣", "炒A菜", "炒福山萵苣"]),
    2707872: ("奶油蛋糕（USDA參考）", ["鮮奶油蛋糕", "奶油蛋糕"]),
}


def convert_foods(foods):
    result = {}
    for food in foods:
        nutrients = {}
        for item in food.get("foodNutrients", []):
            definition = item.get("nutrient", {})
            target = NUTRIENTS.get(definition.get("id"))
            if target and item.get("amount") is not None:
                if definition.get("unitName", "").lower() != target[1].lower():
                    raise ValueError(f"Unexpected nutrient unit for FDC {food['fdcId']}")
                nutrients[target[0]] = item["amount"]
        if not all(field in nutrients for field in ("calories", "protein", "fat", "carbs", "sodium")):
            continue
        fdc_id = food["fdcId"]
        name, aliases = LOCAL_NAMES.get(fdc_id, (food["description"], []))
        result[f"usda_fndds:{fdc_id}"] = {
            "code": str(fdc_id), "fdc_id": fdc_id, "food_code": food.get("foodCode"),
            "name_zh": name, "name_en": food["description"], "aliases": aliases,
            "category": food.get("wweiaFoodCategory", {}).get("wweiaFoodCategoryDescription", ""),
            "description": food["description"], "unit": "per 100g", "source": "USDA FNDDS",
            "source_url": f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients",
            "reference_only": True, "publication_date": food.get("publicationDate"), **nutrients,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "nutrition_db_usda.json")
    args = parser.parse_args()
    with zipfile.ZipFile(args.raw) as archive:
        foods = json.loads(archive.read("surveyDownload.json"))["SurveyFoods"]
    converted = convert_foods(foods)
    args.output.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.with_suffix(".source.json").write_text(json.dumps({
        "provider": "USDA Agricultural Research Service", "dataset": "FNDDS 2021-2023",
        "download_url": DOWNLOAD_URL, "dataset_url": "https://fdc.nal.usda.gov/download-datasets/",
        "license": "Public domain (US government data)",
        "converted_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": hashlib.sha256(args.raw.read_bytes()).hexdigest(),
        "raw_foods": len(foods), "output_foods": len(converted),
        "skipped": "Records without all five core nutrients are excluded; missing values are not invented.",
        "local_names": "Manually mapped translations/reference preparations; not Taiwanese recipe measurements.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Imported {len(converted)} official USDA FNDDS foods; excluded {len(foods) - len(converted)} without core nutrient data")


if __name__ == "__main__":
    main()
