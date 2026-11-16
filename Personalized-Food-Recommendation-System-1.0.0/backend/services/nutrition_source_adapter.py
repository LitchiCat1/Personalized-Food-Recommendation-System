"""Parse one reviewed Markdown nutrition table without granting source rights.

Only trusted server policy may call this helper with a reviewed spec and eligible
item IDs. Search results, client JSON and model output cannot supply those values.
This first adapter rejects layout drift, multiple tables and unaudited columns.
"""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import re

from services.nutrition_evidence_service import IDENTITY_ENUMS, LABELS
from services.tavily_retrieval_service import TavilyRetrievalError, validate_reviewed_url


MAX_DOCUMENT_BYTES = 128 * 1024
DECIMAL = r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
MEASUREMENT = re.compile(r"(?P<less><\s*)?(?P<value>" + DECIMAL + r")\s*(?P<unit>kcal|kJ|mg|g)\Z")
PER_100G = re.compile(r"(?:per\s*100\s*g|每\s*100\s*(?:公克|克))\Z", re.I)
PER_SERVING = re.compile(r"(?:per\s+serving|每份|每一份)\s*[\(\uff08]\s*(?P<weight>" + DECIMAL + r")\s*(?:g|公克|克)\s*[\)\uff09]\Z", re.I)
MISSING = {"-", "\u2014", "N/A"}
NUTRIENT_BY_LABEL = {label: nutrient for nutrient, labels in LABELS.items() for label in labels}
IGNORED_LABELS = {"salt", "added sugar", "added sugars", "net carbs", "net carbohydrate", "net carbohydrates",
                  "%dv", "daily value", "\u9e7d", "\u6dfb\u52a0\u7cd6", "\u6de8\u78b3\u6c34\u5316\u5408\u7269"}


class NutritionSourceAdapterError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise NutritionSourceAdapterError(code, message)


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and value.strip() == value


def _single_line(value):
    return isinstance(value, str) and 0 < len(value) <= 4096 and value.strip() == value and not any(
        ord(character) < 32 for character in value)


def _url(value):
    try:
        return validate_reviewed_url(value)
    except TavilyRetrievalError as error:
        raise NutritionSourceAdapterError("invalid_provenance", "A source requires a reviewed canonical HTTPS URL") from error


def _metadata(document, spec):
    _require(isinstance(document, dict) and isinstance(spec, dict), "invalid_document", "Document and reviewed spec must be objects")
    url = _url(spec.get("source_url"))
    _require(url == spec.get("source_url") and document.get("url") == url,
             "source_mismatch", "Retrieved URL must exactly match the canonical reviewed URL")
    _url(document.get("url"))
    content = document.get("raw_content")
    _require(isinstance(content, str) and bool(content) and len(content) <= MAX_DOCUMENT_BYTES,
             "invalid_document", "A source requires bounded nonempty Markdown")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as error:
        raise NutritionSourceAdapterError("invalid_document", "Source text must be valid UTF-8") from error
    _require(len(encoded) <= MAX_DOCUMENT_BYTES, "oversized_document", "Source text exceeds the adapter budget")
    _require(not any(ord(character) < 32 and character not in "\r\n\t" for character in content),
             "invalid_document", "Source text contains unsupported control characters")
    content_hash = hashlib.sha256(encoded).hexdigest()
    _require(document.get("content_hash") == content_hash,
             "content_hash_mismatch", "Source content disagrees with its retrieval hash")
    retrieved = document.get("retrieved_at")
    _require(isinstance(retrieved, str) and len(retrieved) <= 64 and "T" in retrieved,
             "invalid_provenance", "Retrieval timestamp requires a timezone")
    try:
        timestamp = datetime.fromisoformat(retrieved)
    except ValueError as error:
        raise NutritionSourceAdapterError("invalid_provenance", "Invalid retrieval timestamp") from error
    _require(timestamp.tzinfo is not None and timestamp.utcoffset() is not None,
             "invalid_provenance", "Retrieval timestamp requires a timezone")
    _require(all(_identifier(value) for value in (spec.get("source_id"), spec.get("adapter_version"),
                                                 spec.get("table_id"), document.get("retrieval_version"))),
             "invalid_spec", "Source, table, adapter and retrieval versions require bounded IDs")
    return content, {"source_id": spec["source_id"], "source_url": url, "content_hash": content_hash,
                     "retrieved_at": retrieved, "adapter_version": spec["adapter_version"],
                     "retrieval_version": document["retrieval_version"]}


