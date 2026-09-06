"""一鍵灌入 7 天飲食測試資料。

`--source recommend` 的重點是拿「店家搜尋真的找得到的店」的餐點：
Google Places 找出附近真實店家 → 該店菜單（本地已知菜單，或用 Gemini 即時估算）
→ 過濾預算與疾病禁忌 → 依 match 順序輪流分攤到七天三餐。

只使用真實店家的資料。本地 `restaurant_catalog.json` 的纖維／糖／飽和脂肪
是佔位值，灌進去會讓達標判定失真，所以拿不到真實菜單時直接報錯說明原因，
不會退回本地目錄充數。
"""

import itertools
import random
import time
from datetime import datetime, timedelta

from services.app_time_service import app_now, get_app_timezone
from services.medical_risk_service import evaluate_medical_risk
from services.nutrient_service import NUTRITION_FIELDS, normalize_nutrition_fields
from services.nutrition_progress_service import build_nutrition_goal_types, calculate_pdf_daily_targets

MEAL_ORDER = ("早餐", "午餐", "晚餐")
MEAL_HOURS = {"早餐": (8, 0), "午餐": (12, 30), "晚餐": (19, 0)}

SEED_SOURCES = ("recommend",)
MAX_DAYS = 14
# 找到的店家沒有菜單時要送去 Gemini 分析，但那是外部呼叫，
# 用「時間預算」而不是固定次數控制，才不會在 Render 上把整個 request 拖到逾時。
MENU_ANALYSIS_BUDGET_SECONDS = 75
MAX_MENU_ANALYSES = 6


class SeedDataUnavailable(Exception):
    """拿不到真實店家菜單。訊息會原樣顯示給使用者，要寫得能照著處理。"""


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
        raise SeedDataUnavailable(f"店家搜尋失敗，無法取得真實店家：{error}") from error

    if not places:
        raise SeedDataUnavailable(
            f"半徑 {radius_km} km 內搜尋不到店家，請調整定位或把半徑放大。"
        )

    conditions = user.get("health_conditions", []) or []
    allergens = user.get("allergens", []) or []
    # 目錄裡混了兩種東西：內建的 20 家測試店（纖維／糖是佔位值，不能用），
    # 以及 /restaurant/menu 分析真實店家後寫回來的快取（可以用，還能省一次 Gemini）。
    # 只認後者，靠 restaurant_id 前綴或 AI 標記分辨。
    catalog_by_name = {
        str(r.get("name", "")).strip().lower(): r
        for r in restaurant_catalog
        if str(r.get("restaurant_id", "")).startswith(("scraped_", "google_", "places_"))
        or "AI標記" in (r.get("tags") or [])
    }

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
        reason = "菜單分析沒有回傳可用餐點"
        if enrich_failures:
            reason = f"{enrich_failures} 家的菜單分析失敗"
        raise SeedDataUnavailable(
            f"搜尋到 {len(places)} 家店，但{reason}（常見原因是 Gemini 配額用盡或逾時），"
            f"也可能是所有餐點都超過 {budget} 元或被健康條件擋掉。請稍後再試或調高預算。"
        )

    note = (
        f"分析了 {enrich_calls} 家沒有現成菜單的店家，"
        f"共 {resolved_restaurants} 家有可用餐點（營養由 Gemini 估算）。"
    )
    if enrich_failures:
        note += f" 另有 {enrich_failures} 家分析失敗略過。"
    return dishes, "google_places", note


