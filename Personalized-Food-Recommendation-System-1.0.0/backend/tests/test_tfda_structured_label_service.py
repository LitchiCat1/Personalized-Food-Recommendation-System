from hashlib import sha256
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from services.nutrition_profile_service import NutritionProfileError
from services.tfda_structured_label_service import (
    TFDA_STRUCTURED_LABEL_DATASET_NAME,
    TFDA_STRUCTURED_LABEL_SOURCE_URL,
    build_reviewed_tfda_package_preview,
    build_tfda_label_profile,
    read_tfda_label_export,
)


IDENTITY = {
    "trace_code": "B-112981393-00000-5-09040000-0000000001",
    "publisher": "笠豐食品有限公司",
    "product_name": "小太陽餅",
}


def label_row():
    return {
        "產品追溯系統串接碼": IDENTITY["trace_code"],
        "公司名稱": IDENTITY["publisher"],
        "產品名稱": IDENTITY["product_name"],
        "有效起始日": "2021/11/01",
        "每一份量": "22公克",
        "每份熱量": "107.2大卡",
        "每份蛋白質": "1.1公克",
        "每份脂肪": "5.3公克",
        "每份飽和脂肪": "3.9公克",
        "每份反式脂肪": "0.15公克",
        "每份碳水化合物": "13.9公克",
        "每份糖": "4.1公克",
        "每份鈉": "10毫克",
        "每100公克熱量": "487.2大卡",
        "每100公克蛋白質": "4.8公克",
        "每100公克脂肪": "24公克",
        "每100公克飽和脂肪": "17.6公克",
        "每100公克反式脂肪": "0.67公克",
        "每100公克碳水化合物": "63公克",
        "每100公克糖": "18.6公克",
        "每100公克鈉": "47毫克",
    }


