from datetime import datetime
from math import cos, radians, sin, sqrt, atan2


RESTAURANT_CATALOG = [
    {
        "restaurant_id": "fp_001",
        "name": "原型健康餐盒",
        "lat": 25.0338,
        "lng": 121.5645,
        "open_hours": ["11:00-20:30"],
        "tags": ["高蛋白", "低鈉", "健康餐盒"],
        "items": [
            {"name": "舒肥雞胸餐盒", "price": 140, "calories": 520, "protein": 38, "carbs": 42, "fat": 12, "sodium": 480, "gi": "low"},
            {"name": "鮭魚藜麥餐盒", "price": 180, "calories": 560, "protein": 34, "carbs": 40, "fat": 18, "sodium": 420, "gi": "low"},
        ],
    },
    {
        "restaurant_id": "fp_002",
        "name": "日光沙拉廚房",
        "lat": 25.0351,
        "lng": 121.5622,
        "open_hours": ["10:30-19:30"],
        "tags": ["沙拉", "低 GI"],
        "items": [
            {"name": "雞胸酪梨沙拉", "price": 155, "calories": 430, "protein": 30, "carbs": 18, "fat": 22, "sodium": 360, "gi": "low"},
            {"name": "豆腐藜麥碗", "price": 135, "calories": 410, "protein": 20, "carbs": 36, "fat": 14, "sodium": 300, "gi": "low"},
        ],
    },
    {
        "restaurant_id": "fp_003",
        "name": "輕湯食堂",
        "lat": 25.0316,
        "lng": 121.5661,
        "open_hours": ["11:00-14:00", "17:00-21:00"],
        "tags": ["湯品", "暖食"],
        "items": [
            {"name": "蒸魚野菜套餐", "price": 170, "calories": 470, "protein": 33, "carbs": 35, "fat": 14, "sodium": 520, "gi": "low"},
            {"name": "蕈菇雞湯麵", "price": 150, "calories": 590, "protein": 28, "carbs": 62, "fat": 16, "sodium": 680, "gi": "medium"},
        ],
    },
    {
        "restaurant_id": "fp_004",
        "name": "晨間好食",
        "lat": 25.0344,
        "lng": 121.5604,
        "open_hours": ["07:00-14:00"],
        "tags": ["早餐", "輕食"],
        "items": [
            {"name": "鮪魚蛋吐司盒", "price": 95, "calories": 390, "protein": 24, "carbs": 34, "fat": 14, "sodium": 430, "gi": "medium"},
            {"name": "燕麥優格水果杯", "price": 85, "calories": 320, "protein": 15, "carbs": 38, "fat": 9, "sodium": 120, "gi": "low"},
        ],
    },
]


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


def build_healthy_food_recommendations(storage, disease_rules: dict, user_id: str, params: dict):
    user = storage.get_user(user_id)
    if not user:
        return None

    budget = int(params.get("budget", 150))
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    now = datetime.utcnow()
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

    for restaurant in RESTAURANT_CATALOG:
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
