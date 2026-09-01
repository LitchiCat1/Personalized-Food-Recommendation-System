"""一鍵灌入 7 天飲食測試資料。

`--source recommend` 的重點是拿「店家搜尋真的找得到的店」的餐點：
Google Places 找出附近真實店家 → 該店菜單（本地已知菜單，或用 Gemini 即時估算）
→ 過濾預算與疾病禁忌 → 依 match 順序輪流分攤到七天三餐。

沒有 Google Places 金鑰時會退回本地測試餐廳目錄，並在回傳的 `data_source`
標明，不會假裝資料是真實店家來的。
"""

import itertools
import random
import time
from datetime import datetime, timedelta

from services.app_time_service import app_now, get_app_timezone
from services.medical_risk_service import evaluate_medical_risk
from services.nutrient_service import NUTRITION_FIELDS, normalize_nutrition_fields

MEAL_ORDER = ("早餐", "午餐", "晚餐")
MEAL_HOURS = {"早餐": (8, 0), "午餐": (12, 30), "晚餐": (19, 0)}

SEED_SOURCES = ("recommend", "curated")
MAX_DAYS = 14
# 找到的店家沒有菜單時要送去 Gemini 分析，但那是外部呼叫，
# 用「時間預算」而不是固定次數控制，才不會在 Render 上把整個 request 拖到逾時。
MENU_ANALYSIS_BUDGET_SECONDS = 45
MAX_MENU_ANALYSES = 6


def seed_client_record_id(source: str, day, meal_type: str) -> str:
    return f"seed_{source}_{day.strftime('%Y%m%d')}_{meal_type}"


def seed_record_ids(source: str, days: int, end_date) -> list[str]:
    return [
        seed_client_record_id(source, end_date - timedelta(days=offset), meal_type)
        for offset in range(days)
        for meal_type in MEAL_ORDER
    ]


