import hashlib
import json
import unittest
from copy import deepcopy

from services.fooddata_central_adapter import RETRIEVAL_VERSION
from services.fdc_detail_profile_service import (
    FdcDetailProfileError,
    build_fdc_detail_profile,
)


IDENTITY = {
    "name": "Apples, raw, with skin", "food_state": "raw",
    "preparation_method": "mixed", "components_scope": "food_only",
    "brand": None, "variant": None,
}

SCAN_IDENTITY = {
    "name_zh": "蘋果", "food_state": "raw",
    "preparation_method": "mixed", "components_scope": "food_only",
    "brand": None, "variant": None,
}


def fixture():
    values = {
        "1008": ("Energy", "kcal", 52.0), "1003": ("Protein", "g", 0.26),
        "1005": ("Carbohydrate", "g", 13.81), "1004": ("Total lipid (fat)", "g", 0.17),
        "1093": ("Sodium, Na", "mg", 1.0), "1079": ("Fiber, total dietary", "g", 2.4),
        "2000": ("Sugars, total", "g", 10.39), "1258": ("Fatty acids, total saturated", "g", 0.028),
        "1257": ("Fatty acids, total trans", "g", 0.0),
    }
    payload = {"fdcId": 171688, "description": IDENTITY["name"], "dataType": "SR Legacy",
               "foodNutrients": [{"nutrient": {"number": number, "name": name, "unitName": unit},
                                   "amount": amount}
                                  for number, (name, unit, amount) in values.items()]}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    document = {"url": "https://api.nal.usda.gov/fdc/v1/food/171688", "payload": payload,
                "content_hash": hashlib.sha256(encoded.encode()).hexdigest(),
                "retrieved_at": "2026-11-14T05:00:00+00:00", "retrieval_version": RETRIEVAL_VERSION}
    spec = {"source_id": "usda-fdc-171688", "source_url": document["url"],
            "adapter_version": "usda-fdc-json-v1", "table_id": "fdc-171688-per-100g",
            "food_identity": deepcopy(IDENTITY)}
    return document, spec


class FdcDetailProfileServiceTests(unittest.TestCase):
    def test_builds_profile_and_portion_from_original_per_100g_cells(self):
        document, spec = fixture()
        result = build_fdc_detail_profile(document=document, spec=spec,
                                          confirmed_item_identity=SCAN_IDENTITY,
                                          item_id="item-1", weight_g=150)
        self.assertEqual(result["nutrition_profile"]["basis"], "per_100g")
        self.assertEqual(result["nutrition_profile"]["per_100g"]["calories"], 52.0)
        self.assertEqual(result["portion"]["values"]["calories"], 78.0)
        self.assertEqual(result["portion"]["values"]["sodium"], 1.5)
        self.assertNotIn("confidence", result)
        self.assertEqual(result["source_block"]["source_id"], "usda-fdc-171688")

    def test_unknown_weight_is_rejected_without_defaulting_to_100g(self):
        document, spec = fixture()
        with self.assertRaises(FdcDetailProfileError) as caught:
            build_fdc_detail_profile(document=document, spec=spec,
                                     confirmed_item_identity=SCAN_IDENTITY,
                                     item_id="item-1", weight_g=None)
        self.assertEqual(caught.exception.code, "invalid_portion")

    def test_identity_mismatch_is_rejected_before_profile_build(self):
        document, spec = fixture()
        changed = dict(SCAN_IDENTITY, food_state="prepared")
        with self.assertRaises(FdcDetailProfileError) as caught:
            build_fdc_detail_profile(document=document, spec=spec,
                                     confirmed_item_identity=changed,
                                     item_id="item-1", weight_g=100)
        self.assertEqual(caught.exception.code, "identity_mismatch")

    def test_missing_core_nutrient_is_rejected(self):
        document, spec = fixture()
        document["payload"]["foodNutrients"] = [row for row in document["payload"]["foodNutrients"]
                                                  if row["nutrient"]["number"] != "1003"]
        encoded = json.dumps(document["payload"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        document["content_hash"] = hashlib.sha256(encoded.encode()).hexdigest()
        with self.assertRaises(FdcDetailProfileError) as caught:
            build_fdc_detail_profile(document=document, spec=spec,
                                     confirmed_item_identity=SCAN_IDENTITY,
                                     item_id="item-1", weight_g=100)
        self.assertEqual(caught.exception.code, "missing_core")

    def test_different_scan_language_is_retained_separately_from_fdc_source_name(self):
        document, spec = fixture()
        result = build_fdc_detail_profile(document=document, spec=spec,
                                          confirmed_item_identity=SCAN_IDENTITY,
                                          item_id="item-1", weight_g=100)
        self.assertEqual(result["recognition_identity"]["name_zh"], "蘋果")
        self.assertEqual(result["source_identity"]["name"], "Apples, raw, with skin")

    def test_brand_and_unknown_state_are_not_wildcards(self):
        document, spec = fixture()
        for changed in (
                dict(SCAN_IDENTITY, brand="Example brand"),
                dict(SCAN_IDENTITY, food_state="unknown"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(FdcDetailProfileError) as caught:
                    build_fdc_detail_profile(document=document, spec=spec,
                                             confirmed_item_identity=changed,
                                             item_id="item-1", weight_g=100)
                self.assertEqual(caught.exception.code, "identity_mismatch")

    def test_raw_or_boiled_bok_choy_cannot_be_relabelled_as_stir_fried(self):
        document, spec = fixture()
        for source_state, source_method, scan_state, scan_method in (
                ("raw", "mixed", "prepared", "stir_fried"),
                ("prepared", "boiled", "prepared", "stir_fried")):
            with self.subTest(source_state=source_state, source_method=source_method):
                identity = {
                    "name": "Cabbage, chinese (pak-choi)",
                    "food_state": source_state,
                    "preparation_method": source_method,
                    "components_scope": "food_only",
                    "brand": None,
                    "variant": None,
                }
                bok_choy_spec = {**spec, "food_identity": identity}
                scan_identity = {
                    "name_zh": "青江菜",
                    "food_state": scan_state,
                    "preparation_method": scan_method,
                    "components_scope": "food_only",
                    "brand": None,
                    "variant": None,
                }
                with self.assertRaises(FdcDetailProfileError) as caught:
                    build_fdc_detail_profile(
                        document=document, spec=bok_choy_spec,
                        confirmed_item_identity=scan_identity,
                        item_id="item-1", weight_g=100,
                    )
                self.assertEqual(caught.exception.code, "identity_mismatch")


if __name__ == "__main__":
    unittest.main()
