"""Single-attempt relay bridge for audited nutrition cell selection.

The coordinator supplies a bounded instruction/data prompt and validates its
returned selections. This bridge neither fetches sources nor grants evidence
authority. It shares the existing relay pool; activation still needs capacity
reservation for image recognition.
"""

import math
import time

import requests

from services.ai_relay_service import get_relay_config, relay_chat


MAX_INSTRUCTION_BYTES = 64 * 1024
MAX_DATA_BYTES = 192 * 1024
MAX_RESPONSE_BYTES = 256 * 1024


class NutritionExtractionModelError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _bounded_text(value, maximum):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return len(value.encode("utf-8")) <= maximum
    except UnicodeEncodeError:
        return False


def select_nutrition_cells_with_relay(prompt: dict, *, deadline: float) -> str:
    """Select cells once; do not rotate to a second key or salvage truncation."""
    if (
        not isinstance(prompt, dict) or set(prompt) != {"instruction", "data"}
        or not _bounded_text(prompt["instruction"], MAX_INSTRUCTION_BYTES)
        or not _bounded_text(prompt["data"], MAX_DATA_BYTES)
    ):
        raise NutritionExtractionModelError("invalid_input", "Nutrition extraction requires a bounded instruction/data prompt")
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        raise NutritionExtractionModelError("invalid_input", "Nutrition extraction requires a finite monotonic deadline")
    try:
        finite_deadline = math.isfinite(deadline)
    except OverflowError:
        finite_deadline = False
    if not finite_deadline:
        raise NutritionExtractionModelError("invalid_input", "Nutrition extraction requires a finite monotonic deadline")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NutritionExtractionModelError("timeout", "Nutrition extraction deadline has expired")
    try:
        configured = get_relay_config() is not None
    except (OSError, ValueError):
        configured = False
    if not configured:
        raise NutritionExtractionModelError("unavailable", "Nutrition extraction relay is unavailable")
    try:
        response, finish = relay_chat(
            prompt["instruction"] + "\nUNTRUSTED_SOURCE_DATA_JSON:\n" + prompt["data"],
            max_tokens=4096, timeout=min(25, remaining), deadline=deadline,
            max_attempts=1,
        )
    except requests.Timeout:
        raise NutritionExtractionModelError("timeout", "Nutrition extraction timed out") from None
    except requests.RequestException:
        raise NutritionExtractionModelError("upstream_error", "Nutrition extraction relay request failed") from None
    except ValueError:
        raise NutritionExtractionModelError("invalid_output", "Nutrition extraction relay returned an invalid response") from None
    if time.monotonic() >= deadline:
        raise NutritionExtractionModelError("timeout", "Nutrition extraction deadline has expired")
    if finish != "stop" or not _bounded_text(response, MAX_RESPONSE_BYTES):
        raise NutritionExtractionModelError("invalid_output", "Nutrition extraction did not return a complete response")
    return response
