import json
import os
from datetime import datetime
from math import atan2, cos, radians, sin, sqrt

from services.app_time_service import app_now
from services.google_places_service import fetch_google_places_restaurants
from services.medical_risk_service import evaluate_medical_risk
from services.nutrient_service import NUTRITION_FIELDS, is_fried_food_name
from services.robust_restaurant_scraper_service import validate_and_balance_nutrition
from services.nutrition_progress_service import build_daily_nutrition_progress
from services.disease_rule_service import load_disease_rules, load_allergen_taxonomy


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
    now = app_now()
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
                "sugar": item.get("sugar"),
                "saturated_fat": item.get("saturated_fat"),
                "trans_fat": item.get("trans_fat"),
                "fiber": item.get("fiber"),
                "is_fried": item.get("is_fried"),
            }
            medical_risk = evaluate_medical_risk(candidate, conditions, allergens, disease_rules, taxonomy, user_profile=user)
            reasons = [f"超出預算 {budget} 元"] if item["price"] > budget else []
            reasons.extend(medical_risk["block_reasons"])

            if reasons:
                filtered_item = {
                    "restaurant_id": restaurant["restaurant_id"],
                    "restaurant_name": restaurant["name"],
                    "item_name": item["name"],
                    "reasons": reasons,
                    "price": item.get("price", 0),
                    "medical_risk": medical_risk,
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

    # Developer convenience fallback: if no restaurants are nearby in local dev catalog,
    # temporarily shift them around the user's location so they can see results.
    if not restaurants:
        for idx, restaurant in enumerate(restaurant_catalog):
            if not _restaurant_matches_category(restaurant, category):
                continue
            
            # Place them in a grid around the user's current location:
            offset_lat = lat + (0.003 if idx % 2 == 0 else -0.003) * (1 + idx // 4)
            offset_lng = lng + (0.003 if (idx // 2) % 2 == 0 else -0.003) * (1 + idx // 4)
            distance_km = haversine_km(lat, lng, offset_lat, offset_lng)
            is_open = True
            
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
                    "sugar": item.get("sugar"),
                    "saturated_fat": item.get("saturated_fat"),
                    "trans_fat": item.get("trans_fat"),
                    "fiber": item.get("fiber"),
                    "is_fried": item.get("is_fried"),
                }
                medical_risk = evaluate_medical_risk(candidate, conditions, allergens, disease_rules, taxonomy, user_profile=user)
                reasons = [f"超出預算 {budget} 元"] if item["price"] > budget else []
                reasons.extend(medical_risk["block_reasons"])

                if reasons:
                    filtered_item = {
                        "restaurant_id": restaurant["restaurant_id"],
                        "restaurant_name": restaurant["name"],
                        "item_name": item["name"],
                        "reasons": reasons,
                        "price": item.get("price", 0),
                        "medical_risk": medical_risk,
                    }
                    filtered_out.append(filtered_item)
                    restaurant_filtered_items.append(filtered_item)
                    continue

                recommended_item = {
                    "restaurant_id": restaurant["restaurant_id"],
                    "restaurant_name": restaurant["name"],
                    "restaurant_lat": offset_lat,
                    "restaurant_lng": offset_lng,
                    "address": restaurant.get("address", "測試路段"),
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
                    "match_score": 95,
                    "reasons": ["營養與安全條件相符"],
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
                    "lat": offset_lat,
                    "lng": offset_lng,
                    "address": restaurant.get("address", "測試路段"),
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


def _venue_allergen_cautions(restaurant: dict, allergens: list, taxonomy: dict) -> list[str]:
    """店名層級的過敏原提醒。

    Places 沒有菜色資料，「生猛海鮮熱炒」不會命中 蝦／蟹 這種菜色關鍵字，
    但店家類型本身就足以提醒使用者點餐時要確認。這裡只給警告不擋掉，
    因為同一家店通常仍有可以吃的品項。
    """
    if not allergens:
        return []
    from services.disease_rule_service import normalize_allergen_ids

    selected = set(normalize_allergen_ids(allergens, taxonomy))
    haystack = f"{restaurant.get('name', '')} {' '.join(str(tag) for tag in restaurant.get('tags', []))}".lower()
    cautions = []
    for group in taxonomy.get("groups", []):
        if group.get("id") not in selected:
            continue
        hit = next((word for word in group.get("venue_keywords", []) if word.lower() in haystack), None)
        if hit:
            cautions.append(f"這家店以「{hit}」為主，你設定了{group.get('label_zh')}過敏，點餐前請向店家確認")
    return cautions


def _places_risk_candidate(restaurant: dict, item: dict) -> dict:
    """用店名 + 店家類型當作比對文字。

    Places 沒有菜色營養，所有營養欄位都是 0，靠的是
    `detect_allergen_hits` 與 `_condition_keyword_hits` 的關鍵字比對。
    """
    tags = " ".join(str(tag) for tag in restaurant.get("tags", []) if tag)
    name = restaurant.get("name", "")
    return {
        "label": item.get("item_id", name),
        "name_zh": f"{name} {tags}".strip(),
        "item_name": item.get("item_name", ""),
        "gi": item.get("gi"),
        "allergens": [],
        "is_fried": is_fried_food_name(name, tags),
        **{nutrient: item.get(nutrient, 0) for nutrient in NUTRITION_FIELDS},
    }


def _number(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _fit_penalty(item: dict, remaining: dict) -> int:
    """這道菜吃下去會不會撐破今天剩下的額度。撐得愈兇扣愈多。"""
    penalty = 0
    # 熱量已經是硬條件（超過今日剩餘就不推薦），這裡只排序剩下的項目
    for nutrient, weight in (("sodium", 18), ("saturated_fat", 8)):
        left = _number(remaining.get(nutrient))
        value = _number(item.get(nutrient))
        if left > 0 and value > left:
            penalty += min(weight, int(weight * (value - left) / left))
    return penalty


def _items_from_indexed_menu(
    storage, restaurant: dict, budget: int, conditions, allergens,
    disease_rules: dict, taxonomy: dict, user: dict, remaining: dict,
):
    """用建檔好的真實菜單挑出這家店可以吃的餐點。

    Places 本身沒有菜色營養，所以原本每家店只掛一個「到店後再選」的佔位
    品項，疾病規則只能拿店名跟店家類型去猜。已經建檔的店有逐道菜的營養，
    就該真的逐道菜篩，這才是「推薦符合疾病禁忌的餐點」。

    沒有建檔的店回 None，交給呼叫端沿用原本的佔位品項。
    """
    cached = storage.get_restaurant_menu(
        restaurant.get("name", ""), restaurant.get("google_place_id", "")
    )
    items = (cached or {}).get("items") or []
    if not items:
        return None

    allowed, blocked = [], []
    for raw in items:
        # 快取存的是模型原始輸出，這裡補上留白的飽和脂肪與糖，跟灌入同一套
        menu_item = validate_and_balance_nutrition(dict(raw))
        name = str(menu_item.get("name") or "餐點")
        price = int(_number(menu_item.get("price")))
        entry = {
            "restaurant_id": restaurant["restaurant_id"],
            "restaurant_name": restaurant["name"],
            "restaurant_lat": restaurant.get("lat"),
            "restaurant_lng": restaurant.get("lng"),
            "address": restaurant.get("address", ""),
            "distance_km": restaurant.get("distance_km", 0),
            "tags": ["Google Places", "真實店家", "已建檔菜單"],
            "item_id": str(menu_item.get("item_id") or f"{restaurant['restaurant_id']}_{name}"),
            "item_name": name,
            "price": price,
            **{nutrient: menu_item.get(nutrient, 0) for nutrient in NUTRITION_FIELDS},
            "is_fried": menu_item.get("is_fried") is True,
            "gi": menu_item.get("gi"),
            "nutrition_available": True,
        }

        if price > budget:
            blocked.append({
                "restaurant_id": restaurant["restaurant_id"],
                "restaurant_name": restaurant["name"],
                "item_name": name,
                "price": price,
                "reasons": [f"超過預算 {budget} 元"],
            })
            continue

        # 吃下去會超過今天剩餘熱量的就不推薦。remaining 已經是
        # max(0, 目標 - 已攝取)，所以 0 代表今天的額度用完了。
        calories_left = _number(remaining.get("calories"))
        calories = _number(menu_item.get("calories"))
        if calories > calories_left:
            blocked.append({
                "restaurant_id": restaurant["restaurant_id"],
                "restaurant_name": restaurant["name"],
                "item_name": name,
                "price": price,
                "reasons": [
                    f"{calories:.0f} kcal 超過今日剩餘熱量 {calories_left:.0f} kcal"
                    if calories_left > 0
                    else "今天的熱量額度已經用完"
                ],
                "over_remaining": True,
            })
            continue

        risk = evaluate_medical_risk(
            {
                "label": entry["item_id"],
                "name_zh": name,
                "gi": menu_item.get("gi"),
                "allergens": menu_item.get("allergens", []),
                "is_fried": entry["is_fried"],
                **{nutrient: menu_item.get(nutrient, 0) for nutrient in NUTRITION_FIELDS},
            },
            conditions, allergens, disease_rules, taxonomy, user_profile=user,
        )
        entry["medical_risk"] = risk
        if risk["block_reasons"]:
            blocked.append({
                "restaurant_id": restaurant["restaurant_id"],
                "restaurant_name": restaurant["name"],
                "item_name": name,
                "price": price,
                "reasons": risk["block_reasons"],
                "medical_risk": risk,
            })
            continue

        entry["match_score"] = max(1, restaurant.get("match_score", 50) - _fit_penalty(entry, remaining))
        entry["reasons"] = [
            f"{restaurant['name']}，距離約 {restaurant.get('distance_km', 0)} km",
            "已建檔菜單，營養由 Gemini 估算，逐道菜比對過疾病禁忌與過敏原",
            *risk["caution_reasons"],
        ]
        allowed.append(entry)

    allowed.sort(key=lambda entry: entry["match_score"], reverse=True)
    return allowed, blocked


def _calorie_note(filtered_out: list, remaining: dict) -> str | None:
    """清單因為熱量額度而變短時，要說出來。

    空清單如果不解釋，看起來就像壞掉，而不是「你今天已經吃夠了」。
    """
    dropped = [entry for entry in filtered_out if entry.get("over_remaining")]
    if not dropped:
        return None
    left = _number(remaining.get("calories"))
    if left <= 0:
        return "今天的熱量額度已經用完，這裡不再推薦餐點。想再吃可以先看趨勢頁確認。"
    return f"今日剩餘熱量 {left:.0f} kcal，{len(dropped)} 道餐點吃下去會超過，已排除。"


def build_google_places_food_recommendations(storage, user_id: str, params: dict):
    user = storage.get_user(user_id)
    if not user:
        return None

    budget = int(params.get("budget", 150))
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    radius_km = min(max(float(params.get("radius_km", 3)), 0.5), 10)
    category = _normalize_category(params.get("category", "all"))
    now = app_now()

    remaining = build_daily_nutrition_progress(storage, user_id, user, now)["remaining"]

    data_source = "google_places"
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    disease_rules = load_disease_rules(base_dir)
    taxonomy = load_allergen_taxonomy(base_dir)
    conditions = user.get("health_conditions", []) or []
    allergens = user.get("allergens", []) or []

    from services.google_places_service import GooglePlacesConfigError
    try:
        restaurants = fetch_google_places_restaurants(lat, lng, radius_km, category, budget, limit=12)
    except GooglePlacesConfigError:
        raise
    except Exception as e:
        print(f"[Google Places API error] {e}. Falling back to coordinate-shifted local catalog.")
        restaurant_catalog = load_restaurant_catalog(base_dir)
        offline_recommendations = build_healthy_food_recommendations(
            storage, disease_rules, restaurant_catalog, user_id, params, taxonomy
        )
        return {
            "user_id": user_id,
            "budget": budget,
            "radius_km": radius_km,
            "category": category or "all",
            "location": {"lat": lat, "lng": lng},
            "remaining": remaining,
            "data_source": "google_places_fallback",
            "nutrition_available": True,
            "nutrition_note": f"Google Places API 載入失敗（可能是 Billing 未啟用或金鑰錯誤）：{e}。已自動為您切換至本地模擬店家以利演示功能。",
            "recommended": offline_recommendations.get("recommended", []),
            "restaurants": offline_recommendations.get("restaurants", []),
            "filtered_out": offline_recommendations.get("filtered_out", []),
        }

    # 推薦是「現在要去吃」，所以現在沒開的店不推薦。
    # 建檔那條路徑不套這個條件——它是為整週準備菜單，晚餐店照樣要建。
    # 拿不到營業時間的店留著：不知道不等於沒開。
    closed_now = [r for r in restaurants if r.get("is_open") is False]
    restaurants = [r for r in restaurants if r.get("is_open") is not False]

    # Google Places 只給店名與店家類型，沒有菜色營養，但店名／類型本身就足以
    # 擋掉明顯衝突的店家（海鮮過敏遇到海產店、高血脂遇到炸雞店）。
    # 之前這條路徑完全沒有套用疾病與過敏原規則，等於「沒有根據不能吃的食物做推薦」。
    recommendations = []
    filtered_out = []
    venues_with_menu = 0
    for restaurant in restaurants:
        # 有建檔菜單的店逐道菜篩，沒有的才退回「靠店名猜」的舊行為
        from_menu = _items_from_indexed_menu(
            storage, restaurant, budget, conditions, allergens, disease_rules, taxonomy, user, remaining
        )
        if from_menu is not None:
            restaurant_allowed, restaurant_blocked = from_menu
            restaurant["recommended_items"] = restaurant_allowed
            restaurant["filtered_items"] = restaurant_blocked
            restaurant["nutrition_available"] = True
            filtered_out.extend(restaurant_blocked)
            recommendations.extend(restaurant_allowed)
            venues_with_menu += 1
            continue

        restaurant_allowed = []
        restaurant_blocked = []
        for item in restaurant.get("recommended_items", []):
            medical_risk = evaluate_medical_risk(
                _places_risk_candidate(restaurant, item),
                conditions,
                allergens,
                disease_rules,
                taxonomy,
                user_profile=user,
            )
            venue_cautions = _venue_allergen_cautions(restaurant, allergens, taxonomy)
            if venue_cautions:
                medical_risk = {
                    **medical_risk,
                    "has_caution": True,
                    "caution_reasons": [*medical_risk["caution_reasons"], *venue_cautions],
                }
            item["medical_risk"] = medical_risk
            if medical_risk["block_reasons"]:
                blocked = {
                    "restaurant_id": restaurant["restaurant_id"],
                    "restaurant_name": restaurant["name"],
                    "item_name": item.get("item_name", restaurant["name"]),
                    "price": item.get("price", 0),
                    "reasons": medical_risk["block_reasons"],
                    "medical_risk": medical_risk,
                }
                restaurant_blocked.append(blocked)
                filtered_out.append(blocked)
            else:
                if medical_risk["caution_reasons"]:
                    item["reasons"] = [*item.get("reasons", []), *medical_risk["caution_reasons"]]
                restaurant_allowed.append(item)

        restaurant["recommended_items"] = restaurant_allowed
        restaurant["filtered_items"] = restaurant_blocked
        recommendations.extend(restaurant_allowed)

    restaurants = [restaurant for restaurant in restaurants if restaurant["recommended_items"]]
    recommendations.sort(key=lambda item: item["match_score"], reverse=True)
    return {
        "user_id": user_id,
        "budget": budget,
        "radius_km": radius_km,
        "category": category or "all",
        "location": {"lat": lat, "lng": lng},
        "remaining": remaining,
        "data_source": "google_places",
        "nutrition_available": venues_with_menu > 0,
        "venues_with_menu": venues_with_menu,
        "calorie_note": _calorie_note(filtered_out, remaining),
        "closed_now": len(closed_now),
        "opening_note": (
            f"附近 {len(closed_now)} 家店現在沒有營業，已排除。"
            if closed_now else None
        ),
        "nutrition_note": (
            f"{venues_with_menu} 家店已建檔菜單，逐道菜比對過疾病禁忌與過敏原；"
            "其餘店家 Google Places 只給店名與類型，僅能用店名比對，到店後請用掃描確認。"
            if venues_with_menu
            else "附近店家都還沒建檔菜單，這裡只用店名與店家類型比對疾病禁忌與過敏原；"
                 "到「我的 → ① 建立附近店家菜單檔案」建檔後才會逐道菜過濾。"
        ),
        "recommended": recommendations[:12],
        "restaurants": restaurants,
        "filtered_out": filtered_out,
    }

