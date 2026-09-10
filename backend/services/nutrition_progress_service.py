from datetime import datetime

from services.app_time_service import app_today
from services.profile_service import compute_bmr


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


def _fallback_bmr(user: dict, weight_kg: float, height_cm: float) -> float:
    """profile 沒帶 bmr 時（舊資料，或測試用的精簡 dict）就地補算一次。"""
    gender = str(user.get("gender") or "male")
    age = _number(user.get("age"), 30.0)
    return _number(compute_bmr(gender, weight_kg, height_cm, age), 0.0)


def resolve_energy_factor(activity_multiplier: float) -> int:
    """每公斤理想體重要給幾大卡，依活動量分級。

    先前不分活動量一律 25 或 30，等於把每個人都當成輕度活動：一位選了
    「中等活動」的使用者拿到的每日目標會比他的 BMR 還低。臨床營養的熱量
    需求本來就是依活動量分級開的，這裡照同一組級距對應到 App 既有的
    五個活動量選項（ACTIVITY_LEVELS 的 multiplier）。
    """
    if activity_multiplier <= 1.2:
        return 25  # 久坐／臥床
    if activity_multiplier <= 1.375:
        return 30  # 輕度活動
    if activity_multiplier <= 1.55:
        return 35  # 中等活動
    return 40  # 高度／極高活動


def calculate_pdf_daily_targets(user: dict) -> dict:
    return calculate_daily_targets_with_basis(user)["targets"]


def calculate_daily_targets_with_basis(user: dict) -> dict:
    """算出每日目標，並一併回報「這個數字是怎麼來的」。

    畫面上先前同時存在三個每日熱量（tdee、使用者自填的 daily_calorie_target、
    這裡算出來的疾病目標），彼此打架又沒有任何說明。basis 就是要讓畫面能講清楚
    現在生效的是哪一個、為什麼。
    """
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

    activity_multiplier = _number(user.get("activity_multiplier") or user.get("activityMultiplier"), 1.55)
    energy_factor = resolve_energy_factor(activity_multiplier)
    # 糖尿病與高血脂的指引本身就含減重目標，過重時往下調一級；
    # 痛風／高血壓／腎病則不做這個減量（維持原本的行為）。
    weight_managed_factor = max(energy_factor - 5, 20) if is_overweight else energy_factor

    bmr = _number(user.get("bmr") or user.get("bmr_kcal"), 0.0)
    if bmr <= 0:
        bmr = _fallback_bmr(user, weight_kg, height_cm)

    # 決定不同疾病下的每日總熱量需求 E
    conditions = normalize_conditions(user)

    e_candidates = []
    if "diabetes" in conditions:
        e_candidates.append(W * weight_managed_factor)
    if "gout" in conditions:
        e_candidates.append(W * energy_factor)
    if "hyperlipidemia" in conditions:
        e_candidates.append(W * weight_managed_factor)
    if "hypertension" in conditions:
        e_candidates.append(W * energy_factor)
    if "kidney_disease" in conditions:
        e_candidates.append(W * energy_factor)

    floored_at_bmr = False
    if e_candidates:
        E = min(e_candidates)
        # 疾病目標是 App 幫使用者決定的，不能低到基礎代謝以下；
        # 使用者自己填的數字則尊重他的選擇，不在這裡改。
        if bmr > 0 and E < bmr:
            E = bmr
            floored_at_bmr = True
        target_source = "disease"
    else:
        E = daily_calorie_target
        target_source = "user"

    if E <= 0:
        E = W * energy_factor

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

    basis = {
        "source": target_source,
        "conditions": sorted(conditions),
        "ideal_body_weight": round(W, 1),
        "kcal_per_kg": weight_managed_factor if target_source == "disease" else None,
        "activity_multiplier": activity_multiplier,
        "bmr": round(bmr) if bmr > 0 else None,
        "floored_at_bmr": floored_at_bmr,
        "user_target": round(daily_calorie_target) if daily_calorie_target > 0 else None,
        "is_overweight": is_overweight,
    }

    return {"targets": targets, "basis": basis}


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
