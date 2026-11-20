"""Normalize an explicitly selected row from the TFDA traceability export."""

from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import re
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED
from zlib import error as ZlibError

from services.nutrition_profile_service import (
    NUTRIENTS,
    NutritionProfileError,
    build_nutrition_profile,
    validate_profile_consistency,
)

TFDA_STRUCTURED_LABEL_SOURCE_URL = "https://data.gov.tw/dataset/33575"
TFDA_STRUCTURED_LABEL_DATASET_NAME = "食藥署食品追溯追蹤系統消費者查詢資料集"
_MAX_ROWS = 100_000
_MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
_MAX_DOCUMENT_BYTES = 128 * 1024 * 1024
_MAX_PACKAGE_PHOTO_BYTES = 8 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXPORT_MEMBER = re.compile(r"188_[0-9]{1,4}\.json")
_TRACE = re.compile(r"[A-Z]-[0-9]{9}-[0-9]{5}-[0-9]-[0-9]{8}-[0-9]{10}")
_MASS = re.compile(r"([0-9]{1,12}(?:\.[0-9]{1,12})?)公克")
_CELL = re.compile(r"([<＜])?([0-9]{1,12}(?:\.[0-9]{1,12})?)(大卡|公克|毫克)")
_NUTRIENT_LABELS = {
    "熱量": ("calories", "大卡", "kcal"),
    "蛋白質": ("protein", "公克", "g"),
    "脂肪": ("fat", "公克", "g"),
    "飽和脂肪": ("saturated_fat", "公克", "g"),
    "反式脂肪": ("trans_fat", "公克", "g"),
    "碳水化合物": ("carbs", "公克", "g"),
    "糖": ("sugar", "公克", "g"),
    "鈉": ("sodium", "毫克", "mg"),
}


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON member")
        obj[key] = value
    return obj


def _invalid_json_constant(_value):
    raise ValueError("Non-finite JSON number")


def read_tfda_label_export(archive):
    """Read the sole government JSON entry from a bounded in-memory ZIP."""
    if not isinstance(archive, bytes) or len(archive) > _MAX_ARCHIVE_BYTES:
        raise NutritionProfileError("invalid_document", "Invalid TFDA ZIP size")
    try:
        with ZipFile(BytesIO(archive)) as bundle:
            entries = bundle.infolist()
            if len(entries) != 1:
                raise ValueError("Expected a single TFDA JSON entry")
            entry = entries[0]
            if (not _EXPORT_MEMBER.fullmatch(entry.filename)
                    or entry.is_dir() or entry.flag_bits & 1
                    or entry.compress_type not in (ZIP_DEFLATED, ZIP_STORED)
                    or entry.file_size > _MAX_DOCUMENT_BYTES):
                raise ValueError("Unexpected TFDA JSON entry")
            with bundle.open(entry) as document:
                raw = document.read(_MAX_DOCUMENT_BYTES + 1)
            if len(raw) > _MAX_DOCUMENT_BYTES or len(raw) != entry.file_size:
                raise ValueError("Unexpected TFDA JSON size")
        rows = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_json_constant)
        if not isinstance(rows, list) or len(rows) > _MAX_ROWS or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Expected a bounded list of TFDA JSON objects")
        return rows
    except (BadZipFile, EOFError, OSError, RecursionError, RuntimeError, ValueError, ZlibError):
        raise NutritionProfileError("invalid_document", "Malformed TFDA ZIP export") from None


def _cells(row, prefix):
    cells = dict.fromkeys(NUTRIENTS)
    for label, (field, expected_unit, unit) in _NUTRIENT_LABELS.items():
        key = prefix + label
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        matched = _CELL.fullmatch(raw) if isinstance(raw, str) else None
        if not matched or matched[3] != expected_unit:
            raise NutritionProfileError("invalid_measurement", f"Invalid TFDA label cell {key}")
        comparison, value, _ = matched.groups()
        cells[field] = {"value": value, "unit": unit, "comparison": "less_than" if comparison else "exact",
                        "evidence": {"field": key, "raw": raw}}
    return cells


def build_tfda_label_profile(rows, *, trace_code, publisher, product_name):
    """Build a per-100g profile from one reviewed identity in a decoded export.

    The caller owns source admission and retrieval. The three identity fields
    come from the review, independently of the downloaded row.
    """
    selected = _select_label_row(rows, trace_code, publisher, product_name)
    return _build_profile(selected, trace_code, publisher, product_name)


