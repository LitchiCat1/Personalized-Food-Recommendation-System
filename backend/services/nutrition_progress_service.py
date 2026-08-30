from datetime import datetime

from services.app_time_service import app_today


DEFAULT_DAILY_NUTRITION_TARGETS = {
    "calories": 2100,
    "protein": 130,
    "carbs": 250,
    "sugar": 50,
    "fat": 70,
    "saturated_fat": 20,
    "trans_fat": 0,
    "fiber": 25,
    "sodium": 2000,
}

NUTRITION_GOAL_TYPES = {
    "calories": "upper_limit",
    "protein": "minimum_target",
    "carbs": "upper_limit",
    "sugar": "upper_limit",
    "fat": "upper_limit",
    "saturated_fat": "upper_limit",
    "trans_fat": "upper_limit",
    "fiber": "minimum_target",
    "sodium": "upper_limit",
}

RECORD_TOTAL_FIELDS = {
    "calories": "total_calories",
    "protein": "total_protein",
    "carbs": "total_carbs",
    "sugar": "total_sugar",
    "fat": "total_fat",
    "saturated_fat": "total_saturated_fat",
    "trans_fat": "total_trans_fat",
    "fiber": "total_fiber",
    "sodium": "total_sodium",
}

CONDITION_ALIASES = {
    "糖尿病": "diabetes",
    "血糖管理": "diabetes",
    "痛風": "gout",
    "高尿酸": "gout",
    "高血脂": "hyperlipidemia",
    "膽固醇": "hyperlipidemia",
    "高血壓": "hypertension",
    "鈉控制": "hypertension",
    "慢性腎臟病": "kidney_disease",
    "腎臟病": "kidney_disease",
    "腎臟照護": "kidney_disease",
    "ckd": "kidney_disease",
}


def normalize_conditions(user: dict) -> set:
    raw_conditions = user.get("health_conditions", []) or user.get("healthConditions", [])
    return {
        CONDITION_ALIASES.get(str(condition).strip().lower(), str(condition).strip().lower())
        for condition in raw_conditions
        if str(condition).strip()
    }


def build_nutrition_goal_types(user: dict) -> dict:
    """依疾病調整目標的方向。

    慢性腎臟病的蛋白質目標是 W x 0.6 的「嚴格限量」，方向與一般人的
    「至少要吃到」相反；沿用預設的 minimum_target 會把 114 g 蛋白質
    判成達標，等於給腎病患者相反的建議。
    """
    goal_types = dict(NUTRITION_GOAL_TYPES)
    if "kidney_disease" in normalize_conditions(user):
        goal_types["protein"] = "upper_limit"
    return goal_types


