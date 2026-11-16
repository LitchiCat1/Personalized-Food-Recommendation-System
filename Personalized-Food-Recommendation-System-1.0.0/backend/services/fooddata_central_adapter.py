"""Strict offline adapter for USDA FoodData Central API replays.

The adapter is deliberately separate from the Tavily Markdown adapter.  FDC
returns structured JSON and its public-domain statement does not make an
arbitrary record compatible with a photographed food.  Callers must supply a
server-reviewed spec and eligible item IDs; this module only parses a bounded
response into the existing evidence catalog.
"""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re

from services.nutrition_evidence_service import NUTRIENTS, IDENTITY_ENUMS
from services.tavily_retrieval_service import TavilyRetrievalError, validate_reviewed_url


MAX_PAYLOAD_BYTES = 512 * 1024
MAX_NUTRIENTS = 512
ADAPTER_VERSION = "usda-fdc-json-v1"
RETRIEVAL_VERSION = "usda-fdc-api-v1"
ALLOWED_DATA_TYPES = {"SR Legacy", "Foundation", "Survey (FNDDS)"}
FDC_DETAIL_URL = "https://api.nal.usda.gov/fdc/v1/food/{}"
_FDC_ID = re.compile(r"[1-9][0-9]{0,17}\Z")

# USDA nutrient numbers are stable identifiers in FoodData Central.  Keep the
# mapping explicit so a similarly named but semantically different nutrient is
# never silently selected.
FDC_NUMBERS = {
    # SR Legacy / FNDDS identifiers.
    "calories": {"1008": "kcal", "208": "kcal", "1062": "kJ",
                 # Foundation uses separate Atwater methods; the reviewed
                 # spec must select one when both are present.
                 "957": "kcal", "958": "kcal"},
    "protein": {"1003": "g", "203": "g"},
    "carbs": {"1005": "g", "205": "g", "205.2": "g"},
    "fat": {"1004": "g", "204": "g"},
    "sodium": {"1093": "mg", "307": "mg"},
    "fiber": {"1079": "g", "291": "g"},
    "sugar": {"2000": "g", "1063": "g", "269": "g", "269.3": "g"},
    "saturated_fat": {"1258": "g", "606": "g"},
    "trans_fat": {"1257": "g", "605": "g"},
}
LABELS = {
    "calories": "Energy", "protein": "Protein", "carbs": "Carbohydrate",
    "fat": "Total fat", "sodium": "Sodium", "fiber": "Dietary fiber",
    "sugar": "Sugars", "saturated_fat": "Saturated fat", "trans_fat": "Trans fat",
}


class FoodDataCentralAdapterError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise FoodDataCentralAdapterError(code, message)


def _text(value, limit=4096):
    return (isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value
            and not any(ord(character) < 32 for character in value))


def _identifier(value):
    return _text(value, 128)


def _canonical_fdc_id(value):
    """Return the only ID form accepted by the fixed detail endpoint."""
    if isinstance(value, bool):
        valid = False
    elif isinstance(value, int):
        valid = value > 0
        value = str(value)
    elif isinstance(value, str):
        valid = _FDC_ID.fullmatch(value) is not None
    else:
        valid = False
    _require(valid and _FDC_ID.fullmatch(value) is not None,
             "invalid_payload", "FDC food ID must be a canonical numeric string")
    return value


def _canonical_payload(payload):
    try:
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise FoodDataCentralAdapterError("invalid_payload", "FDC response must be finite JSON") from error
    _require(len(encoded.encode("utf-8")) <= MAX_PAYLOAD_BYTES,
             "oversized_payload", "FDC response exceeds the adapter budget")
    return encoded