class TfdaStructuredLabelTests(unittest.TestCase):
    def reviewed_package(self, row):
        photo = b"reviewed package photo bytes"
        row_bytes = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                               allow_nan=False).encode("utf-8")
        review = dict(IDENTITY, reviewed_photo_sha256=sha256(photo).hexdigest(),
                      reviewed_row_sha256=sha256(row_bytes).hexdigest())
        return photo, review

    def test_exact_reviewed_package_returns_only_historical_profile(self):
        row = label_row()
        photo, review = self.reviewed_package(row)
        reordered = dict(reversed(list(row.items())))
        other_product_version = dict(row, 產品追溯系統串接碼="B-112981393-00001-6-09040000-0000000009")
        preview = build_reviewed_tfda_package_preview([other_product_version, reordered], photo, **review)
        self.assertEqual(set(preview), {"status", "nutrition_profile"})
        self.assertEqual(preview["status"], "historical_preview_only")
        self.assertEqual(preview["nutrition_profile"], build_tfda_label_profile([row], **IDENTITY))
        self.assertIsNone(preview["nutrition_profile"]["per_100g"]["fiber"])

    def test_package_preview_rejects_different_photo_and_malformed_review(self):
        row = label_row()
        photo, review = self.reviewed_package(row)
        for content, evidence, code in (
            (photo + b"modified", review, "identity_mismatch"),
            (b"", review, "identity_mismatch"),
            (bytearray(photo), review, "identity_mismatch"),
            (photo, dict(review, reviewed_photo_sha256="a" * 63), "invalid_identity"),
            (photo, dict(review, reviewed_row_sha256=None), "invalid_identity"),
        ):
            with self.subTest(code=code), self.assertRaises(NutritionProfileError) as raised:
                build_reviewed_tfda_package_preview([row], content, **evidence)
            self.assertEqual(raised.exception.code, code)

    def test_exact_package_photo_cannot_admit_changed_label_or_ambiguous_identity(self):
        row = label_row()
        photo, review = self.reviewed_package(row)
        for rows, evidence, code in (
            ([dict(row, 有效起始日="2021/11/02")], review, "source_conflict"),
            ([dict(row, 每100公克鈉="48毫克")], review, "source_conflict"),
            ([dict(row, 產品名稱="太陽餅")], review, "source_conflict"),
            ([row, row], review, "source_conflict"),
            ([row], dict(review, publisher="另一家公司"), "source_conflict"),
            ([], review, "not_found"),
        ):
            with self.subTest(code=code), self.assertRaises(NutritionProfileError) as raised:
                build_reviewed_tfda_package_preview(rows, photo, **evidence)
            self.assertEqual(raised.exception.code, code)

    def test_reviewed_hash_does_not_bypass_label_validation(self):
        row = dict(label_row(), 每100公克蛋白質="")
        photo, review = self.reviewed_package(row)
        with self.assertRaises(NutritionProfileError) as raised:
            build_reviewed_tfda_package_preview([row], photo, **review)
        self.assertEqual(raised.exception.code, "incomplete_core")

    def test_reads_official_zip_shape_and_rejects_unexpected_entries(self):
        def archive(*members):
            output = BytesIO()
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
                for name, content in members:
                    bundle.writestr(name, content)
            return output.getvalue()

        raw = json.dumps([label_row()], ensure_ascii=False)
        valid = archive(("188_5.json", raw))
        self.assertEqual(read_tfda_label_export(valid), [label_row()])
        for invalid in (
            b"not a ZIP",
            archive(("../188_5.json", raw)),
            archive(("188_5.json", raw), ("extra.json", "[]")),
            archive(("188_5.json", '[{"product":"one","product":"two"}]')),
        ):
            with self.subTest(invalid=invalid[:30]), self.assertRaises(NutritionProfileError) as raised:
                read_tfda_label_export(invalid)
            self.assertEqual(raised.exception.code, "invalid_document")
        with patch("services.tfda_structured_label_service._MAX_DOCUMENT_BYTES", 8):
            with self.assertRaises(NutritionProfileError):
                read_tfda_label_export(valid)

    def test_uses_reviewed_trace_and_keeps_original_cells(self):
        row = label_row()
        other = dict(row, 產品追溯系統串接碼="B-112981393-00001-6-09040000-0000000009")
        profile = build_tfda_label_profile([other, row], **IDENTITY)
        self.assertEqual(profile["per_100g"]["calories"], 487.2)
        self.assertEqual(profile["per_100g"]["protein"], 4.8)
        self.assertEqual(profile["per_100g"]["sodium"], 47)
        self.assertIsNone(profile["per_100g"]["fiber"])
        self.assertEqual(profile["source_nutrients"]["sodium"]["evidence"],
                         {"field": "每100公克鈉", "raw": "47毫克"})
        self.assertEqual(profile["source_details"], {
            "source_url": TFDA_STRUCTURED_LABEL_SOURCE_URL,
            "manufacturer_label": dict(IDENTITY, dataset_name=TFDA_STRUCTURED_LABEL_DATASET_NAME),
            "effective_date": "2021-11-01",
        })

    def test_rejects_wrong_or_duplicate_identity(self):
        row = label_row()
        for rows, identity, code in (
            ([row, row], IDENTITY, "source_conflict"),
            ([], IDENTITY, "not_found"),
            ([row], dict(IDENTITY, publisher="另一家食品"), "source_conflict"),
            ([row], dict(IDENTITY, product_name="太陽餅"), "source_conflict"),
            ([row], dict(IDENTITY, trace_code=""), "invalid_identity"),
        ):
            with self.subTest(code=code), self.assertRaises(NutritionProfileError) as raised:
                build_tfda_label_profile(rows, **identity)
            self.assertEqual(raised.exception.code, code)

    def test_rejects_unverified_core_and_incompatible_bases(self):
        for key, value, code in (
            ("每100公克蛋白質", "7.公克", "invalid_measurement"),
            ("每100公克蛋白質", "", "incomplete_core"),
            ("每100公克熱量", "487.2毫克", "invalid_measurement"),
            ("每一份量", "22毫升", "invalid_basis"),
            ("每份熱量", "60大卡", "source_conflict"),
            ("有效起始日", "2021/02/29", "invalid_document"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(NutritionProfileError) as raised:
                build_tfda_label_profile([dict(label_row(), **{key: value})], **IDENTITY)
            self.assertEqual(raised.exception.code, code)

    def test_explicit_upper_bound_and_zero_are_distinct_from_missing(self):
        override = {"每份反式脂肪": "", "每100公克反式脂肪": "<0.67公克",
                    "每份糖": "0公克", "每100公克糖": "0公克"}
        profile = build_tfda_label_profile([dict(label_row(), **override)], **IDENTITY)
        self.assertEqual(profile["upper_bounds_per_100g"]["trans_fat"], 0.67)
        self.assertEqual(profile["per_100g"]["sugar"], 0)
        self.assertIsNone(profile["per_100g"]["fiber"])
