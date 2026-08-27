import json
import os
from datetime import datetime, timezone
from math import atan2, cos, radians, sin, sqrt

from services.google_places_service import fetch_google_places_restaurants
from services.medical_risk_service import evaluate_medical_risk
from services.nutrition_progress_service import build_daily_nutrition_progress


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


def _normalize_category(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _restaurant_matches_category(restaurant: dict, category: str) -> bool:
    if not category or category == "all":
        return True
    tags = [str(tag).lower() for tag in restaurant.get("tags", [])]
    haystack = [str(restaurant.get("name", "")).lower(), *tags]
    return any(category in value for value in haystack)


def _sort_recommended_item(item: dict) -> tuple:
    return (-item["match_score"], item["price"], item["sodium"])


def build_healthy_food_recommendations(storage, disease_rules: dict, restaurant_catalog: list[dict], user_id: str, params: dict, allergen_taxonomy: dict | None = None):
    user = storage.get_user(user_id)
    if not user:
        return None

    budget = int(params.get("budget", 150))
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    radius_km = min(max(float(params.get("radius_km", 5)), 0.5), 10)
    category = _normalize_category(params.get("category", "all"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    conditions = user.get("health_conditions", [])
    allergens = user.get("allergens", [])

    remaining = build_daily_nutrition_progress(storage, user_id, user, now)["remaining"]

    recommendations = []
    filtered_out = []
    restaurants = []
    taxonomy = allergen_taxonomy or {"groups": []}

    for restaurant in restaurant_catalog:
        if not _restaurant_matches_category(restaurant, category):
            continue

        distance_km = haversine_km(lat, lng, restaurant["lat"], restaurant["lng"])
        if distance_km > radius_km:
            continue
        is_open = is_open_now(restaurant["open_hours"], now)
        if not is_open:
            continue

        restaurant_recommended_items = []
        restaurant_filtered_items = []
        for item in restaurant["items"]:
            candidate = {
                "label": item.get("item_id", item["name"]),
                "name_zh": item["name"],
                "gi": item.get("gi"),
                "allergens": item.get("allergens", []),
                "sodium": item.get("sodium"),
                "carbs": item.get("carbs"),
                "protein": item.get("protein"),
                "fat": item.get("fat"),
            }
            medical_risk = evaluate_medical_risk(candidate, conditions, allergens, disease_rules, taxonomy)
            reasons = [f"超出預算 {budget} 元"] if item["price"] > budget else []
            reasons.extend(medical_risk["block_reasons"])

            if reasons:
                filtered_item = {
                    "restaurant_id": restaurant["restaurant_id"],
                    "restaurant_name": restaurant["name"],
                    "item_name": item["name"],
                    "reasons": reasons,
                }
                filtered_out.append(filtered_item)
                restaurant_filtered_items.append(filtered_item)
                continue

            budget_score = max(0, 30 - abs(budget - item["price"]))
            distance_score = max(0, 25 - int(distance_km * 6))
            calorie_fit = max(0, 35 - abs(remaining["calories"] - item["calories"]) // 15)
            sodium_score = max(0, 15 - int(item["sodium"] / 80))
            protein_bonus = 8 if item["protein"] >= 25 else 0
            total_score = min(99, budget_score + distance_score + calorie_fit + sodium_score + protein_bonus)

            recommended_item = {
                "restaurant_id": restaurant["restaurant_id"],
                "restaurant_name": restaurant["name"],
                "restaurant_lat": restaurant["lat"],
                "restaurant_lng": restaurant["lng"],
                "address": restaurant.get("address", ""),
                "distance_km": round(distance_km, 2),
                "tags": restaurant["tags"],
                "item_id": item.get("item_id", item["name"]),
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
                    f"符合預算 {budget} 元",
                    f"距離約 {round(distance_km, 2)} km",
                    "營養與安全條件相符",
                ],
                "medical_risk": medical_risk,
            }
            recommendations.append(recommended_item)
            restaurant_recommended_items.append(recommended_item)

        if restaurant_recommended_items:
            restaurant_recommended_items.sort(key=_sort_recommended_item)
            best_score = restaurant_recommended_items[0]["match_score"]
            restaurants.append({
                "restaurant_id": restaurant["restaurant_id"],
                "name": restaurant["name"],
                "lat": restaurant["lat"],
                "lng": restaurant["lng"],
                "address": restaurant.get("address", ""),
                "phone": restaurant.get("phone", ""),
                "google_place_id": restaurant.get("google_place_id", ""),
                "distance_km": round(distance_km, 2),
                "tags": restaurant["tags"],
                "price_level": restaurant.get("price_level"),
                "is_open": is_open,
                "match_score": best_score,
                "recommended_items": restaurant_recommended_items[:4],
                "filtered_items": restaurant_filtered_items[:4],
            })

    recommendations.sort(key=lambda item: item["match_score"], reverse=True)
    restaurants.sort(key=lambda item: (-item["match_score"], item["distance_km"]))
    return {
        "user_id": user_id,
        "budget": budget,
        "radius_km": radius_km,
        "category": category or "all",
        "location": {"lat": lat, "lng": lng},
        "remaining": remaining,
        "recommended": recommendations[:12],
        "restaurants": restaurants[:12],
        "filtered_out": filtered_out[:12],
    }


def build_google_places_food_recommendations(storage, user_id: str, params: dict):
    user = storage.get_user(user_id)
    if not user:
        return None

    budget = int(params.get("budget", 150))
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    radius_km = min(max(float(params.get("radius_km", 3)), 0.5), 10)
    category = _normalize_category(params.get("category", "all"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    remaining = build_daily_nutrition_progress(storage, user_id, user, now)["remaining"]

    restaurants = fetch_google_places_restaurants(lat, lng, radius_km, category, budget, limit=12)
    recommendations = [item for restaurant in restaurants for item in restaurant.get("recommended_items", [])]
    recommendations.sort(key=lambda item: item["match_score"], reverse=True)
    return {
        "user_id": user_id,
        "budget": budget,
        "radius_km": radius_km,
        "category": category or "all",
        "location": {"lat": lat, "lng": lng},
        "remaining": remaining,
        "data_source": "google_places",
        "nutrition_available": False,
        "nutrition_note": "Google Places does not expose nutritional data; use it for location discovery only.",
        "recommended": recommendations[:12],
        "restaurants": restaurants,
        "filtered_out": [],
    }
