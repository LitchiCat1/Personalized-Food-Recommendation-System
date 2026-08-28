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
    warnings = risk_messages(risk_result)

    # Check drug-food interactions
    user_meds = (user_profile or {}).get("medications", [])
    food_name = (nutrients.get("name_zh") or nutrients.get("label") or "").lower()

    if any(m in ["Warfarin", "抗凝血劑"] for m in user_meds):
        if any(k in food_name for k in ["菠菜", "花椰菜", "芥藍", "綠茶", "羽衣甘藍"]):
            warnings.append("💊 Warfarin 用藥提醒：本食物含高維生素K，請維持穩定攝取量，避免大幅改變影響藥效。")

    if any(m in ["Statins", "降血脂藥"] for m in user_meds):
        if any(k in food_name for k in ["柚子", "葡萄柚", "文旦"]):
            warnings.append("💊 Statins 降血脂藥禁忌：葡萄柚/柚子會抑制藥物代謝，請避免食用。")

    if any(m in ["ACEi", "降血壓藥"] for m in user_meds):
        if any(k in food_name for k in ["香蕉", "奇異果", "低鈉鹽", "深綠蔬菜"]):
            warnings.append("💊 降血壓藥提醒：本餐含有高鉀成分，服藥期間請避免過量高鉀飲食。")

    if any(m in ["Metformin", "降血糖藥"] for m in user_meds):
        if any(k in food_name for k in ["酒", "啤酒", "清酒", "紅酒"]):
            warnings.append("💊 Metformin 用藥警示：服藥期間請勿飲酒，預防乳酸中毒風險。")

    return warnings

