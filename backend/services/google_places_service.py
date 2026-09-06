import os
import time
from concurrent.futures import ThreadPoolExecutor
from math import isfinite
from math import cos, radians, sin, sqrt, atan2
from urllib.parse import urlparse

import requests

from services.app_time_service import app_now


GOOGLE_PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

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


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return radius * c


# Places API (New) 依 field mask 計費，每按一次「更新地圖」就是一次計費請求。
# 同一組座標／半徑／類型在短時間內重複搜尋（重新整理、切分頁、連按）直接吃快取。
_SEARCH_CACHE: dict = {}
SEARCH_CACHE_TTL_SECONDS = 600
SEARCH_CACHE_MAX_ENTRIES = 64


def clear_search_cache() -> None:
    """測試與需要強制重新查詢時使用。"""
    _SEARCH_CACHE.clear()


def _search_cache_key(lat: float, lng: float, radius_km: float, category: str, budget: int, limit: int) -> tuple:
    # 座標取到小數第 3 位（約 100 公尺），走幾步不會重新計費
    return (round(lat, 3), round(lng, 3), round(radius_km, 2), category or "all", budget, limit)


def _search_cache_get(key: tuple):
    entry = _SEARCH_CACHE.get(key)
    if not entry:
        return None
    cached_at, value = entry
    if time.time() - cached_at > SEARCH_CACHE_TTL_SECONDS:
        _SEARCH_CACHE.pop(key, None)
        return None
    return value


def _search_cache_put(key: tuple, value):
    if len(_SEARCH_CACHE) >= SEARCH_CACHE_MAX_ENTRIES:
        oldest = min(_SEARCH_CACHE, key=lambda item: _SEARCH_CACHE[item][0])
        _SEARCH_CACHE.pop(oldest, None)
    _SEARCH_CACHE[key] = (time.time(), value)


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


def _public_http_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _build_place_links(website_url, google_maps_url) -> dict:
    website = _public_http_url(website_url)
    maps_url = _public_http_url(google_maps_url)
    links = {}
    if website:
        links["official_website_url"] = website
        links["menu_link"] = {
            "url": website,
            "source": "google_places_website",
        }
    if maps_url:
        links["google_maps_url"] = maps_url
    return links


def _fetch_legacy_place_links(place_id: str, key: str) -> dict:
    """Get optional public links without allowing a details failure to break discovery."""
    try:
        response = requests.get(
            GOOGLE_PLACES_DETAILS_URL,
            params={
                "key": key,
                "place_id": place_id,
                "fields": "website,url",
                "language": "zh-TW",
            },
            timeout=4,
        )
        if response.status_code != 200:
            return {}
        payload = response.json()
        if payload.get("status") != "OK":
            return {}
        result = payload.get("result") or {}
        return _build_place_links(result.get("website"), result.get("url"))
    except (requests.RequestException, ValueError, TypeError):
        return {}


def _opening_periods(place: dict) -> list[dict]:
    """抽出每週營業時段，統一成 {day, open_minute, close_minute}。

    新版 Places 的 regularOpeningHours.periods 長 
    {"open": {"day": 1, "hour": 7, "minute": 0}, "close": {...}}；
    舊版 Nearby Search 的 opening_hours.periods 用 "0730" 字串。
    兩邊都轉成「星期幾 + 當天第幾分鐘」，缺資料就回空清單代表未知。
    """
    def to_minutes(hour, minute):
        return int(hour) * 60 + int(minute)

    periods = []
    regular = place.get("regular_opening_hours") or {}
    for period in regular.get("periods") or []:
        start, end = period.get("open") or {}, period.get("close") or {}
        if "hour" not in start:
            continue
        # 沒有 close 代表 24 小時營業
        close_minute = to_minutes(end.get("hour", 23), end.get("minute", 59)) if end else 24 * 60
        periods.append({
            "day": int(start.get("day", 0)),
            "open_minute": to_minutes(start.get("hour", 0), start.get("minute", 0)),
            "close_minute": close_minute,
        })
    if periods:
        return periods

    legacy = (place.get("opening_hours") or {}).get("periods") or []
    for period in legacy:
        start, end = period.get("open") or {}, period.get("close") or {}
        raw_open = str(start.get("time", ""))
        if len(raw_open) != 4:
            continue
        raw_close = str(end.get("time", "")) if end else ""
        close_minute = (
            to_minutes(raw_close[:2], raw_close[2:]) if len(raw_close) == 4 else 24 * 60
        )
        periods.append({
            "day": int(start.get("day", 0)),
            "open_minute": to_minutes(raw_open[:2], raw_open[2:]),
            "close_minute": close_minute,
        })
    return periods