def _identity(spec):
    identity = spec.get("food_identity")
    _require(isinstance(identity, dict) and _single_line(identity.get("name")),
             "invalid_identity", "A reviewed source needs its original food name")
    for field, allowed in IDENTITY_ENUMS.items():
        _require(isinstance(identity.get(field), str) and identity[field] in allowed,
                 "invalid_identity", "Reviewed food identity requires explicit enum values")
    for field in ("brand", "variant"):
        _require(field in identity and (identity[field] is None or _single_line(identity[field])),
                 "invalid_identity", "Reviewed brand and variant must be explicit strings or null")
    evidence = spec.get("identity_line")
    _require(_single_line(evidence) and identity["name"] in evidence,
             "invalid_identity", "Reviewed identity evidence must contain the original food name")
    return deepcopy(identity), evidence


def _cells(line):
    text = line.strip()
    _require(text.startswith("|") and text.endswith("|") and "\\|" not in text,
             "invalid_table", "Only explicit unescaped pipe table cells are supported")
    cells = [value.strip() for value in text[1:-1].split("|")]
    _require(2 <= len(cells) <= 16 and all(len(value) <= 4096 for value in cells),
             "invalid_table", "Table cells exceed their layout budget")
    return cells


def _table(content, spec, identity_line):
    lines = content.splitlines()
    identities = [index for index, line in enumerate(lines) if line == identity_line]
    _require(len(identities) == 1, "ambiguous_identity", "Reviewed identity line must occur exactly once")
    headers = spec.get("table_header")
    _require(isinstance(headers, list) and 2 <= len(headers) <= 16 and all(_single_line(value) for value in headers)
             and len(set(headers)) == len(headers), "invalid_spec", "Reviewed headers must be explicit and unique")
    _require(type(spec.get("label_column_index", 0)) is int and spec.get("label_column_index", 0) == 0,
             "invalid_spec", "The nutrient label column must be first")
    pipe_indices = [index for index, line in enumerate(lines) if "|" in line]
    separators = []
    for index in pipe_indices:
        cells = _cells(lines[index])
        if all(re.fullmatch(r":?-{3,}:?", cell) is not None for cell in cells):
            separators.append(index)
    _require(len(separators) == 1, "ambiguous_table", "Exactly one Markdown table is supported")
    separator = separators[0]
    _require(separator > 0 and _cells(lines[separator - 1]) == headers
             and len(_cells(lines[separator])) == len(headers),
             "header_mismatch", "Markdown table must match the complete reviewed header")
    _require(identities[0] < separator - 1, "ambiguous_identity", "Food identity must precede the reviewed table")
    start, end = separator - 1, separator + 1
    rows = []
    while end < len(lines) and "|" in lines[end]:
        cells = _cells(lines[end])
        _require(len(cells) == len(headers) and bool(cells[0]),
                 "invalid_table", "Every row must match the reviewed column count and have a label")
        _require(cells != headers, "ambiguous_table", "Repeated table headers are not supported")
        rows.append((cells, lines[end].strip()))
        end += 1
    _require(rows and len(rows) <= 64 and pipe_indices == list(range(start, end)),
             "ambiguous_table", "Only one contiguous bounded table is supported")
    return headers, rows


