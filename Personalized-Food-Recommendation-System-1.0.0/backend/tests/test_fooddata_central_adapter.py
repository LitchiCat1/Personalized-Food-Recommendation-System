import hashlib
import json
import unittest
from copy import deepcopy

from services.fooddata_central_adapter import (
    RETRIEVAL_VERSION, FoodDataCentralAdapterError, build_reviewed_fooddata_central_source,
)
from services.nutrition_evidence_service import NUTRIENTS, validate_and_build_nutrition_profiles
from services.nutrition_profile_service import calculate_portion


IDENTITY = {
    "name": "Apples, raw, with skin",
    "food_state": "raw", "preparation_method": "mixed", "components_scope": "food_only",
    "brand": None, "variant": None,
}


def fixture():
    values = {
        "1008": ("Energy", "kcal", 52.0), "1062": ("Energy", "kJ", 218.0),
        "1003": ("Protein", "g", 0.26), "1005": ("Carbohydrate", "g", 13.81),
        "1004": ("Total lipid (fat)", "g", 0.17), "1093": ("Sodium, Na", "mg", 1.0),
        "1079": ("Fiber, total dietary", "g", 2.4), "2000": ("Sugars, total", "g", 10.39),
        "1258": ("Fatty acids, total saturated", "g", 0.028),
        "1257": ("Fatty acids, total trans", "g", 0.0),
    }
    rows = []
    for number, (name, unit, amount) in values.items():
        rows.append({"nutrient": {"number": number, "name": name, "unitName": unit}, "amount": amount})
    payload = {"fdcId": 171688, "description": IDENTITY["name"], "dataType": "SR Legacy",
               "foodNutrients": rows}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    document = {"url": "https://api.nal.usda.gov/fdc/v1/food/171688", "payload": payload,
                "content_hash": hashlib.sha256(encoded.encode()).hexdigest(),
                "retrieved_at": "2026-11-14T05:00:00+00:00", "retrieval_version": RETRIEVAL_VERSION}
    spec = {"source_id": "usda-fdc-171688", "source_url": document["url"],
            "adapter_version": "usda-fdc-json-v1", "table_id": "fdc-171688-per-100g",
            "food_identity": deepcopy(IDENTITY)}
    return payload, document, spec