def score_day(dishes: list, combo, targets: dict, goal_types: dict) -> tuple[int, float]:
    """一天三餐加總後，符合幾項每日目標。

    回傳 (符合項數, 違規總幅度)。違規幅度用來在符合項數相同時分高下，
    例如同樣差一項，鈉超標 50 mg 比超標 800 mg 好。
    """
    totals = {nutrient: 0.0 for nutrient in NUTRITION_FIELDS}
    for index in combo:
        for nutrient in NUTRITION_FIELDS:
            totals[nutrient] += _number(dishes[index].get(nutrient))

    passed = 0
    shortfall = 0.0
    for nutrient in NUTRITION_FIELDS:
        target = _number(targets.get(nutrient))
        actual = totals[nutrient]
        if goal_types[nutrient] == "upper_limit":
            if actual <= target:
                passed += 1
            else:
                shortfall += (actual - target) / max(target, 1.0)
        else:
            if actual >= target:
                passed += 1
            else:
                shortfall += (target - actual) / max(target, 1.0)
    return passed, shortfall


def plan_daily_dishes(dishes: list, days: int, seed: str, targets: dict, goal_types: dict) -> list[list[int]]:
    """排出每天三餐，優先讓「整天加總」符合疾病別的每日目標。

    只擋掉違規的單道菜是不夠的：鈉、纖維、糖這些是以「一天」為單位判定的，
    三道各自合格的菜加起來仍可能超標。這裡列舉三道菜的組合、依符合的目標
    項數排序，再挑出彼此不同的 N 天。
    """
    meals = len(MEAL_ORDER)
    rng = random.Random(seed)
    dish_count = len(dishes)
    if dish_count == 0:
        return []

    combos = [list(combo) for combo in itertools.combinations_with_replacement(range(dish_count), meals)]
    rng.shuffle(combos)  # 同分時的順序要穩定但不固定偏向前面的菜
    scored = []
    for combo in combos:
        passed, shortfall = score_day(dishes, combo, targets, goal_types)
        # 同分時偏好三道都不一樣的組合
        scored.append((-passed, shortfall, -len(set(combo)), combo))
    scored.sort(key=lambda item: item[:3])

    plan = []
    used = set()
    for _, _, _, combo in scored:
        key = tuple(sorted(combo))
        if key in used:
            continue
        used.add(key)
        plan.append(list(combo))
        if len(plan) == days:
            break

    while len(plan) < days:  # 菜色太少時只能重複
        plan.append(list(scored[len(plan) % len(scored)][3]))

    for combo in plan:
        rng.shuffle(combo)  # 早午晚順序不要固定
    return plan


def build_week_records(user_id: str, dishes: list, days: int, source: str, end_date, user: dict) -> list[dict]:
    """把菜色發到每天三餐，盡量符合疾病別每日目標，且七天彼此不重複。"""
    tzinfo = get_app_timezone()
    targets = calculate_pdf_daily_targets(user)
    goal_types = build_nutrition_goal_types(user)
    records = []
    plan = plan_daily_dishes(dishes, days, f"{user_id}:{source}:{end_date.isoformat()}", targets, goal_types)
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

    dishes, data_source, note = collect_recommendation_dishes(
        {**user},
        {**params, "target_dishes": days * len(MEAL_ORDER)},
        restaurant_catalog,
        disease_rules,
        allergen_taxonomy,
        fetch_places,
        enrich_restaurant,
    )

    records = build_week_records(user_id, dishes, days, source, end_date, user)

    created = 0
    deduplicated = 0
    for record in records:
        saved = storage.insert_record(record)
        if saved.get("_deduplicated"):
            deduplicated += 1
        else:
            created += 1

    targets = calculate_pdf_daily_targets(user)
    goal_types = build_nutrition_goal_types(user)
    fully_compliant = 0
    for day_index in range(days):
        day_records = records[day_index * len(MEAL_ORDER):(day_index + 1) * len(MEAL_ORDER)]
        combo_dishes = [record["foods"][0] for record in day_records]
        passed, _ = score_day(combo_dishes, range(len(combo_dishes)), targets, goal_types)
        if passed == len(NUTRITION_FIELDS):
            fully_compliant += 1

    return {
        "days": days,
        "records": len(records),
        "fully_compliant_days": fully_compliant,
        "conditions": user.get("health_conditions", []) or [],
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
