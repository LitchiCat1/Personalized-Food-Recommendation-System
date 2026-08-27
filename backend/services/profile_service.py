from datetime import datetime, timezone

from services.disease_rule_service import normalize_allergen_ids, normalize_condition_ids


def compute_bmr(gender: str, weight: float, height: float, age: int) -> float:
    if gender == "male":
        return round(10 * weight + 6.25 * height - 5 * age + 5)
    return round(10 * weight + 6.25 * height - 5 * age - 161)


def compute_tdee(bmr: float, activity_multiplier: float) -> float:
    return round(bmr * activity_multiplier)


def build_user_profile(data: dict, disease_rules: dict | None = None, allergen_taxonomy: dict | None = None) -> dict:
    user_id = data["user_id"]
    gender = data.get("gender", "male")
    weight = data.get("weight", 70)
    height = data.get("height", 170)
    age = data.get("age", 25)
    activity_multiplier = data.get("activity_multiplier", 1.55)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity_multiplier)

    health_conditions = data.get("health_conditions", [])
    allergens = data.get("allergens", [])
    if disease_rules:
        health_conditions = normalize_condition_ids(health_conditions, disease_rules)
    if allergen_taxonomy:
        allergens = normalize_allergen_ids(allergens, allergen_taxonomy)

    return {
        "user_id": user_id,
        "name": data.get("name", ""),
        "gender": gender,
        "height": height,
        "weight": weight,
        "age": age,
        "activity_level": data.get("activity_level", "中等活動量"),
        "activity_multiplier": activity_multiplier,
        "bmi": round(weight / ((height / 100) ** 2), 1),
        "bmr": bmr,
        "tdee": tdee,
        "daily_calorie_target": data.get("daily_calorie_target", tdee),
        "health_conditions": health_conditions,
        "allergens": allergens,
        "target_weight": data.get("target_weight"),
        "diet_type": data.get("diet_type", "均衡飲食"),
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }


def build_bmr_response(data: dict) -> dict:
    gender = data.get("gender", "male")
    weight = data.get("weight", 70)
    height = data.get("height", 170)
    age = data.get("age", 25)
    activity = data.get("activity_multiplier", 1.55)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity)

    return {
        "bmr": bmr,
        "tdee": tdee,
        "formula": "Mifflin-St Jeor",
        "gender": gender,
        "bmi": round(weight / ((height / 100) ** 2), 1),
    }
