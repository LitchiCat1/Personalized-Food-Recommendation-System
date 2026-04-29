from datetime import datetime


def compute_bmr(gender: str, weight: float, height: float, age: int) -> float:
    if gender == "male":
        return round(10 * weight + 6.25 * height - 5 * age + 5)
    return round(10 * weight + 6.25 * height - 5 * age - 161)


def compute_tdee(bmr: float, activity_multiplier: float) -> float:
    return round(bmr * activity_multiplier)


def build_user_profile(data: dict) -> dict:
    user_id = data["user_id"]
    gender = data.get("gender", "male")
    weight = data.get("weight", 70)
    height = data.get("height", 170)
    age = data.get("age", 25)
    activity_multiplier = data.get("activity_multiplier", 1.55)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity_multiplier)

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
        "health_conditions": data.get("health_conditions", []),
        "allergens": data.get("allergens", []),
        "target_weight": data.get("target_weight"),
        "diet_type": data.get("diet_type", "均衡飲食"),
        "updated_at": datetime.utcnow().isoformat(),
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
