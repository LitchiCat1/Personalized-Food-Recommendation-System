from datetime import datetime


def normalize_number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_candidate(label: str, nutrients: dict, source: str) -> dict | None:
    calories = nutrients.get("calories")
    if calories is None:
        return None

    return {
        "label": label,
        "name_zh": nutrients.get("name_zh", label),
        "calories": calories or 0,
        "protein": nutrients.get("protein", 0) or 0,
        "carbs": nutrients.get("carbs", 0) or 0,
        "fat": nutrients.get("fat", 0) or 0,
        "sodium": nutrients.get("sodium", 0) or 0,
        "fiber": nutrients.get("fiber", 0) or 0,
        "gi": nutrients.get("gi"),
        "allergens": nutrients.get("allergens", []) or [],
        "source": source,
    }


def build_custom_candidate(food_doc: dict) -> dict | None:
    base_nutrition = food_doc.get("nutrition_per_100g") or food_doc.get("nutrition_per_serving") or {}
    if not base_nutrition:
        return None
    return build_candidate(
        food_doc.get("food_id", food_doc.get("name_zh", "custom_food")),
        {
            "name_zh": food_doc.get("name_zh"),
            "calories": base_nutrition.get("calories"),
            "protein": base_nutrition.get("protein"),
            "carbs": base_nutrition.get("carbs"),
            "fat": base_nutrition.get("fat"),
            "sodium": base_nutrition.get("sodium"),
            "fiber": base_nutrition.get("fiber"),
            "allergens": food_doc.get("allergens", []),
        },
        food_doc.get("source", "custom-food"),
    )


def build_recommendation_candidates(storage, nutrition_db: dict, tfda_db: dict, user_id: str) -> list[dict]:
    candidates = []
    seen_labels = set()

    for label, nutrients in nutrition_db.items():
        candidate = build_candidate(label, nutrients, nutrients.get("source", "manual-db"))
        if candidate:
            candidates.append(candidate)
            seen_labels.add(candidate["label"])

    for label, nutrients in tfda_db.items():
        if label in seen_labels:
            continue
        candidate = build_candidate(label, nutrients, nutrients.get("source", "TFDA"))
        if candidate:
            candidates.append(candidate)
            seen_labels.add(candidate["label"])

    for food_doc in storage.get_custom_foods(user_id):
        candidate = build_custom_candidate(food_doc)
        if candidate:
            candidates.append(candidate)

    return candidates


def build_preference_profile(records: list[dict]) -> dict:
    foods = []
    source_counts = {}
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "sodium": 0.0}

    for record in records:
        for food in record.get("foods") or []:
            name = (food.get("name") or "").strip()
            if name:
                foods.append(name)
            source = food.get("source") or record.get("source")
            if source:
                source_counts[source] = source_counts.get(source, 0) + 1
            totals["calories"] += normalize_number(food.get("calories"))
            totals["protein"] += normalize_number(food.get("protein"))
            totals["carbs"] += normalize_number(food.get("carbs"))
            totals["fat"] += normalize_number(food.get("fat"))
            totals["sodium"] += normalize_number(food.get("sodium"))

    count = max(1, len(foods))
    avg = {key: value / count for key, value in totals.items()}
    favorite_sources = sorted(source_counts, key=source_counts.get, reverse=True)[:2]

    return {
        "food_names": foods[-30:],
        "avg": avg,
        "favorite_sources": favorite_sources,
        "record_count": len(records),
        "food_count": len(foods),
    }


def compute_preference_score(candidate: dict, profile: dict) -> tuple[int, list[str]]:
    if profile["food_count"] == 0:
        return 0, []

    score = 0
    reasons = []
    name = candidate.get("name_zh", "")
    label = candidate.get("label", "")
    name_pool = profile["food_names"]

    if any(name and (name in food_name or food_name in name) for food_name in name_pool):
        score += 18
        reasons.append("與近期常記錄食品相似")
    elif any(label and label in food_name for food_name in name_pool):
        score += 10
        reasons.append("與近期食品標籤相近")

    avg = profile["avg"]
    calories = normalize_number(candidate.get("calories"))
    if avg["calories"] > 0:
        calorie_gap = abs(avg["calories"] - calories)
        if calorie_gap <= 120:
            score += 12
            reasons.append("熱量接近你的近期餐點")
        elif calorie_gap <= 250:
            score += 6

    protein = normalize_number(candidate.get("protein"))
    if avg["protein"] > 0 and protein >= avg["protein"] * 0.8:
        score += 8
        reasons.append("蛋白質符合近期偏好")

    sodium = normalize_number(candidate.get("sodium"))
    if avg["sodium"] > 0 and sodium <= avg["sodium"]:
        score += 6
        reasons.append("鈉含量不高於近期平均")

    if candidate.get("source") in profile["favorite_sources"]:
        score += 4

    return min(score, 35), reasons[:3]