def refresh_hash(document):
    encoded = json.dumps(document["payload"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    document["content_hash"] = hashlib.sha256(encoded.encode()).hexdigest()


class FoodDataCentralAdapterTests(unittest.TestCase):
    def test_builds_structured_source_and_preserves_both_energy_units(self):
        _payload, document, spec = fixture()
        source = build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        table = source["tables"][0]
        self.assertEqual(set(table["columns"]), {"per_100g_kcal", "per_100g_kj"})
        self.assertEqual(table["rows"]["fdc-calories"]["cells"]["per_100g_kcal"]["raw_value"], "52.0")
        self.assertEqual(table["rows"]["fdc-calories"]["cells"]["per_100g_kj"]["unit"], "kJ")
        self.assertTrue(source["reusable"])

    def test_source_round_trips_through_evidence_and_profile_validation(self):
        _payload, document, spec = fixture()
        source = build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        rows = source["tables"][0]["rows"]
        nutrient_selection = {}
        for nutrient in NUTRIENTS:
            row_id = "fdc-" + nutrient
            nutrient_selection[nutrient] = {"row_id": row_id} if row_id in rows else None
        payload = {"schema_version": "NutritionExtractionV1", "items": [{
            "item_id": "item-1", "status": "candidate", "source_id": source["source_id"],
            "table_id": source["tables"][0]["table_id"], "column_id": "per_100g_kcal",
            "nutrients": nutrient_selection,
        }]}
        result = validate_and_build_nutrition_profiles(payload, expected_items=[{
            "item_id": "item-1", "food_state": "raw", "preparation_method": "mixed",
            "components_scope": "food_only", "brand": None, "variant": None,
        }], source_blocks=[source])[0]
        self.assertEqual(result["nutrition_profile"]["per_100g"]["calories"], 52.0)
        self.assertEqual(result["nutrition_profile"]["per_100g"]["sodium"], 1.0)

    def test_detail_to_profile_to_portion_replay_uses_per_100g_formula(self):
        _payload, document, spec = fixture()
        source = build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        rows = source["tables"][0]["rows"]
        extraction = {"schema_version": "NutritionExtractionV1", "items": [{
            "item_id": "item-1", "status": "candidate", "source_id": source["source_id"],
            "table_id": source["tables"][0]["table_id"], "column_id": "per_100g_kcal",
            "nutrients": {field: {"row_id": "fdc-" + field} if "fdc-" + field in rows else None
                          for field in NUTRIENTS},
        }]}
        profile = validate_and_build_nutrition_profiles(
            extraction,
            expected_items=[{"item_id": "item-1", "food_state": "raw",
                             "preparation_method": "mixed", "components_scope": "food_only",
                             "brand": None, "variant": None}],
            source_blocks=[source],
        )[0]["nutrition_profile"]
        portion = calculate_portion(profile, 150, portion_source="vision_estimate")
        self.assertEqual(profile["basis"], "per_100g")
        self.assertEqual(profile["per_100g"]["calories"], 52.0)
        self.assertEqual(profile["per_100g"]["sodium"], 1.0)
        self.assertEqual(portion["weight_g"], 150.0)
        self.assertEqual(portion["values"]["calories"], 78.0)
        self.assertEqual(portion["values"]["sodium"], 1.5)
        self.assertAlmostEqual(portion["values"]["protein"], 0.39)
        self.assertEqual(portion["missing_nutrition_fields"], [])

    def test_does_not_treat_branded_serving_label_as_per_100g(self):
        _payload, document, spec = fixture()
        document["payload"]["dataType"] = "Branded"
        refresh_hash(document)
        with self.assertRaises(FoodDataCentralAdapterError) as error:
            build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        self.assertEqual(error.exception.code, "unsupported_data_type")

    def test_identity_and_hash_are_verified(self):
        _payload, document, spec = fixture()
        document["payload"]["description"] = "Other food"
        refresh_hash(document)
        with self.assertRaises(FoodDataCentralAdapterError) as error:
            build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        self.assertEqual(error.exception.code, "identity_mismatch")
        document["payload"]["description"] = IDENTITY["name"]
        document["content_hash"] = "0" * 64
        with self.assertRaises(FoodDataCentralAdapterError) as error:
            build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        self.assertEqual(error.exception.code, "content_hash_mismatch")

    def test_detail_replay_binds_url_id_and_adapter_version(self):
        _payload, document, spec = fixture()
        for changed_spec, changed_document, expected_code in (
                ({**spec, "source_url": "https://api.nal.usda.gov/fdc/v1/food/171689"}, document,
                 "source_mismatch"),
                ({**spec, "adapter_version": "usda-fdc-json-v0"}, document, "invalid_spec"),
                (spec, {**document, "retrieval_version": "fixture-fdc-v0"}, "invalid_provenance"),
                (spec, {**document, "url": "https://api.nal.usda.gov/fdc/v1/food/171689"},
                 "source_mismatch"),
                (spec, {**document, "payload": {**document["payload"], "fdcId": "0171688"}},
                 "invalid_payload"),
        ):
            with self.subTest(expected_code=expected_code):
                changed_document = deepcopy(changed_document)
                if changed_document.get("payload") != document["payload"]:
                    encoded = json.dumps(changed_document["payload"], ensure_ascii=True,
                                         sort_keys=True, separators=(",", ":"))
                    changed_document["content_hash"] = hashlib.sha256(encoded.encode()).hexdigest()
                with self.assertRaises(FoodDataCentralAdapterError) as error:
                    build_reviewed_fooddata_central_source(changed_document, spec=changed_spec,
                                                           eligible_item_ids=["item-1"])
                self.assertEqual(error.exception.code, expected_code)

    def test_duplicate_non_energy_source_numbers_are_rejected(self):
        _payload, document, spec = fixture()
        document["payload"]["foodNutrients"].append({
            "nutrient": {"number": "1063", "name": "Sugars, total", "unitName": "g"}, "amount": 10.39,
        })
        encoded = json.dumps(document["payload"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        document["content_hash"] = hashlib.sha256(encoded.encode()).hexdigest()
        with self.assertRaises(FoodDataCentralAdapterError) as error:
            build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        self.assertEqual(error.exception.code, "ambiguous_nutrient")

    def test_foundation_energy_methods_require_a_reviewed_choice(self):
        _payload, document, spec = fixture()
        document["payload"]["dataType"] = "Foundation"
        document["payload"]["foodNutrients"].append({
            "nutrient": {"number": "957", "name": "Energy (Atwater General Factors)", "unitName": "kcal"},
            "amount": 52.0,
        })
        document["payload"]["foodNutrients"].append({
            "nutrient": {"number": "958", "name": "Energy (Atwater Specific Factors)", "unitName": "kcal"},
            "amount": 50.0,
        })
        encoded = json.dumps(document["payload"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        document["content_hash"] = hashlib.sha256(encoded.encode()).hexdigest()
        with self.assertRaises(FoodDataCentralAdapterError) as error:
            build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        self.assertEqual(error.exception.code, "ambiguous_nutrient")
        spec["preferred_energy_number"] = "957"
        source = build_reviewed_fooddata_central_source(document, spec=spec, eligible_item_ids=["item-1"])
        self.assertEqual(source["tables"][0]["rows"]["fdc-calories"]["cells"]["per_100g_kcal"]["raw_value"], "52.0")


if __name__ == "__main__":
    unittest.main()

