from datetime import datetime, timezone

from services.medical_risk_service import evaluate_medical_risk


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
        reasons.append("matches recent meal names")
    elif any(label and label in food_name for food_name in name_pool):
        score += 10
        reasons.append("shares recent search terms")

    avg = profile["avg"]
    calories = normalize_number(candidate.get("calories"))
    if avg["calories"] > 0:
        calorie_gap = abs(avg["calories"] - calories)
        if calorie_gap <= 120:
            score += 12
            reasons.append("close to recent calorie profile")
        elif calorie_gap <= 250:
            score += 6

    protein = normalize_number(candidate.get("protein"))
    if avg["protein"] > 0 and protein >= avg["protein"] * 0.8:
        score += 8
        reasons.append("similar protein balance")

    sodium = normalize_number(candidate.get("sodium"))
    if avg["sodium"] > 0 and sodium <= avg["sodium"]:
        score += 6
        reasons.append("lower sodium than recent average")

    if candidate.get("source") in profile["favorite_sources"]:
        score += 4

    return min(score, 35), reasons[:3]


def build_feedback_profile(feedback_docs: list[dict]) -> dict:
    by_label = {}
    counts = {"accepted": 0, "skipped": 0, "disliked": 0}

    for doc in feedback_docs:
        action = doc.get("action")
        label = doc.get("item_label")
        if action not in counts or not label:
            continue
        counts[action] += 1
        by_label.setdefault(label, {"accepted": 0, "skipped": 0, "disliked": 0})[action] += 1

    return {
        "by_label": by_label,
        "counts": counts,
        "total": sum(counts.values()),
    }


def compute_feedback_adjustment(candidate: dict, feedback_profile: dict) -> tuple[int, list[str]]:
    stats = feedback_profile.get("by_label", {}).get(candidate.get("label"), {})
    if not stats:
        return 0, []

    score = 0
    reasons = []
    accepted = stats.get("accepted", 0)
    skipped = stats.get("skipped", 0)
    disliked = stats.get("disliked", 0)

    if accepted:
        score += min(18, accepted * 9)
        reasons.append("previously accepted")
    if skipped:
        score -= min(10, skipped * 5)
        reasons.append("previously skipped")
    if disliked:
        score -= min(35, disliked * 18)
        reasons.append("previously disliked")

    return score, reasons[:2]


def build_recommendation_response(storage, nutrition_db: dict, tfda_db: dict, disease_rules: dict, user_id: str, allergen_taxonomy: dict | None = None):
    user = storage.get_user(user_id)
    if not user:
        return None

    conditions = user.get("health_conditions", [])
    allergens = user.get("allergens", [])
    daily_target = user.get("daily_calorie_target", 2100)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_records = storage.get_records(user_id, today, limit=500)
    recent_records = storage.get_records(user_id, limit=50)
    consumed_today = sum(record.get("total_calories", 0) for record in today_records)
    remaining_calories = max(0, daily_target - consumed_today)

    safe_candidates = []
    filtered_out = []
    candidates = build_recommendation_candidates(storage, nutrition_db, tfda_db, user_id)
    preference_profile = build_preference_profile(recent_records)
    feedback_docs = storage.get_recommendation_feedback(user_id, limit=100)
    feedback_profile = build_feedback_profile(feedback_docs)

    taxonomy = allergen_taxonomy or {"groups": []}

    for nutrients in candidates:
        label = nutrients["label"]
        medical_risk = evaluate_medical_risk(nutrients, conditions, allergens, disease_rules, taxonomy, user_profile=user)
        if not medical_risk["is_safe"]:
            filtered_out.append(
                {
                    "label": label,
                    "name_zh": nutrients.get("name_zh", label),
                    "reasons": medical_risk["block_reasons"],
                }
            )
            continue

        calories = nutrients.get("calories", 0)
        fit_score = max(0, 100 - abs(remaining_calories - calories) // 8)
        lower_sodium_bonus = max(0, 25 - int((nutrients.get("sodium", 0) or 0) / 80))
        macro_bonus = 0
        if (nutrients.get("protein") or 0) >= 15:
            macro_bonus += 8
        if nutrients.get("gi") == "low":
            macro_bonus += 10
        elif nutrients.get("gi") == "medium":
            macro_bonus += 4
        preference_score, preference_reasons = compute_preference_score(nutrients, preference_profile)
        feedback_adjustment, feedback_reasons = compute_feedback_adjustment(nutrients, feedback_profile)

        safety_badges = []
        if (nutrients.get("sodium") or 0) <= 400:
            safety_badges.append("low sodium")
        if nutrients.get("gi") == "low":
            safety_badges.append("low GI")
        elif nutrients.get("gi") == "medium":
            safety_badges.append("medium GI")
        if (nutrients.get("protein") or 0) >= 15:
            safety_badges.append("protein rich")

        safe_candidates.append(
            {
                "label": label,
                "name_zh": nutrients.get("name_zh", label),
                "calories": calories,
                "protein": nutrients.get("protein", 0),
                "carbs": nutrients.get("carbs", 0),
                "fat": nutrients.get("fat", 0),
                "sodium": nutrients.get("sodium", 0),
                "gi": nutrients.get("gi"),
                "source": nutrients.get("source"),
                "match_score": max(0, min(99, int(fit_score + lower_sodium_bonus + macro_bonus + preference_score + feedback_adjustment))),
                "preference_score": preference_score,
                "feedback_adjustment": feedback_adjustment,
                "preference_reasons": (feedback_reasons + preference_reasons)[:4],
                "safety_badges": safety_badges,
                "medical_risk": medical_risk,
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
            "feedback_count": feedback_profile["total"],
            "feedback_counts": feedback_profile["counts"],
        },
    }