def _number(value, fallback: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _display_number(value: float) -> int | float:
    rounded = round(value, 1)
    return int(rounded) if rounded.is_integer() else rounded


def _progress_status(nutrient: str, consumed: float, target: float, goal_types: dict | None = None) -> str:
    goal_type = (goal_types or NUTRITION_GOAL_TYPES)[nutrient]
    if target <= 0:
        return "within_target" if consumed <= 0 else "over"
    if consumed > target:
        return "over" if goal_type == "upper_limit" else "target_met"
    if consumed >= target * 0.8:
        return "near_limit" if goal_type == "upper_limit" else "near_target"
    return "within_target"


def round_targets_for_display(targets: dict) -> dict:
    return {key: _display_number(value) for key, value in targets.items()}


def calculate_pdf_daily_targets(user: dict) -> dict:
    height_cm = _number(user.get("height"), 170.0)
    weight_kg = _number(user.get("weight"), 65.0)
    if height_cm <= 0:
        height_cm = 170.0
    if weight_kg <= 0:
        weight_kg = 65.0
    daily_calorie_target = _number(
        user.get("daily_calorie_target") or user.get("dailyCalorieTarget"),
        weight_kg * 30,
    )
    
    height_m = height_cm / 100.0
    W = 22.0 * (height_m ** 2)
    if W <= 0:
        W = weight_kg
    
    bmi = weight_kg / (height_m ** 2) if height_m > 0 else 22.0
    is_overweight = bmi >= 24.0
    
    # 決定不同疾病下的每日總熱量需求 E
    conditions = normalize_conditions(user)
    
    e_candidates = []
    if "diabetes" in conditions:
        e_candidates.append(W * 25 if is_overweight else W * 30)
    if "gout" in conditions:
        e_candidates.append(W * 30)
    if "hyperlipidemia" in conditions:
        e_candidates.append(W * 25 if is_overweight else W * 30)
    if "hypertension" in conditions:
        e_candidates.append(W * 30)
    if "kidney_disease" in conditions:
        e_candidates.append(W * 30) # 慢性腎臟病取 30
        
    E = min(e_candidates) if e_candidates else daily_calorie_target
    if E <= 0:
        E = W * 30
        
    # Default baseline daily targets:
    targets = {
        "calories": E,
        "protein": W * 1.0,
        "carbs": (E * 0.50) / 4.0,
        "sugar": (E * 0.05) / 4.0,
        "fat": (E * 0.25) / 9.0,
        "saturated_fat": (E * 0.07) / 9.0,
        "trans_fat": 0.0,
        "fiber": 25.0,
        "sodium": 2000.0,
    }
    
    # Apply matching disease-specific clinical guidelines from PDF:
    # 1. 蛋白質
    protein_vals = []
    if "diabetes" in conditions:
        protein_vals.append(W * 1.0)
    if "gout" in conditions:
        protein_vals.append(W * 1.0)
    if "hyperlipidemia" in conditions:
        protein_vals.append(W * 1.0)
    if "hypertension" in conditions:
        protein_vals.append(W * 1.0)
    if "kidney_disease" in conditions:
        protein_vals.append(W * 0.6) # 嚴格限量 W * 0.6 ~ 0.8
    if protein_vals:
        targets["protein"] = min(protein_vals)
        
    # 2. 總碳水化合物
    carbs_ratios = []
    if "diabetes" in conditions:
        carbs_ratios.append(0.475)
    if "gout" in conditions or "hyperlipidemia" in conditions or "hypertension" in conditions:
        carbs_ratios.append(0.50)
    if "kidney_disease" in conditions:
        carbs_ratios.append(0.60)  # 利用低蛋白澱粉補充
    carbs_ratio = min(carbs_ratios) if carbs_ratios else 0.50
    targets["carbs"] = (E * carbs_ratio) / 4.0
    
    # 3. 精緻糖
    sugar_limit = (E * 0.05) / 4.0
    if "diabetes" in conditions:
        sugar_limit = min(sugar_limit, 25.0)
    targets["sugar"] = sugar_limit
    
    # 4. 總脂肪
    fat_ratio = 0.25
    if "gout" in conditions or "hyperlipidemia" in conditions:
        fat_ratio = min(fat_ratio, 0.25)
    elif "kidney_disease" in conditions:
        fat_ratio = max(fat_ratio, 0.325)
    targets["fat"] = (E * fat_ratio) / 9.0
    
    # 5. 飽和脂肪
    sat_fat_ratio = 0.07
    if "hyperlipidemia" in conditions:
        sat_fat_ratio = 0.07
    elif "gout" in conditions or "kidney_disease" in conditions:
        sat_fat_ratio = 0.10
    targets["saturated_fat"] = (E * sat_fat_ratio) / 9.0
    
    # 6. 反式脂肪
    targets["trans_fat"] = 0.0
    
    # 7. 膳食纖維
    fiber_vals = []
    if "diabetes" in conditions:
        fiber_vals.append(30.0)
    if "gout" in conditions:
        fiber_vals.append(25.0)
    if "hyperlipidemia" in conditions:
        fiber_vals.append(32.5)
    if "hypertension" in conditions:
        fiber_vals.append(30.0)
    if "kidney_disease" in conditions:
        fiber_vals.append(17.5) # 15 ~ 20g
    if fiber_vals:
        if "kidney_disease" in conditions:
            targets["fiber"] = 17.5
        else:
            targets["fiber"] = max(fiber_vals)
            
    # 8. 鈉
    sodium_vals = [2000.0]
    if "kidney_disease" in conditions:
        sodium_vals.append(1500.0)
    targets["sodium"] = min(sodium_vals)
    
    return targets


def build_daily_nutrition_progress(storage, user_id: str, user: dict, now: datetime | None = None) -> dict:
    today = app_today(now)
    records = storage.get_records(user_id, today, limit=500)

    # 根據 PDF 指引動態計算目標值
    targets = calculate_pdf_daily_targets(user)
    goal_types = build_nutrition_goal_types(user)

    consumed = {
        nutrient: sum(_number(record.get(field)) for record in records)
        for nutrient, field in RECORD_TOTAL_FIELDS.items()
    }
    remaining = {
        nutrient: max(0.0, targets[nutrient] - consumed[nutrient])
        for nutrient in targets
    }
    over_by = {
        nutrient: max(0.0, consumed[nutrient] - targets[nutrient])
        for nutrient in targets
    }

    return {
        "date": today,
        "goal_type": goal_types,
        "targets": {key: _display_number(value) for key, value in targets.items()},
        "consumed": {key: _display_number(value) for key, value in consumed.items()},
        "remaining": {key: _display_number(value) for key, value in remaining.items()},
        "over_by": {key: _display_number(value) for key, value in over_by.items()},
        "progress_percent": {
            nutrient: round(consumed[nutrient] / max(0.1, targets[nutrient]) * 100, 1)
            for nutrient in targets
        },
        "status": {
            nutrient: _progress_status(nutrient, consumed[nutrient], targets[nutrient], goal_types)
            for nutrient in targets
        },
    }
