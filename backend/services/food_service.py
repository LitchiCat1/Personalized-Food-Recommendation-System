from datetime import datetime, timezone
import uuid

from services.nutrient_service import get_nutrient_value, is_fried_food_name


def search_foods(storage, tfda_db: dict, query: str, limit: int, user_id: str | None, build_custom_food_search_result):
    q = query.strip()
    q_lower = q.lower()
    results = []

    if user_id:
        for food in storage.get_custom_foods(user_id):
            haystacks = [
                food.get("food_id", ""),
                food.get("name_zh", ""),
                food.get("name_en", ""),
                food.get("brand", ""),
            ]
            if any(q in value or q_lower in value.lower() for value in haystacks if isinstance(value, str)):
                results.append(build_custom_food_search_result(food))
                if len(results) >= limit:
                    return results

    tfda_candidates = []
    for key, food in tfda_db.items():
        if q in key or q in (food.get("name_zh") or "") or q_lower in (food.get("name_en") or "").lower():
            tfda_candidates.append((_score_tfda_match(q, q_lower, key, food), key, food))

    for _, key, food in sorted(tfda_candidates, key=lambda item: item[0])[:limit - len(results)]:
        results.append(
            {
                "key": key,
                "name_zh": food.get("name_zh", key),
                "name_en": food.get("name_en", ""),
                "category": food.get("category", ""),
                "calories": food.get("calories", 0),
                "protein": food.get("protein", 0),
                "fat": food.get("fat", 0),
                "carbs": food.get("carbs", 0),
                "sodium": food.get("sodium", 0),
                "fiber": food.get("fiber", 0),
                "sugar": get_nutrient_value(food, "sugar"),
                "saturated_fat": food.get("saturated_fat") or 0,
                "trans_fat": food.get("trans_fat") or 0,
                "calcium": food.get("calcium") or 0,
                "iron": food.get("iron") or 0,
                "is_fried": food.get("is_fried") is True
                or is_fried_food_name(food.get("name_zh", key), food.get("name_en")),
                "unit": food.get("unit", "per 100g"),
                "source": "TFDA",
                "allergens": food.get("allergens", []) or [],
            }
        )

    return results


def _score_tfda_match(q: str, q_lower: str, key: str, food: dict) -> tuple:
    name_zh = food.get("name_zh", key) or key
    name_en = (food.get("name_en") or "").lower()
    category = food.get("category", "") or ""

    if name_zh == q or key == q:
        match_rank = 0
    elif name_zh.startswith(q) or key.startswith(q):
        match_rank = 1
    elif q in name_zh or q in key:
        match_rank = 2
    elif q_lower and name_en.startswith(q_lower):
        match_rank = 3
    else:
        match_rank = 4

    category_rank = 0 if category == "水果類" else 1
    processed_penalty = sum(token in name_zh for token in ["汁", "飲", "茶", "乳", "發酵", "濃稠", "保久", "餅", "醬"])
    average_bonus = 0 if "平均值" in name_zh else 1
    return (match_rank, category_rank, processed_penalty, average_bonus, len(name_zh), name_zh)


def build_custom_food_doc(data: dict, normalize_nutrition_payload, scale_nutrition_per_100g, extract_number):
    name_zh = (data.get("name_zh") or "").strip()
    if not name_zh:
        raise ValueError("缺少 name_zh")
    user_id = (data.get("user_id") or "").strip()
    if not user_id:
        raise ValueError("缺少 user_id")
    is_fried = data.get("is_fried", False)
    if not isinstance(is_fried, bool):
        raise ValueError("is_fried 必須是布林值")

    nutrition_per_serving = normalize_nutrition_payload(data.get("nutrition_per_serving") or {})
    nutrition_per_100g = normalize_nutrition_payload(data.get("nutrition_per_100g") or {})
    serving_size_g = extract_number(data.get("serving_size_g"))

    if not any(value is not None for value in nutrition_per_serving.values()) and not any(
        value is not None for value in nutrition_per_100g.values()
    ):
        raise ValueError("至少需要一組營養數據")

    if not any(value is not None for value in nutrition_per_100g.values()):
        nutrition_per_100g = scale_nutrition_per_100g(nutrition_per_serving, serving_size_g)

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    return {
        "food_id": data.get("food_id") or f"custom_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "name_zh": name_zh,
        "name_en": (data.get("name_en") or "").strip(),
        "brand": (data.get("brand") or "").strip(),
        "category": data.get("category", "自訂食品"),
        "serving_size_g": serving_size_g,
        "servings_per_container": extract_number(data.get("servings_per_container")),
        "unit": data.get("unit") or ("per 100g" if nutrition_per_100g else "per serving"),
        "nutrition_per_serving": nutrition_per_serving,
        "nutrition_per_100g": nutrition_per_100g,
        "is_fried": is_fried or is_fried_food_name(name_zh, data.get("name_en")),
        "ocr_text": data.get("ocr_text", ""),
        "source": data.get("source", "custom-food"),
        "created_at": data.get("created_at") or now,
        "updated_at": now,
    }
