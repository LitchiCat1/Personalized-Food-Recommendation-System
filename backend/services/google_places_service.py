import os
from math import isfinite
from math import cos, radians, sin, sqrt, atan2

import requests


GOOGLE_PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

PLACE_CATEGORY_KEYWORDS = {
    "all": "餐廳 美食 小吃",
    "便當": "便當",
    "小吃": "小吃",
    "早餐": "早餐",
    "飲料": "飲料 手搖 茶",
    "沙拉": "沙拉 健康餐",
}


class GooglePlacesConfigError(Exception):
    pass


class GooglePlacesAPIError(Exception):
    pass


def _haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return radius * c


def get_google_places_api_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise GooglePlacesConfigError("尚未設定 GOOGLE_PLACES_API_KEY")
    return key


def _category_keyword(category: str) -> str:
    normalized = (category or "all").strip().lower()
    return PLACE_CATEGORY_KEYWORDS.get(normalized, category or "restaurant")


def _price_estimate(price_level) -> int | None:
    if price_level is None:
        return None
    try:
        level = int(price_level)
    except (TypeError, ValueError):
        return None
    return {0: 80, 1: 120, 2: 220, 3: 420, 4: 700}.get(level)


def _score_place(distance_km: float, rating, user_ratings_total, is_open: bool, budget: int, price_level) -> int:
    distance_score = max(0, 42 - int(distance_km * 8))
    rating_score = int(float(rating or 0) * 8)
    popularity_score = min(12, int((int(user_ratings_total or 0) ** 0.5) / 2))
    open_bonus = 12 if is_open else 0
    estimated_price = _price_estimate(price_level)
    budget_score = 10 if estimated_price is None or estimated_price <= budget else -8
    return max(1, min(99, distance_score + rating_score + popularity_score + open_bonus + budget_score))


def _fetch_new_places_api(lat: float, lng: float, radius_m: float, key: str) -> list[dict]:
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.priceLevel,places.rating,places.userRatingCount"
    }
    payload = {
        "includedTypes": ["restaurant"],
        "maxResultCount": 12,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": lat,
                    "longitude": lng
                },
                "radius": float(radius_m)
            }
        }
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            places_v1 = data.get("places", [])
            results = []
            for p in places_v1:
                loc = p.get("location") or {}
                name_obj = p.get("displayName") or {}
                
                price_enum = p.get("priceLevel", "")
                price_level = 1
                if "INEXPENSIVE" in price_enum:
                    price_level = 1
                elif "MODERATE" in price_enum:
                    price_level = 2
                elif "EXPENSIVE" in price_enum:
                    price_level = 3
                
                results.append({
                    "geometry": {
                        "location": {
                            "lat": loc.get("latitude"),
                            "lng": loc.get("longitude")
                        }
                    },
                    "name": name_obj.get("text", "附近餐廳"),
                    "vicinity": p.get("formattedAddress", ""),
                    "place_id": p.get("id"),
                    "rating": p.get("rating"),
                    "user_ratings_total": p.get("userRatingCount"),
                    "price_level": price_level,
                    "opening_hours": {"open_now": True},
                    "types": p.get("types", [])
                })
            return results
    except Exception as e:
        print(f"[!] Places API (New) fallback failed: {e}")
    return []


def fetch_google_places_restaurants(lat: float, lng: float, radius_km: float, category: str, budget: int, limit: int = 12) -> list[dict]:
    key = get_google_places_api_key()
    radius_m = int(max(500, min(radius_km * 1000, 10000)))
    
    results = []
    legacy_err_msg = ""
    try:
        response = requests.get(
            GOOGLE_PLACES_NEARBY_URL,
            params={
                "key": key,
                "location": f"{lat},{lng}",
                "radius": radius_m,
                "type": "restaurant",
                "keyword": _category_keyword(category),
                "language": "zh-TW",
            },
            timeout=10,
        )
        if response.status_code != 200:
            legacy_failed = True
            legacy_err_msg = f"HTTP {response.status_code}: {response.text}"
        else:
            payload = response.json()
            status = payload.get("status")
            if status not in {"OK", "ZERO_RESULTS"}:
                legacy_failed = True
                legacy_err_msg = payload.get("error_message") or f"Status {status}"
            else:
                results = payload.get("results", [])
    except Exception as exc:
        legacy_failed = True
        legacy_err_msg = str(exc)

    # Automatic fallback to Google Places API (New) v1 if legacy API is not enabled
    if legacy_failed:
        print(f"[Google Places] Legacy API call failed ({legacy_err_msg}). Trying Places API (New) fallback...")
        results = _fetch_new_places_api(lat, lng, radius_m, key)
        if not results:
            # If both failed, raise the exception with the actual detailed error message
            raise GooglePlacesAPIError(legacy_err_msg or "Google Places API failed. Please check key permissions.")

    restaurants = []
    for place in results:
        geometry = place.get("geometry") or {}
        place_location = geometry.get("location") or {}
        place_lat = place_location.get("lat")
        place_lng = place_location.get("lng")
        if not isinstance(place_lat, (int, float)) or not isinstance(place_lng, (int, float)):
            continue
        if not isfinite(place_lat) or not isfinite(place_lng):
            continue

        distance_km = _haversine_km(lat, lng, float(place_lat), float(place_lng))
        opening_hours = place.get("opening_hours") or {}
        is_open = bool(opening_hours.get("open_now", True))
        rating = place.get("rating")
        user_ratings_total = place.get("user_ratings_total")
        price_level = place.get("price_level")
        score = _score_place(distance_km, rating, user_ratings_total, is_open, budget, price_level)
        place_id = place.get("place_id") or place.get("name") or str(len(restaurants))
        name = place.get("name") or "附近餐廳"

        recommended_item = {
            "restaurant_id": f"google_{place_id}",
            "restaurant_name": name,
            "restaurant_lat": float(place_lat),
            "restaurant_lng": float(place_lng),
            "address": place.get("vicinity", ""),
            "distance_km": round(distance_km, 2),
            "tags": ["Google Places", "真實店家", "營養待確認"],
            "item_id": f"google_{place_id}_visit",
            "item_name": "到店後選擇符合預算的餐點",
            "price": _price_estimate(price_level) or budget,
            "calories": 0,
            "protein": 0,
            "carbs": 0,
            "fat": 0,
            "sodium": 0,
            "gi": None,
            "match_score": score,
            "nutrition_available": False,
            "reasons": [
                f"Google Places 找到的真實店家，距離約 {round(distance_km, 2)} km",
                "Google Places 不提供可靠菜單營養與價格，請到店後用掃描或手動搜尋記錄餐點",
            ],
        }

        restaurants.append({
            "restaurant_id": f"google_{place_id}",
            "name": name,
            "lat": float(place_lat),
            "lng": float(place_lng),
            "address": place.get("vicinity", ""),
            "phone": "",
            "google_place_id": place_id,
            "distance_km": round(distance_km, 2),
            "tags": ["Google Places", "真實店家", *(place.get("types") or [])[:2]],
            "price_level": price_level,
            "is_open": is_open,
            "rating": rating,
            "user_ratings_total": user_ratings_total,
            "match_score": score,
            "data_source": "google_places",
            "nutrition_available": False,
            "recommended_items": [recommended_item],
            "filtered_items": [],
        })

    restaurants.sort(key=lambda item: (-item["match_score"], item["distance_km"]))
    return restaurants[:limit]