def _select_label_row(rows, trace_code, publisher, product_name):
    if not isinstance(trace_code, str) or not _TRACE.fullmatch(trace_code):
        raise NutritionProfileError("invalid_identity", "Invalid TFDA trace code")
    for name in (publisher, product_name):
        if not isinstance(name, str) or not name.strip() or name.strip() != name or len(name) > 256:
            raise NutritionProfileError("invalid_identity", "Reviewed TFDA company and product are required")
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        raise NutritionProfileError("invalid_document", "Expected a bounded TFDA export list")
    selected = None
    for row in rows:
        if not isinstance(row, dict):
            raise NutritionProfileError("invalid_document", "TFDA export rows must be objects")
        if row.get("產品追溯系統串接碼") != trace_code:
            continue
        if selected is not None:
            raise NutritionProfileError("source_conflict", "TFDA trace code occurs more than once")
        selected = row
    if selected is None:
        raise NutritionProfileError("not_found", "TFDA trace code was not found")
    if (selected.get("公司名稱"), selected.get("產品名稱")) != (publisher, product_name):
        raise NutritionProfileError("source_conflict", "TFDA trace code no longer matches the reviewed product")
    return selected


def build_reviewed_tfda_package_preview(rows, photo, *, trace_code, publisher, product_name,
                                        reviewed_photo_sha256, reviewed_row_sha256):
    """Preview only the exact reviewed historical artifact; not a photo matcher.

    Expected hashes and identity must be supplied by server-owned review data,
    never by a request or model. No scan or enrichment authority is issued.
    """
    for digest in (reviewed_photo_sha256, reviewed_row_sha256):
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise NutritionProfileError("invalid_identity", "Reviewed SHA-256 digest is required")
    if (not isinstance(photo, bytes) or not 0 < len(photo) <= _MAX_PACKAGE_PHOTO_BYTES
            or sha256(photo).hexdigest() != reviewed_photo_sha256):
        raise NutritionProfileError("identity_mismatch", "Package photo does not match the reviewed artifact")
    selected = _select_label_row(rows, trace_code, publisher, product_name)
    try:
        canonical = json.dumps(selected, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                               allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise NutritionProfileError("invalid_document", "TFDA row is not canonical JSON") from None
    if sha256(canonical).hexdigest() != reviewed_row_sha256:
        raise NutritionProfileError("source_conflict", "TFDA row differs from the reviewed version")
    return {"status": "historical_preview_only", "nutrition_profile":
            _build_profile(selected, trace_code, publisher, product_name)}


def _build_profile(selected, trace_code, publisher, product_name):
    raw_date = selected.get("有效起始日")
    try:
        if not isinstance(raw_date, str) or not re.fullmatch(r"[0-9]{4}/[0-9]{2}/[0-9]{2}", raw_date):
            raise ValueError
        effective_date = datetime.strptime(raw_date, "%Y/%m/%d").date().isoformat()
    except ValueError:
        raise NutritionProfileError("invalid_document", "Invalid TFDA label effective date") from None

    profile = build_nutrition_profile(
        _cells(selected, "每100公克"), basis="per_100g", basis_weight_g=100,
        source_details={
            "source_url": TFDA_STRUCTURED_LABEL_SOURCE_URL,
            "manufacturer_label": {
                "publisher": publisher, "product_name": product_name,
                "dataset_name": TFDA_STRUCTURED_LABEL_DATASET_NAME, "trace_code": trace_code,
            },
            "effective_date": effective_date,
        },
    )
    if not profile["has_required_point_values"]:
        raise NutritionProfileError("incomplete_core", "TFDA label per-100g core values are incomplete")
    serving_cells = _cells(selected, "每份")
    if any(cell is not None for cell in serving_cells.values()):
        serving = selected.get("每一份量")
        matched = _MASS.fullmatch(serving) if isinstance(serving, str) else None
        if not matched:
            raise NutritionProfileError("invalid_basis", "TFDA serving weight in grams is required")
        portion = build_nutrition_profile(serving_cells, basis="per_serving", basis_weight_g=matched[1])
        validate_profile_consistency(profile, [portion])
    return profile
