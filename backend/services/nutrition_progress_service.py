from datetime import datetime, timezone


DEFAULT_DAILY_NUTRITION_TARGETS = {
    "calories": 2100,
    "protein": 130,
    "carbs": 250,
    "fat": 70,
    "sodium": 2000,
    "fiber": 25,
}

NUTRITION_GOAL_TYPES = {
    "calories": "upper_limit",
    "protein": "minimum_target",
    "carbs": "upper_limit",
    "fat": "upper_limit",
    "sodium": "upper_limit",
    "fiber": "minimum_target",
}

RECORD_TOTAL_FIELDS = {
    "calories": "total_calories",
    "protein": "total_protein",
    "carbs": "total_carbs",
    "fat": "total_fat",
    "sodium": "total_sodium",
    "fiber": "total_fiber",
}


def _number(value, fallback: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _display_number(value: float) -> int | float:
    rounded = round(value, 1)
    return int(rounded) if rounded.is_integer() else rounded


def _progress_status(nutrient: str, consumed: float, target: float) -> str:
    if consumed > target:
        return "over" if NUTRITION_GOAL_TYPES[nutrient] == "upper_limit" else "target_met"
    if consumed >= target * 0.8:
        return "near_limit" if NUTRITION_GOAL_TYPES[nutrient] == "upper_limit" else "near_target"
    return "within_target"


def build_daily_nutrition_progress(storage, user_id: str, user: dict, now: datetime | None = None) -> dict:
    current_time = now or datetime.now(timezone.utc)
    today = current_time.strftime("%Y-%m-%d")
    records = storage.get_records(user_id, today, limit=500)

    targets = dict(DEFAULT_DAILY_NUTRITION_TARGETS)
    calorie_target = _number(user.get("daily_calorie_target"), DEFAULT_DAILY_NUTRITION_TARGETS["calories"])
    targets["calories"] = calorie_target if calorie_target > 0 else DEFAULT_DAILY_NUTRITION_TARGETS["calories"]

    consumed = {
        nutrient: sum(_number(record.get(field)) for record in records)
        for nutrient, field in RECORD_TOTAL_FIELDS.items()
    }
    remaining = {
        nutrient: max(0, targets[nutrient] - consumed[nutrient])
        for nutrient in targets
    }
    over_by = {
        nutrient: max(0, consumed[nutrient] - targets[nutrient])
        for nutrient in targets
    }

    return {
        "date": today,
        "goal_type": NUTRITION_GOAL_TYPES,
        "targets": {key: _display_number(value) for key, value in targets.items()},
        "consumed": {key: _display_number(value) for key, value in consumed.items()},
        "remaining": {key: _display_number(value) for key, value in remaining.items()},
        "over_by": {key: _display_number(value) for key, value in over_by.items()},
        "progress_percent": {
            nutrient: round(consumed[nutrient] / targets[nutrient] * 100, 1)
            for nutrient in targets
        },
        "status": {
            nutrient: _progress_status(nutrient, consumed[nutrient], targets[nutrient])
            for nutrient in targets
        },
    }