def build_recommendation_response(storage, nutrition_db: dict, tfda_db: dict, disease_rules: dict, user_id: str):
    user = storage.get_user(user_id)
    if not user:
        return None

    conditions = user.get("health_conditions", [])
    allergens = user.get("allergens", [])
    daily_target = user.get("daily_calorie_target", 2100)

    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_records = storage.get_records(user_id, today, limit=500)
    recent_records = storage.get_records(user_id, limit=50)
    consumed_today = sum(record.get("total_calories", 0) for record in today_records)
    remaining_calories = max(0, daily_target - consumed_today)

    safe_candidates = []
    filtered_out = []
    candidates = build_recommendation_candidates(storage, nutrition_db, tfda_db, user_id)
    preference_profile = build_preference_profile(recent_records)

    for nutrients in candidates:
        label = nutrients["label"]
        food_allergens = nutrients.get("allergens", [])
        gi = nutrients.get("gi")
        is_safe = True
        block_reasons = []

        for allergen in food_allergens:
            if allergen in allergens:
                is_safe = False
                block_reasons.append(f"含過敏原: {allergen}")

        for condition in conditions:
            rules = disease_rules.get(condition, {})
            if "blocked_gi" in rules and gi in rules["blocked_gi"]:
                is_safe = False
                block_reasons.append(f"高 GI — 不適合{condition}患者")
            if "max_sodium_per_meal" in rules and (nutrients.get("sodium") or 0) > rules["max_sodium_per_meal"]:
                is_safe = False
                block_reasons.append(f"高鈉 — 不適合{condition}患者")
            if "blocked_labels" in rules and label in rules["blocked_labels"]:
                is_safe = False
                block_reasons.append(f"不適合{condition}患者")

        if is_safe:
            calories = nutrients.get("calories", 0)
            fit_score = max(0, 100 - abs(remaining_calories - calories) // 8)
            lower_sodium_bonus = max(0, 25 - int((nutrients.get("sodium", 0) or 0) / 80))
            macro_bonus = 0
            if (nutrients.get("protein") or 0) >= 15:
                macro_bonus += 8
            if gi == "low":
                macro_bonus += 10
            elif gi == "medium":
                macro_bonus += 4
            preference_score, preference_reasons = compute_preference_score(nutrients, preference_profile)

            safety_badges = []
            if (nutrients.get("sodium") or 0) <= 400:
                safety_badges.append("低鈉")
            if gi == "low":
                safety_badges.append("低 GI")
            elif gi == "medium":
                safety_badges.append("中 GI")
            if (nutrients.get("protein") or 0) >= 15:
                safety_badges.append("高蛋白")

            safe_candidates.append(
                {
                    "label": label,
                    "name_zh": nutrients.get("name_zh", label),
                    "calories": calories,
                    "protein": nutrients.get("protein", 0),
                    "carbs": nutrients.get("carbs", 0),
                    "fat": nutrients.get("fat", 0),
                    "sodium": nutrients.get("sodium", 0),
                    "gi": gi,
                    "source": nutrients.get("source"),
                    "match_score": min(99, int(fit_score + lower_sodium_bonus + macro_bonus + preference_score)),
                    "preference_score": preference_score,
                    "preference_reasons": preference_reasons,
                    "safety_badges": safety_badges,
                }
            )
        else:
            filtered_out.append(
                {
                    "label": label,
                    "name_zh": nutrients.get("name_zh", label),
                    "reasons": block_reasons,
                }
            )

    safe_candidates.sort(key=lambda x: x["match_score"], reverse=True)
    return {
        "user_id": user_id,
        "remaining_calories": remaining_calories,
        "health_conditions": conditions,
        "recommended": safe_candidates[:10],
        "filtered_out": filtered_out[:12],
        "total_candidates": len(safe_candidates),
        "total_filtered": len(filtered_out),
        "source_counts": {
            "total": len(candidates),
            "manual_db": sum(1 for c in candidates if c.get("source") == "manual-db"),
            "tfda": sum(1 for c in candidates if c.get("source") == "TFDA"),
            "custom_foods": sum(1 for c in candidates if c.get("source") not in {"manual-db", "TFDA"}),
        },
        "preference_profile": {
            "record_count": preference_profile["record_count"],
            "food_count": preference_profile["food_count"],
        },
    }