def _columns(spec, headers):
    reviewed = spec.get("columns")
    _require(isinstance(reviewed, dict) and len(reviewed) == len(headers) - 1
             and all(_identifier(column_id) for column_id in reviewed),
             "invalid_spec", "Every non-label column must have a reviewed basis")
    columns, indices = {}, {}
    for column_id, column in reviewed.items():
        _require(isinstance(column, dict) and type(column.get("index")) is int
                 and 1 <= column["index"] < len(headers) and column["index"] not in indices,
                 "invalid_spec", "Reviewed column indices must be unique data columns")
        index = column["index"]
        header = headers[index]
        _require(column.get("evidence") == header, "invalid_basis", "Basis evidence must exactly equal its source header")
        basis = column.get("basis")
        weight = column.get("basis_weight_g")
        _require(weight is None or (not isinstance(weight, bool) and isinstance(weight, (str, int, float))
                 and len(str(weight)) <= 80 and re.fullmatch(DECIMAL, str(weight)) is not None),
                 "invalid_basis", "Reviewed basis weight must be an ordinary nonnegative decimal")
        _require(column.get("basis_volume_ml") is None, "invalid_basis", "Volume conversion is not supported by this adapter")
        if basis == "per_100g":
            _require(PER_100G.fullmatch(header) is not None and (weight is None or Decimal(str(weight)) == 100),
                     "invalid_basis", "The source header must explicitly describe 100g")
            weight = "100"
        elif basis == "per_serving":
            match = PER_SERVING.fullmatch(header)
            _require(match is not None and weight is not None and Decimal(str(weight)) > 0
                     and Decimal(match.group("weight")) == Decimal(str(weight)),
                     "invalid_basis", "Serving header must explicitly give the reviewed positive gram weight")
            weight = str(weight)
        else:
            raise NutritionSourceAdapterError("invalid_basis", "Only evidenced mass-based source columns are supported")
        columns[column_id] = {"basis": basis, "basis_weight_g": weight, "evidence": header}
        indices[index] = column_id
    _require(set(indices) == set(range(1, len(headers))), "invalid_spec", "No unreviewed data column may be omitted")
    return columns, indices


def _measurement(text, nutrient, evidence):
    if text in MISSING:
        return None
    match = MEASUREMENT.fullmatch(text)
    _require(match is not None and len(match.group("value")) <= 80,
             "invalid_cell", "Canonical nutrient cells require an explicit supported number and unit")
    value, unit = match.group("value"), match.group("unit")
    _require(unit in (("kcal", "kJ") if nutrient == "calories" else ("g", "mg")),
             "invalid_unit", "Nutrient unit does not match the canonical row")
    less = match.group("less") is not None
    _require(not less or Decimal(value) > 0, "invalid_cell", "An exclusive upper bound must be positive")
    return {"raw_value": "<" + value if less else value, "unit": unit,
            "comparison": "less_than" if less else "exact", "evidence": evidence,
            "label_rounding": None}


def _nutrient(label):
    lowered = label.lower()
    if lowered in NUTRIENT_BY_LABEL:
        return NUTRIENT_BY_LABEL[lowered]
    if lowered in IGNORED_LABELS:
        return None
    for known in NUTRIENT_BY_LABEL:
        # A changed nutrient label may hide a corroborating energy/serving row.
        # Fail closed instead of guessing its semantics or silently ignoring it.
        pattern = r"(?<![a-z])" + re.escape(known) + r"(?![a-z])" if known.isascii() else re.escape(known)
        _require(re.search(pattern, lowered) is None, "unsupported_nutrient_label",
                 "A nutrient-like row label requires a specifically reviewed adapter")
    return None


def build_reviewed_markdown_source(document, *, spec, eligible_item_ids):
    """Adapt one server-reviewed document after policy/rights/identity approval.

    This helper establishes table layout and original cell evidence. The caller
    must establish reuse rights and item compatibility before assigning IDs.
    It performs no network calls, model inference, arithmetic or persistence.
    """
    content, metadata = _metadata(document, spec)
    _require(isinstance(eligible_item_ids, list) and 0 < len(eligible_item_ids) <= 64
             and all(_identifier(item_id) for item_id in eligible_item_ids)
             and len(set(eligible_item_ids)) == len(eligible_item_ids),
             "invalid_items", "Eligible item IDs must be a bounded unique server-approved list")
    identity, identity_evidence = _identity(spec)
    headers, parsed_rows = _table(content, spec, identity_evidence)
    columns, indices = _columns(spec, headers)
    rows = {}
    for index, (cells, evidence) in enumerate(parsed_rows):
        nutrient = _nutrient(cells[0])
        if nutrient is None:
            continue
        row_cells = {}
        for column_index, column_id in indices.items():
            measurement = _measurement(cells[column_index], nutrient, evidence)
            if measurement is not None:
                row_cells[column_id] = measurement
        rows["row-" + str(index + 1)] = {"nutrient": nutrient, "label": cells[0], "cells": row_cells}
    _require(any(row["cells"] for row in rows.values()), "missing_nutrition_table",
             "The reviewed table contains no supported nutrient measurement")
    table = {"table_id": spec["table_id"], "eligible_item_ids": list(eligible_item_ids),
             "food_identity": identity, "identity_evidence": identity_evidence,
             "columns": columns, "rows": rows}
    return dict(metadata, audited=True, reusable=True, tables=[table])
