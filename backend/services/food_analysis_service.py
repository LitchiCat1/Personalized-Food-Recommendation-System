import os

from services.medical_risk_service import evaluate_medical_risk, risk_messages


VISION_CONFIRMATION_CONFIDENCE = float(os.environ.get("VISION_CONFIRMATION_CONFIDENCE", "0.75"))
PORTION_UNCERTAINTY_BY_CONFIDENCE = {
    "high": 0.25,
    "medium": 0.40,
    "low": 0.60,
}


def build_portion_range(weight_g: float, reliability_level: str) -> dict:
    uncertainty = PORTION_UNCERTAINTY_BY_CONFIDENCE.get(reliability_level, 0.60)
    return {
        "min_g": max(1, round(weight_g * (1 - uncertainty), 1)),
        "max_g": round(weight_g * (1 + uncertainty), 1),
        "uncertainty_percent": int(uncertainty * 100),
    }


def build_detection_reliability(label: str, confidence: float, needs_confirmation: bool, nutrients: dict) -> dict:
    if needs_confirmation or confidence < VISION_CONFIRMATION_CONFIDENCE:
        level = "low" if confidence < 0.60 else "medium"
    else:
        level = "high"

    reasons = [
        f"Gemini Vision confidence {confidence:.0%}",
        "TFDA / database grounding" if nutrients.get("source") == "TFDA" else "database-only grounding",
        "Vision and database are combined to reduce false positives.",
    ]
    if needs_confirmation:
        reasons.append("Needs user confirmation because the match is uncertain.")

    return {
        "level": level,
        "score": round(max(0, min(1, confidence)), 2),
        "reasons": reasons,
    }


def check_food_safety(
    nutrients: dict,
    weight_g: float,
    user_conditions: list,
    user_allergens: list,
    disease_rules: dict,
    allergen_taxonomy: dict | None = None,
    user_profile: dict | None = None,
) -> list:
    if not nutrients.get("calories"):
        return []

    risk_result = evaluate_medical_risk(
        {
            "label": nutrients.get("name_zh") or nutrients.get("label"),
            "name_zh": nutrients.get("name_zh"),
            "gi": nutrients.get("gi"),
            "allergens": nutrients.get("allergens", []),
            "sodium": nutrients.get("sodium"),
            "carbs": nutrients.get("carbs"),
            "protein": nutrients.get("protein"),
            "fat": nutrients.get("fat"),
            "sugar": nutrients.get("sugar"),
            "saturated_fat": nutrients.get("saturated_fat"),
            "trans_fat": nutrients.get("trans_fat"),
            "fiber": nutrients.get("fiber"),
            "calcium": nutrients.get("calcium"),
            "iron": nutrients.get("iron"),
            "is_fried": nutrients.get("is_fried"),
        },
        user_conditions,
        user_allergens,
        disease_rules,
        allergen_taxonomy or {"groups": []},
        portion_g=weight_g,
        user_profile=user_profile,
    )
    return risk_messages(risk_result)