def _metadata(document, spec):
    _require(isinstance(document, dict) and isinstance(spec, dict), "invalid_document", "Document and spec must be objects")
    try:
        url = validate_reviewed_url(spec.get("source_url"))
    except TavilyRetrievalError as error:
        raise FoodDataCentralAdapterError("invalid_provenance", "FDC requires a reviewed canonical HTTPS URL") from error
    _require(url == spec.get("source_url") and document.get("url") == url,
             "source_mismatch", "FDC replay URL must exactly match the reviewed page URL")
    payload = document.get("payload")
    canonical = _canonical_payload(payload)
    _require(document.get("content_hash") == hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
             "content_hash_mismatch", "FDC payload disagrees with its retrieval hash")
    retrieved = document.get("retrieved_at")
    _require(_text(retrieved, 64) and "T" in retrieved, "invalid_provenance", "FDC retrieval time is required")
    try:
        timestamp = datetime.fromisoformat(retrieved)
    except ValueError as error:
        raise FoodDataCentralAdapterError("invalid_provenance", "FDC retrieval timestamp is invalid") from error
    _require(timestamp.tzinfo is not None and timestamp.utcoffset() is not None,
             "invalid_provenance", "FDC retrieval timestamp requires a timezone")
    for field in ("source_id", "adapter_version", "table_id"):
        _require(_identifier(spec.get(field)), "invalid_spec", "FDC source IDs and versions are required")
    _require(spec["adapter_version"] == ADAPTER_VERSION,
             "invalid_spec", "FDC adapter version is not supported")
    _require(document.get("retrieval_version") == RETRIEVAL_VERSION,
             "invalid_provenance", "FDC retrieval client version is not supported")
    return payload, {
        "source_id": spec["source_id"], "source_url": url,
        "content_hash": document["content_hash"], "retrieved_at": retrieved,
        "adapter_version": spec["adapter_version"], "retrieval_version": document["retrieval_version"],
    }


def _identity(spec, payload):
    identity = spec.get("food_identity")
    _require(isinstance(identity, dict) and _text(identity.get("name")),
             "invalid_identity", "FDC food identity requires an original name")
    for field, allowed in IDENTITY_ENUMS.items():
        _require(isinstance(identity.get(field), str) and identity[field] in allowed,
                 "invalid_identity", "FDC food identity enums are required")
    for field in ("brand", "variant"):
        _require(field in identity and (identity[field] is None or _text(identity[field])),
                 "invalid_identity", "FDC brand and variant must be explicit or null")
    _require(payload.get("description") == identity["name"], "identity_mismatch",
             "FDC description differs from the reviewed food identity")
    evidence = "FoodData Central description: " + payload["description"]
    return deepcopy(identity), evidence


def _amount(value):
    _require(not isinstance(value, bool) and isinstance(value, (int, float, str)),
             "invalid_number", "FDC nutrient amount must be numeric")
    text = str(value)
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise FoodDataCentralAdapterError("invalid_number", "FDC nutrient amount is not decimal") from error
    _require(number.is_finite() and number >= 0 and len(text) <= 80,
             "invalid_number", "FDC nutrient amount must be finite and nonnegative")
    return text


def _nutrients(payload, spec):
    rows = payload.get("foodNutrients")
    _require(isinstance(rows, list) and 0 < len(rows) <= MAX_NUTRIENTS,
             "invalid_payload", "FDC foodNutrients must be a bounded nonempty list")
    selected = {field: {} for field in NUTRIENTS}
    for entry in rows:
        if not isinstance(entry, dict):
            raise FoodDataCentralAdapterError("invalid_payload", "FDC nutrient rows must be objects")
        nutrient = entry.get("nutrient")
        if not isinstance(nutrient, dict):
            continue
        number = nutrient.get("number")
        if not isinstance(number, str):
            continue
        for field, mapping in FDC_NUMBERS.items():
            if number not in mapping:
                continue
            amount = entry.get("amount")
            if amount is None:
                continue
            unit = mapping[number]
            actual_unit = nutrient.get("unitName")
            _require(isinstance(actual_unit, str) and actual_unit.lower() == unit.lower(),
                     "invalid_unit", "FDC nutrient unit disagrees with its nutrient number")
            _require(number not in selected[field], "ambiguous_nutrient",
                     "FDC contains duplicate rows for a canonical nutrient number")
            selected[field][number] = {"raw_value": _amount(amount), "unit": unit,
                                       "comparison": "exact",
                                       "evidence": f"foodNutrients[{number}].amount={amount} {unit}",
                                       "label_rounding": None}
    preferred = spec.get("preferred_nutrient_numbers", {})
    _require(preferred is None or isinstance(preferred, dict), "invalid_spec",
             "Preferred FDC nutrient numbers must be an object")
    if preferred is None:
        preferred = {}
    if spec.get("preferred_energy_number") is not None and "calories" not in preferred:
        preferred = dict(preferred, calories=spec.get("preferred_energy_number"))
    for field, values in selected.items():
        if not values:
            continue
        choice = preferred.get(field) if isinstance(preferred, dict) else None
        if field == "calories":
            kcal_numbers = [number for number in values if FDC_NUMBERS[field][number] == "kcal"]
            _require(len(kcal_numbers) <= 1 or isinstance(choice, str) and choice in kcal_numbers,
                     "ambiguous_nutrient", "FDC contains multiple kcal energy methods; a reviewed number is required")
            if len(kcal_numbers) > 1:
                selected[field] = {choice: values[choice]}
                selected[field].update({number: values[number] for number in values
                                        if FDC_NUMBERS[field][number] == "kJ"})
            continue
        if len(values) > 1:
            _require(isinstance(choice, str) and choice in values, "ambiguous_nutrient",
                     "FDC contains multiple source numbers; a reviewed number is required")
            selected[field] = {choice: values[choice]}
        elif choice is not None:
            _require(isinstance(choice, str) and choice in values, "invalid_spec",
                     "The reviewed FDC nutrient number is not present")
    return selected


