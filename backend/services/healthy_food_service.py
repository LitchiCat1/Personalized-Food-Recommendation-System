import json
import os
from datetime import datetime, timezone
from math import cos, radians, sin, sqrt, atan2


def load_restaurant_catalog(base_dir: str) -> list[dict]:
    catalog_path = os.environ.get(
        "RESTAURANT_CATALOG_PATH",
        os.path.join(base_dir, "data", "restaurant_catalog.json"),
    )
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    if not isinstance(catalog, list):
        raise ValueError("restaurant catalog must be a JSON array")
    return catalog


def is_open_now(open_hours: list[str], now: datetime) -> bool:
    current = now.strftime("%H:%M")
    for slot in open_hours:
        start, end = slot.split("-")
        if start <= current <= end:
            return True
    return False


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return radius * c


def build_healthy_food_recommendations(storage, disease_rules: dict, restaurant_catalog: list[dict], user_id: str, params: dict):
    user = storage.get_user(user_id)
    if not user:
        return None

    budget = int(params.get("budget", 150))
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    conditions = user.get("health_conditions", [])
    daily_target = user.get("daily_calorie_target", 2100)

    today = now.strftime("%Y-%m-%d")
    today_records = storage.get_records(user_id, today, limit=500)
    consumed = {
        "calories": sum(r.get("total_calories", 0) for r in today_records),
        "protein": sum(r.get("total_protein", 0) for r in today_records),
        "carbs": sum(r.get("total_carbs", 0) for r in today_records),
        "fat": sum(r.get("total_fat", 0) for r in today_records),
        "sodium": sum(r.get("total_sodium", 0) for r in today_records),
    }
    remaining = {
        "calories": max(0, daily_target - consumed["calories"]),
        "protein": max(0, 130 - consumed["protein"]),
        "carbs": max(0, 250 - consumed["carbs"]),
        "fat": max(0, 70 - consumed["fat"]),
        "sodium": max(0, 2000 - consumed["sodium"]),
    }

    recommendations = []
    filtered_out = []

    for restaurant in restaurant_catalog:
        distance_km = haversine_km(lat, lng, restaurant["lat"], restaurant["lng"])
        if distance_km > 5:
            continue
        if not is_open_now(restaurant["open_hours"], now):
            continue

        for item in restaurant["items"]:
            reasons = []
            if item["price"] > budget:
                reasons.append("超出預算")
            for condition in conditions:
                rules = disease_rules.get(condition, {})
                if "blocked_gi" in rules and item.get("gi") in rules["blocked_gi"]:
                    reasons.append(f"高 GI，不適合{condition}")
                if "max_sodium_per_meal" in rules and item["sodium"] > rules["max_sodium_per_meal"]:
                    reasons.append(f"鈉過高，不適合{condition}")
                if "max_fat_per_meal" in rules and item["fat"] > rules["max_fat_per_meal"]:
                    reasons.append(f"脂肪偏高，不適合{condition}")

            if reasons:
                filtered_out.append({
                    "restaurant_name": restaurant["name"],
                    "item_name": item["name"],
                    "reasons": reasons,
                })
                continue

            budget_score = max(0, 30 - abs(budget - item["price"]))
            distance_score = max(0, 25 - int(distance_km * 6))
            calorie_fit = max(0, 35 - abs(remaining["calories"] - item["calories"]) // 15)
            sodium_score = max(0, 15 - int(item["sodium"] / 80))
            protein_bonus = 8 if item["protein"] >= 25 else 0
            total_score = min(99, budget_score + distance_score + calorie_fit + sodium_score + protein_bonus)

            recommendations.append({
                "restaurant_id": restaurant["restaurant_id"],
                "restaurant_name": restaurant["name"],
                "distance_km": round(distance_km, 2),
                "tags": restaurant["tags"],
                "item_name": item["name"],
                "price": item["price"],
                "calories": item["calories"],
                "protein": item["protein"],
                "carbs": item["carbs"],
                "fat": item["fat"],
                "sodium": item["sodium"],
                "gi": item.get("gi"),
                "match_score": total_score,
                "reasons": [
                    f"符合預算 {budget} 元內",
                    f"距離約 {round(distance_km, 2)} km",
                    f"熱量與剩餘配額契合度高",
                ],
            })

    recommendations.sort(key=lambda item: item["match_score"], reverse=True)
    return {
        "user_id": user_id,
        "budget": budget,
        "location": {"lat": lat, "lng": lng},
        "remaining": remaining,
        "recommended": recommendations[:12],
        "filtered_out": filtered_out[:12],
    }
