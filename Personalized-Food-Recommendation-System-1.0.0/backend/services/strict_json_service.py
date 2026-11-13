"""Parse complete model responses without salvaging embedded JSON fragments."""

import json
import math
import re


MAX_MODEL_JSON_BYTES = 256 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Model JSON contains a duplicate key")
        result[key] = value
    return result


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Model JSON contains a nonfinite number")
    return number


def _reject_constant(_value):
    raise ValueError("Model JSON contains a nonfinite constant")


def parse_strict_model_json(text, *, allow_array=False, max_bytes=MAX_MODEL_JSON_BYTES):
    if not isinstance(text, str) or len(text.encode("utf-8")) > max_bytes:
        raise ValueError("Model JSON is missing or exceeds the response limit")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        fenced = re.fullmatch(r"```(?:json)?\s*\n?([\s\S]*?)\s*```", cleaned, flags=re.IGNORECASE)
        if not fenced:
            raise ValueError("Model JSON has an incomplete outer fence")
        cleaned = fenced.group(1)
    try:
        result = json.loads(cleaned, object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant, parse_float=_finite_float)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Model response must contain one complete JSON value") from error
    if not isinstance(result, dict) and not (allow_array and isinstance(result, list)):
        raise ValueError("Model JSON requires an object")
    return result