def _number(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _dish_from_item(item: dict, restaurant: dict) -> dict:
    """把菜單品項轉成飲食紀錄用的 food。

    直接吃菜單原始欄位，纖維／糖／飽和脂肪／反式脂肪都留得住；
    走推薦 API 的 response 反而只剩五項。
    """
    dish = {
        "name": f"{item.get('name', '餐點')}（{restaurant.get('name', '未知店家')}）",
        "restaurant_id": restaurant.get("restaurant_id"),
        "restaurant_name": restaurant.get("name"),
        "item_id": item.get("item_id", item.get("name")),
        "price": item.get("price", 0),
        "is_fried": item.get("is_fried") is True,
        **normalize_nutrition_fields(item),
    }
    return dish


def _passes_filters(item: dict, restaurant: dict, budget: int, conditions, allergens, disease_rules, allergen_taxonomy, user) -> bool:
    if _number(item.get("price")) > budget:
        return False
    candidate = {
        "label": item.get("item_id", item.get("name")),
        "name_zh": item.get("name"),
        "gi": item.get("gi"),
        "allergens": item.get("allergens", []),
        "is_fried": item.get("is_fried"),
        **{nutrient: item.get(nutrient) for nutrient in NUTRITION_FIELDS},
    }
    risk = evaluate_medical_risk(candidate, conditions, allergens, disease_rules, allergen_taxonomy, user_profile=user)
    return not risk.get("block_reasons")


def collect_catalog_dishes(restaurant_catalog: list, user: dict, disease_rules: dict, allergen_taxonomy: dict, budget: int) -> list[dict]:
    conditions = user.get("health_conditions", []) or []
    allergens = user.get("allergens", []) or []
    dishes = []
    for restaurant in restaurant_catalog:
        for item in restaurant.get("items", []):
            if _passes_filters(item, restaurant, budget, conditions, allergens, disease_rules, allergen_taxonomy, user):
                dishes.append(_dish_from_item(item, restaurant))
    return dishes


def collect_recommendation_dishes(
    user: dict,
    params: dict,
    restaurant_catalog: list,
    disease_rules: dict,
    allergen_taxonomy: dict,
    fetch_places,
    enrich_restaurant,
) -> tuple[list[dict], str, str]:
    """回傳 (菜色, data_source, 說明)。"""
    budget = int(params.get("budget", 150))
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    radius_km = min(max(float(params.get("radius_km", 3)), 0.5), 10)
    category = str(params.get("category", "all") or "all").strip().lower()

    try:
        places = fetch_places(lat, lng, radius_km, category, budget, limit=6)
    except Exception as error:  # 金鑰未設定、Billing 未開、配額用盡都走這裡
        dishes = collect_catalog_dishes(restaurant_catalog, user, disease_rules, allergen_taxonomy, budget)
        note = f"Google Places 無法使用（{error}），已改用本地測試餐廳目錄，資料不是真實店家。"
        return dishes, "local_catalog_fallback", note

    if not places:
        dishes = collect_catalog_dishes(restaurant_catalog, user, disease_rules, allergen_taxonomy, budget)
        note = "附近沒有搜尋到符合條件的真實店家，已改用本地測試餐廳目錄。"
        return dishes, "local_catalog_fallback", note

    conditions = user.get("health_conditions", []) or []
    allergens = user.get("allergens", []) or []
    catalog_by_name = {str(r.get("name", "")).strip().lower(): r for r in restaurant_catalog}

    def add_dishes(restaurant, items) -> int:
        added = 0
        for item in items:
            if _passes_filters(item, restaurant, budget, conditions, allergens, disease_rules, allergen_taxonomy, user):
                dishes.append(_dish_from_item(item, restaurant))
                added += 1
        return added

    dishes = []
    resolved_restaurants = 0
    enrich_failures = 0

    # 第一輪只用本地已知菜單，不打任何外部 API
    unknown_places = []
    for place in places:
        name = str(place.get("name", "")).strip()
        if not name:
            continue
        known = catalog_by_name.get(name.lower())
        if known and known.get("items"):
            if add_dishes(known, known["items"]):
                resolved_restaurants += 1
        else:
            unknown_places.append((name, place))

    # 第二輪：沒有菜單的店家送去 Gemini 分析。單次分析最壞情況是
    # 「金鑰數 x 模型數」次 20 秒請求，所以用時間預算擋住，湊滿七天份就停。
    target_dishes = params.get("target_dishes") or 21
    deadline = time.monotonic() + MENU_ANALYSIS_BUDGET_SECONDS
    enrich_calls = 0
    for name, place in unknown_places:
        if len(dishes) >= target_dishes or enrich_calls >= MAX_MENU_ANALYSES:
            break
        if time.monotonic() >= deadline:
            print(f"[week-seed] 菜單分析已用滿 {MENU_ANALYSIS_BUDGET_SECONDS}s 預算，剩餘店家略過")
            break
        enrich_calls += 1
        try:
            enriched = enrich_restaurant(name, place.get("address") or "台灣", "")
        except Exception as error:  # 單一店家失敗不該讓整批都拿不到資料
            print(f"[week-seed] {name} 菜單估算失敗: {error}")
            enrich_failures += 1
            continue
        items = enriched.get("items", []) or []
        if not items:
            continue
        restaurant = {
            "restaurant_id": place.get("restaurant_id", f"places_{name}"),
            "name": name,
            "address": place.get("address", ""),
        }
        if add_dishes(restaurant, items):
            resolved_restaurants += 1

    if not dishes:
        dishes = collect_catalog_dishes(restaurant_catalog, user, disease_rules, allergen_taxonomy, budget)
        note = f"搜尋到 {len(places)} 家真實店家，但都沒有取得可用的菜單營養資料，已改用本地測試餐廳目錄。"
        return dishes, "local_catalog_fallback", note

    note = f"取自 Google Places 搜尋到的 {resolved_restaurants} 家真實店家，其中 {enrich_calls} 家沒有現成菜單、由 Gemini 分析後估算營養。"
    if enrich_failures:
        note += f" 另有 {enrich_failures} 家分析失敗略過。"
    return dishes, "google_places", note


def plan_daily_dishes(dish_count: int, days: int, seed: str) -> list[list[int]]:
    """排出每天三餐要吃哪幾道，盡量讓七天彼此都不一樣。

    菜色夠多時直接洗牌切段；菜色少於一週的量時改列舉「可重複的三道組合」，
    優先挑三道都不同的組合，這樣即使只有 3 道菜，七天也不會長得一模一樣。
    """
    meals = len(MEAL_ORDER)
    rng = random.Random(seed)

    if dish_count >= days * meals:
        order = list(range(dish_count))
        rng.shuffle(order)
        return [order[index * meals:(index + 1) * meals] for index in range(days)]

    combos = [list(combo) for combo in itertools.combinations_with_replacement(range(dish_count), meals)]
    rng.shuffle(combos)
    combos.sort(key=lambda combo: -len(set(combo)))  # 先用三道都不同的組合

    plan = [list(combo) for combo in combos[:days]]
    while len(plan) < days:  # 菜色實在太少（例如只有 1~2 道）才會重複
        plan.append(list(combos[len(plan) % len(combos)]))
    for combo in plan:
        rng.shuffle(combo)  # 早午晚的順序也不要固定
    return plan


def build_week_records(user_id: str, dishes: list, days: int, source: str, end_date) -> list[dict]:
    """把菜色發到每天三餐，七天的組合彼此不重複。"""
    tzinfo = get_app_timezone()
    records = []
    plan = plan_daily_dishes(len(dishes), days, f"{user_id}:{source}:{end_date.isoformat()}")
    for day_index, dish_indexes in enumerate(plan):
        day = end_date - timedelta(days=days - 1 - day_index)
        for meal_index, dish_index in enumerate(dish_indexes):
            meal_type = MEAL_ORDER[meal_index]
            dish = dishes[dish_index]
            hour, minute = MEAL_HOURS[meal_type]
            foods = [dict(dish)]
            totals = {
                nutrient: round(sum(_number(food.get(nutrient)) for food in foods), 2)
                for nutrient in NUTRITION_FIELDS
            }
            records.append(
                {
                    "user_id": user_id,
                    "client_record_id": seed_client_record_id(source, day, meal_type),
                    "timestamp": datetime(day.year, day.month, day.day, hour, minute, tzinfo=tzinfo).isoformat(),
                    "meal_type": meal_type,
                    "foods": foods,
                    **{f"total_{nutrient}": total for nutrient, total in totals.items()},
                    "source": "manual",
                }
            )
    records.sort(key=lambda record: record["timestamp"])
    return records


def seed_week_records(
    storage,
    user_id: str,
    user: dict,
    source: str,
    days: int,
    params: dict,
    restaurant_catalog: list,
    disease_rules: dict,
    allergen_taxonomy: dict,
    fetch_places=None,
    enrich_restaurant=None,
) -> dict:
    days = min(max(int(days), 1), MAX_DAYS)
    budget = int(params.get("budget", 150))
    end_date = app_now().date()

    if source == "recommend":
        dishes, data_source, note = collect_recommendation_dishes(
            {**user},
            {**params, "target_dishes": days * len(MEAL_ORDER)},
            restaurant_catalog,
            disease_rules,
            allergen_taxonomy,
            fetch_places,
            enrich_restaurant,
        )
    else:
        dishes = collect_catalog_dishes(restaurant_catalog, user, disease_rules, allergen_taxonomy, budget)
        data_source = "local_catalog"
        note = "取自本地測試餐廳目錄。"

    if not dishes:
        raise ValueError("找不到符合預算與健康條件的餐點，請調高預算或放寬搜尋半徑")

    records = build_week_records(user_id, dishes, days, source, end_date)

    created = 0
    deduplicated = 0
    for record in records:
        saved = storage.insert_record(record)
        if saved.get("_deduplicated"):
            deduplicated += 1
        else:
            created += 1

    return {
        "days": days,
        "records": len(records),
        "created": created,
        "deduplicated": deduplicated,
        "dishes_available": len(dishes),
        "restaurants": len({dish.get("restaurant_name") for dish in dishes}),
        "data_source": data_source,
        "note": note,
        "start_date": (end_date - timedelta(days=days - 1)).strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }


def clear_week_records(storage, user_id: str, days: int, source: str) -> dict:
    days = min(max(int(days), 1), MAX_DAYS)
    end_date = app_now().date()
    # 多清一週，日期跨天之後舊紀錄才不會留下來
    record_ids = seed_record_ids(source, days + 7, end_date)
    removed = sum(1 for record_id in record_ids if storage.delete_record(user_id, record_id))
    return {"removed": removed, "source": source}
