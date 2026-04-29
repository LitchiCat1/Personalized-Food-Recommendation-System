from datetime import datetime
import uuid


def search_foods(storage, tfda_db: dict, query: str, limit: int, user_id: str | None, build_custom_food_search_result):
    q = query.strip()
    q_lower = q.lower()
    results = []

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

    for key, food in tfda_db.items():
        if q in key or q in (food.get("name_zh") or "") or q_lower in (food.get("name_en") or "").lower():
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
                    "unit": food.get("unit", "per 100g"),
                    "source": "TFDA",
                }
            )
            if len(results) >= limit:
                break

    return results


def build_custom_food_doc(data: dict, normalize_nutrition_payload, scale_nutrition_per_100g, extract_number):
    name_zh = (data.get("name_zh") or "").strip()
    if not name_zh:
        raise ValueError("缺少 name_zh")

    nutrition_per_serving = normalize_nutrition_payload(data.get("nutrition_per_serving") or {})
    nutrition_per_100g = normalize_nutrition_payload(data.get("nutrition_per_100g") or {})
    serving_size_g = extract_number(data.get("serving_size_g"))

    if not any(value is not None for value in nutrition_per_serving.values()) and not any(
        value is not None for value in nutrition_per_100g.values()
    ):
        raise ValueError("至少需要一組營養數據")

    if not any(value is not None for value in nutrition_per_100g.values()):
        nutrition_per_100g = scale_nutrition_per_100g(nutrition_per_serving, serving_size_g)

    now = datetime.utcnow().isoformat()
    return {
        "food_id": data.get("food_id") or f"custom_{uuid.uuid4().hex[:10]}",
        "user_id": data.get("user_id", "demo_user"),
        "name_zh": name_zh,
        "name_en": (data.get("name_en") or "").strip(),
        "brand": (data.get("brand") or "").strip(),
        "category": data.get("category", "自訂食品"),
        "serving_size_g": serving_size_g,
        "servings_per_container": extract_number(data.get("servings_per_container")),
        "unit": data.get("unit") or ("per 100g" if nutrition_per_100g else "per serving"),
        "nutrition_per_serving": nutrition_per_serving,
        "nutrition_per_100g": nutrition_per_100g,
        "ocr_text": data.get("ocr_text", ""),
        "source": data.get("source", "custom-food"),
        "created_at": data.get("created_at") or now,
        "updated_at": now,
    }