def venue_open_at(periods: list, weekday: int, minute: int):
    """店家在某天某個時刻有沒有開。沒有營業時段資料時回 None（不知道）。

    不知道就不能當成沒開——那會把大半店家排除掉；也不能當成有開，
    那就回到「假裝所有店都開著」的老問題。交給呼叫端決定怎麼處理。
    """
    if not periods:
        return None
    for period in periods:
        if int(period.get("day", -1)) != weekday:
            continue
        start = int(period.get("open_minute", 0))
        end = int(period.get("close_minute", 24 * 60))
        if end <= start:  # 跨午夜，例如 18:00~02:00
            if minute >= start or minute < end:
                return True
        elif start <= minute < end:
            return True
    return False


def venue_open_now(periods: list, now=None):
    """用每週營業時段推「現在」開不開。

    Places 的 currentOpeningHours 不一定會回 openNow，但週間時段幾乎都有，
    可以自己算，比直接當成未知能救回更多店家。
    """
    now = now or app_now()
    # Google 的 day 是 0=週日，Python 的 isoweekday 是 1=週一…7=週日
    return venue_open_at(periods, now.isoweekday() % 7, now.hour * 60 + now.minute)


def _score_place(distance_km: float, rating, user_ratings_total, is_open, budget: int, price_level) -> int:
    distance_score = max(0, 42 - int(distance_km * 8))
    rating_score = int(float(rating or 0) * 8)
    popularity_score = min(12, int((int(user_ratings_total or 0) ** 0.5) / 2))
    # 只有「確定營業中」才加分；不知道營業時間的店不該贏過確定有開的店
    open_bonus = 12 if is_open is True else 0
    estimated_price = _price_estimate(price_level)
    budget_score = 10 if estimated_price is None or estimated_price <= budget else -8
    return max(1, min(99, distance_score + rating_score + popularity_score + open_bonus + budget_score))


def _fetch_new_places_api(lat: float, lng: float, radius_m: float, key: str, max_results: int = 20) -> list[dict]:
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        # businessStatus / currentOpeningHours 跟已經要的 rating、priceLevel 同一個
        # 計費級別，加上去不會讓這次請求變貴。
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,places.location,places.types,"
            "places.priceLevel,places.rating,places.userRatingCount,places.websiteUri,"
            "places.googleMapsUri,places.businessStatus,places.currentOpeningHours,"
            "places.regularOpeningHours"
        ),
    }
    payload = {
        "includedTypes": ["restaurant"],
        "maxResultCount": max(1, min(int(max_results), 20)),
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
                    # 之前這裡寫死 open_now=True，等於對每一家店都宣稱「營業中」，
                    # 連已歇業的店也是，而且還白拿排序的營業加分。沒拿到資料就留空。
                    "opening_hours": p.get("currentOpeningHours") or {},
                    "business_status": p.get("businessStatus", ""),
                    # 每週固定營業時段。灌入七天要按用餐時間挑店，
                    # currentOpeningHours 只說「現在」開不開，撐不起這件事。
                    "regular_opening_hours": p.get("regularOpeningHours") or {},
                    "types": p.get("types", []),
                    "website": p.get("websiteUri"),
                    "url": p.get("googleMapsUri"),
                    "_new_places_api": True,
                })
            return results
    except Exception as e:
        print(f"[!] Places API (New) fallback failed: {e}")
    return []


