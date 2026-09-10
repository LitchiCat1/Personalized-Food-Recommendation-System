from datetime import datetime, timezone

from services.disease_rule_service import normalize_allergen_ids, normalize_condition_ids


# 運動係數先前寫死 1.55（中等活動量），而編輯表單根本沒有這一欄，
# 所以每個人的 TDEE 都是 BMR x 1.55——臥床的人和運動員拿到同一個數字。
DEFAULT_DIET_TYPE = "葷食"

ACTIVITY_LEVELS = [
    {"id": "sedentary", "label_zh": "久坐（幾乎不運動）", "multiplier": 1.2},
    {"id": "light", "label_zh": "輕度活動（每週 1-3 天）", "multiplier": 1.375},
    {"id": "moderate", "label_zh": "中等活動（每週 3-5 天）", "multiplier": 1.55},
    {"id": "active", "label_zh": "高度活動（每週 6-7 天）", "multiplier": 1.725},
    {"id": "very_active", "label_zh": "極高活動（勞力工作或每日訓練）", "multiplier": 1.9},
]

ACTIVITY_MULTIPLIER_BY_LABEL = {level["label_zh"]: level["multiplier"] for level in ACTIVITY_LEVELS}
ACTIVITY_MULTIPLIER_BY_ID = {level["id"]: level["multiplier"] for level in ACTIVITY_LEVELS}
MIN_ACTIVITY_MULTIPLIER = ACTIVITY_LEVELS[0]["multiplier"]
MAX_ACTIVITY_MULTIPLIER = ACTIVITY_LEVELS[-1]["multiplier"]


def resolve_activity_multiplier(data: dict) -> float:
    """從 activity_level 或 activity_multiplier 推出係數，並限制在合理範圍。

    客戶端可以送標籤或數字，但不能送出 1.2~1.9 以外的值——那會讓每日熱量
    目標偏離到沒有意義，而這個數字最後會決定推薦哪些餐點。
    """
    level = data.get("activity_level")
    if level in ACTIVITY_MULTIPLIER_BY_ID:
        return ACTIVITY_MULTIPLIER_BY_ID[level]
    if level in ACTIVITY_MULTIPLIER_BY_LABEL:
        return ACTIVITY_MULTIPLIER_BY_LABEL[level]

    raw = data.get("activity_multiplier")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.55
    return min(max(value, MIN_ACTIVITY_MULTIPLIER), MAX_ACTIVITY_MULTIPLIER)


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
    activity_multiplier = resolve_activity_multiplier(data)

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
        "activity_level": next(
            (level["label_zh"] for level in ACTIVITY_LEVELS if level["multiplier"] == activity_multiplier),
            data.get("activity_level", "中等活動量"),
        ),
        "activity_multiplier": activity_multiplier,
        "bmi": round(weight / ((height / 100) ** 2), 1),
        "bmr": bmr,
        "tdee": tdee,
        "daily_calorie_target": data.get("daily_calorie_target", tdee),
        "health_conditions": health_conditions,
        "allergens": allergens,
        "target_weight": data.get("target_weight"),
        # 前端的選項只有葷食／素食（frontend/constants/diet.ts）。
        # 先前這裡預設「均衡飲食」，新帳號一建好就是「我的」頁不認得的值。
        "diet_type": data.get("diet_type") or DEFAULT_DIET_TYPE,
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }


def build_bmr_response(data: dict) -> dict:
    gender = data.get("gender", "male")
    weight = data.get("weight", 70)
    height = data.get("height", 170)
    age = data.get("age", 25)
    activity = resolve_activity_multiplier(data)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity)

    return {
        "bmr": bmr,
        "tdee": tdee,
        "formula": "Mifflin-St Jeor",
        "gender": gender,
        "bmi": round(weight / ((height / 100) ** 2), 1),
    }
