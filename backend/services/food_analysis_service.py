import os


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
        f"Gemini Vision 食物辨識信心 {confidence:.0%}",
        "營養值依 TFDA/資料庫每 100g 換算" if nutrients.get("source") == "TFDA" else "營養值依自訂食品資料庫換算",
        "份量由 Gemini 依照片內容估算，未使用秤重或深度資訊",
    ]
    if needs_confirmation:
        reasons.append("此結果已標記為需要人工確認")

    return {
        "level": level,
        "score": round(max(0, min(1, confidence)), 2),
        "reasons": reasons,
    }


def check_food_safety(nutrients: dict, weight_g: float, user_conditions: list, user_allergens: list, disease_rules: dict) -> list:
    warnings = []
    if not nutrients.get("calories"):
        return warnings

    scale = weight_g / 100.0
    actual_sodium = (nutrients.get("sodium") or 0) * scale
    actual_carbs = (nutrients.get("carbs") or 0) * scale
    actual_protein = (nutrients.get("protein") or 0) * scale
    actual_fat = (nutrients.get("fat") or 0) * scale
    gi = nutrients.get("gi")
    food_allergens = nutrients.get("allergens", [])

    for allergen in food_allergens:
        if allergen in user_allergens:
            warnings.append(f"含過敏原: {allergen}")

    for condition in user_conditions:
        rules = disease_rules.get(condition, {})
        if "blocked_gi" in rules and gi in rules["blocked_gi"]:
            warnings.append(f"高 GI 食物 - {condition}患者請注意")
        if "max_sodium_per_meal" in rules and actual_sodium > rules["max_sodium_per_meal"]:
            warnings.append(f"高鈉 ({actual_sodium:.0f}mg) - {condition}患者請注意")
        if "max_carbs_per_meal" in rules and actual_carbs > rules["max_carbs_per_meal"]:
            warnings.append(f"碳水過高 ({actual_carbs:.0f}g) - {condition}患者請注意")
        if "max_protein_per_meal" in rules and actual_protein > rules["max_protein_per_meal"]:
            warnings.append(f"蛋白質過高 ({actual_protein:.0f}g) - {condition}患者請注意")
        if "max_fat_per_meal" in rules and actual_fat > rules["max_fat_per_meal"]:
            warnings.append(f"脂肪過高 ({actual_fat:.0f}g) - {condition}患者請注意")
    return warnings