def fetch_google_places_restaurants(lat: float, lng: float, radius_km: float, category: str, budget: int, limit: int = 12) -> list[dict]:
    cache_key = _search_cache_key(lat, lng, radius_km, category, budget, limit)
    cached = _search_cache_get(cache_key)
    if cached is not None:
        print(f"[places] 命中快取，未送出計費請求 ({cache_key})")
        return [dict(restaurant) for restaurant in cached]

    key = get_google_places_api_key()
    radius_m = int(max(500, min(radius_km * 1000, 10000)))
    
    # 先打 Places API (New)：一次請求就把 website / Google Maps 連結一起帶回來，
    # 舊版 Nearby Search 拿不到這些欄位，還要對每一家店再送一次 Place Details（較貴的 SKU）。
    results = _fetch_new_places_api(lat, lng, radius_m, key, max_results=limit)

    if not results:
        print("[Google Places] Places API (New) 沒有結果，改用舊版 Nearby Search")
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
                print(f"[Google Places] 舊版 Nearby Search 失敗 HTTP {response.status_code}")
            else:
                payload = response.json()
                status = payload.get("status")
                if status not in {"OK", "ZERO_RESULTS"}:
                    print(f"[Google Places] 舊版 Nearby Search 失敗：{payload.get('error_message') or status}")
                else:
                    results = payload.get("results", [])
        except Exception as exc:
            print(f"[Google Places] 舊版 Nearby Search 例外：{exc}")
        if not results:
            raise GooglePlacesAPIError(
                "Google Places 兩種 API 都沒有回傳結果，請確認金鑰權限與 Billing 設定。"
            )

    candidates = []
    for place in results:
        geometry = place.get("geometry") or {}
        place_location = geometry.get("location") or {}
        place_lat = place_location.get("lat")
        place_lng = place_location.get("lng")
        if not isinstance(place_lat, (int, float)) or not isinstance(place_lng, (int, float)):
            continue
        if not isfinite(place_lat) or not isfinite(place_lng):
            continue

        # 歇業或暫停營業的店不該出現在推薦裡，也不值得花 Gemini 額度分析菜單
        business_status = str(place.get("business_status") or "").upper()
        if business_status in {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}:
            continue

        distance_km = haversine_km(lat, lng, float(place_lat), float(place_lng))
        opening_hours = place.get("opening_hours") or {}
        # 新版 API 叫 openNow，舊版叫 open_now；兩個都沒有就是「不知道」，
        # 不能當成營業中——那正是先前顯示假「營業中」的原因。
        raw_open = opening_hours.get("open_now", opening_hours.get("openNow"))
        periods = _opening_periods(place)
        if raw_open is None:
            # openNow 沒回時用每週時段自己算，不要輕易放棄成「未知」
            is_open = venue_open_now(periods)
        else:
            is_open = bool(raw_open)
        rating = place.get("rating")
        user_ratings_total = place.get("user_ratings_total")
        price_level = place.get("price_level")
        score = _score_place(distance_km, rating, user_ratings_total, is_open, budget, price_level)
        place_id = place.get("place_id") or place.get("name") or str(len(candidates))
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

        restaurant = {
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
            "opening_periods": periods,
            "rating": rating,
            "user_ratings_total": user_ratings_total,
            "match_score": score,
            "data_source": "google_places",
            "nutrition_available": False,
            "recommended_items": [recommended_item],
            "filtered_items": [],
        }
        candidates.append((restaurant, place))

    candidates.sort(key=lambda item: (-item[0]["match_score"], item[0]["distance_km"]))
    selected_candidates = candidates[:limit]

    # Places API (New) already returns the requested links. Legacy Nearby Search
    # requires a Place Details request, so fetch only the selected nearby venues.
    legacy_candidates = [
        (restaurant, place_id)
        for restaurant, place in selected_candidates
        if not place.get("_new_places_api")
        for place_id in [restaurant.get("google_place_id")]
        if place_id
    ]
    if legacy_candidates:
        with ThreadPoolExecutor(max_workers=min(4, len(legacy_candidates))) as executor:
            futures = {
                restaurant["restaurant_id"]: executor.submit(_fetch_legacy_place_links, place_id, key)
                for restaurant, place_id in legacy_candidates
            }
            for restaurant, _ in legacy_candidates:
                restaurant.update(futures[restaurant["restaurant_id"]].result())

    for restaurant, place in selected_candidates:
        if place.get("_new_places_api"):
            restaurant.update(_build_place_links(place.get("website"), place.get("url")))

    result = [restaurant for restaurant, _ in selected_candidates]
    _search_cache_put(cache_key, [dict(restaurant) for restaurant in result])
    return result