def build_reviewed_fooddata_central_source(document, *, spec, eligible_item_ids):
    """Build an audited source block from a server-reviewed FDC JSON replay.

    Only FDC records whose API values are explicitly per 100g are accepted. A
    branded serving-label response must use a future, separately reviewed
    serving adapter rather than being silently treated as a 100g profile.
    """
    payload, metadata = _metadata(document, spec)
    _require(isinstance(payload, dict), "invalid_payload", "FDC payload must be an object")
    _require(payload.get("dataType") in ALLOWED_DATA_TYPES, "unsupported_data_type",
             "This adapter accepts only FDC analytical records with per-100g semantics")
    fdc_id = _canonical_fdc_id(payload.get("fdcId"))
    expected_url = FDC_DETAIL_URL.format(fdc_id)
    _require(spec["source_url"] == expected_url and document["url"] == expected_url,
             "source_mismatch", "FDC replay URL must match the fixed food detail endpoint")
    serving = payload.get("servingSize")
    serving_unit = payload.get("servingSizeUnit")
    _require(serving is None or (serving == 100 and serving_unit == "g"), "unsupported_basis",
             "FDC serving labels are not accepted unless explicitly 100g")
    _require(isinstance(eligible_item_ids, list) and 0 < len(eligible_item_ids) <= 64
             and all(_identifier(item_id) for item_id in eligible_item_ids)
             and len(set(eligible_item_ids)) == len(eligible_item_ids), "invalid_items", "Eligible IDs must be unique")
    identity, identity_evidence = _identity(spec, payload)
    selected = _nutrients(payload, spec)
    for field, values in selected.items():
        if field != "calories":
            _require(len(values) <= 1, "ambiguous_nutrient",
                     "FDC contains multiple source numbers for one canonical nutrient")

    energy = selected["calories"]
    preferred_energy = spec.get("preferred_energy_number")
    if preferred_energy is not None:
        _require(isinstance(preferred_energy, str) and preferred_energy in energy,
                 "invalid_spec", "The reviewed FDC energy number is not present")
        preferred_unit = FDC_NUMBERS["calories"][preferred_energy]
        _require(preferred_unit == "kcal", "invalid_spec", "The reviewed FDC energy number must be kcal")
        kcal = energy[preferred_energy]
    else:
        kcal_candidates = [energy[number] for number in ("1008", "208", "957", "958") if number in energy]
        _require(len(kcal_candidates) <= 1, "ambiguous_nutrient",
                 "FDC contains multiple kcal energy methods; a reviewed number is required")
        kcal = kcal_candidates[0] if kcal_candidates else None
    kj = energy.get("1062")
    columns = {}
    if kcal is not None:
        columns["per_100g_kcal"] = {"basis": "per_100g", "basis_weight_g": "100",
                                    "evidence": "FoodData Central nutrient amounts per 100 g (kcal)"}
    if kj is not None:
        columns["per_100g_kj"] = {"basis": "per_100g", "basis_weight_g": "100",
                                  "evidence": "FoodData Central nutrient amounts per 100 g (kJ)"}
    _require(columns, "missing_nutrition_table", "FDC record has no supported energy value")
    rows = {}
    for field in NUTRIENTS:
        values = selected[field]
        cells = {}
        if field == "calories":
            if kcal is not None:
                cells["per_100g_kcal"] = kcal
            if kj is not None:
                cells["per_100g_kj"] = kj
        else:
            # Non-energy FDC values are already per 100g; put them in the kcal
            # column when available, otherwise the kJ column remains selectable.
            chosen = next(iter(values.values()), None)
            if chosen is not None:
                cells[next(iter(columns))] = chosen
        if cells:
            rows["fdc-" + field] = {"nutrient": field, "label": LABELS[field], "cells": cells}
    return dict(metadata, audited=True, reusable=True, tables=[{
        "table_id": spec["table_id"], "eligible_item_ids": list(eligible_item_ids),
        "food_identity": identity, "identity_evidence": identity_evidence,
        "columns": columns, "rows": rows,
    }])

