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
# 灌入只剩 recommend，但刪除仍要能清掉舊版 curated 灌進去的紀錄
CLEARABLE_SOURCES = ("recommend", "curated")
MAX_DAYS = 14
# 找到的店家沒有菜單時要送去 Gemini 分析，但那是外部呼叫，
# 用「時間預算」而不是固定次數控制，才不會在 Render 上把整個 request 拖到逾時。
MENU_ANALYSIS_BUDGET_SECONDS = 75
MAX_MENU_ANALYSES = 6
# 一餐只放一道單品時，蛋白質與纖維的每日下限幾乎不可能達成
# （真人一餐也會配青菜、配湯）。允許一餐多道，並限制上限避免變成暴食。
MAX_DISHES_PER_MEAL = 3
MAX_DISHES_PER_DAY = 7


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
    storage=None,
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
    cache_hits = 0

    # 第一輪不打任何外部 API：先用資料庫裡分析過的菜單，再用目錄裡的
    unknown_places = []
    for place in places:
        name = str(place.get("name", "")).strip()
        if not name:
            continue
        cached = storage.get_restaurant_menu(name) if storage else None
        known = cached or catalog_by_name.get(name.lower())
        if known and known.get("items"):
            if add_dishes({**known, "name": name}, known["items"]):
                resolved_restaurants += 1
                if cached:
                    cache_hits += 1
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
            enriched = enrich_restaurant(name, place.get("address") or "台灣", "", deadline)
        except Exception as error:  # 單一店家失敗不該讓整批都拿不到資料
            print(f"[week-seed] {name} 菜單估算失敗: {error}")
            enrich_failures += 1
            continue
        items = enriched.get("items", []) or []
        if not items:
            continue
        if storage:
            # 存起來，下一次同一家店就不用再等 Gemini
            storage.save_restaurant_menu(name, items)
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

    note = f"共 {resolved_restaurants} 家店有可用餐點"
    if cache_hits:
        note += f"（其中 {cache_hits} 家直接用之前分析過的菜單快取）"
    note += f"，這次向 Gemini 分析了 {enrich_calls} 家。"
    if enrich_failures:
        note += f" 另有 {enrich_failures} 家分析失敗略過。"
    return dishes, "google_places", note


def day_totals(dishes: list, combo) -> dict:
    totals = {nutrient: 0.0 for nutrient in NUTRITION_FIELDS}
    for index in combo:
        for nutrient in NUTRITION_FIELDS:
            totals[nutrient] += _number(dishes[index].get(nutrient))
    return totals


def score_day(dishes: list, combo, targets: dict, goal_types: dict) -> tuple[int, float]:
    """一天三餐加總後，符合幾項每日目標。

    回傳 (符合項數, 違規總幅度)。違規幅度用來在符合項數相同時分高下，
    例如同樣差一項，鈉超標 50 mg 比超標 800 mg 好。
    """
    totals = day_totals(dishes, combo)

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


def _best_addition(dishes: list, combo: list, targets: dict, goal_types: dict, order=None):
    """挑一道加進來後最有幫助、且不會撐破任何上限的菜。

    `order` 決定同分時先看哪一道。每天給不同的順序，營養值相同的菜色
    才不會讓七天全部收斂成同一組。
    """
    passed, shortfall = score_day(dishes, combo, targets, goal_types)
    best = None
    for index in (order if order is not None else range(len(dishes))):
        candidate = combo + [index]
        totals = day_totals(dishes, candidate)
        if any(
            goal_types[nutrient] == "upper_limit" and totals[nutrient] > _number(targets.get(nutrient))
            for nutrient in NUTRITION_FIELDS
        ):
            continue
        score = score_day(dishes, candidate, targets, goal_types)
        improves = score[0] > passed or (score[0] == passed and score[1] < shortfall - 1e-9)
        if not improves:
            continue
        if best is None or (score[0], -score[1]) > (best[0][0], -best[0][1]):
            best = (score, index)
    return best[1] if best else None


def _least_harmful_addition(dishes: list, combo: list, targets: dict, goal_types: dict) -> int:
    """一定要再加一道時，挑破壞最小的那道。"""
    return min(
        range(len(dishes)),
        key=lambda index: score_day(dishes, combo + [index], targets, goal_types)[1],
    )


def _build_day(dishes: list, targets: dict, goal_types: dict, first_index: int, order=None) -> list:
    """從一道菜開始，每次加最有幫助的一道，直到全部達標或加不動。

    不先固定「三道主餐」再補配菜——那樣熱量與鈉會先被主餐吃光，
    之後任何青菜都會撐破上限，纖維永遠補不起來。
    """
    meals = len(MEAL_ORDER)
    combo = [first_index]
    while len(combo) < MAX_DISHES_PER_DAY:
        if len(combo) >= meals and score_day(dishes, combo, targets, goal_types)[0] == len(NUTRITION_FIELDS):
            break
        addition = _best_addition(dishes, combo, targets, goal_types, order)
        if addition is None:
            # 三餐都要有東西吃，湊不滿時只能挑破壞最小的，
            # 而且要真的加進 combo 才會被計分（先前是在分餐時複製，等於沒算到）
            if len(combo) < meals:
                combo.append(_least_harmful_addition(dishes, combo, targets, goal_types))
                continue
            break
        combo.append(addition)
    return combo


def _split_into_meals(combo: list, rng: random.Random) -> list[list[int]]:
    """把一天的菜色分到三餐，每餐至少一道，且不超過 MAX_DISHES_PER_MEAL。"""
    meals = len(MEAL_ORDER)
    shuffled = list(combo)
    rng.shuffle(shuffled)
    plate = [[shuffled[index]] for index in range(min(meals, len(shuffled)))]
    while len(plate) < meals:  # _build_day 保證至少三道，這裡只是保險
        plate.append([shuffled[-1]])
    for index in shuffled[meals:]:
        target_meal = min(plate, key=len)
        if len(target_meal) >= MAX_DISHES_PER_MEAL:
            break
        target_meal.append(index)
    return plate


def _vary_day(combo: list, rotation, seen: set):
    """把一天的其中一道換掉，換出一組還沒用過的組合。"""
    for position in range(len(combo)):
        for replacement in rotation:
            candidate = combo[:position] + [replacement] + combo[position + 1:]
            key = tuple(sorted(candidate))
            if key not in seen:
                return candidate, key
    return combo, None


def plan_daily_dishes(dishes: list, days: int, seed: str, targets: dict, goal_types: dict) -> list[list[list[int]]]:
    """排出每天三餐吃哪些菜，優先讓整天加總符合疾病別的每日目標。

    回傳 [天][餐] = 該餐的菜色索引清單。一餐可以配多道
    （例如主餐 + 一份青菜），否則蛋白質與纖維的下限幾乎不可能達成。
    """
    rng = random.Random(seed)
    dish_count = len(dishes)
    if dish_count == 0:
        return []

    # 每天從不同的菜開始長，天與天才不會長得一樣
    starts = list(range(dish_count))
    rng.shuffle(starts)

    plan = []
    seen = set()
    for offset in range(dish_count * 2):
        if len(plan) == days:
            break
        start = starts[offset % dish_count]
        # 每天用不同的候選順序，營養一樣的菜色才不會七天長成同一組
        rotation = starts[offset % dish_count:] + starts[:offset % dish_count]
        combo = _build_day(dishes, targets, goal_types, start, rotation)
        key = tuple(sorted(combo))
        if key in seen:
            # 菜色營養一樣時貪婪法會收斂成同一組，換掉其中一道湊出不同的一天
            combo, key = _vary_day(combo, rotation, seen)
            if key is None:
                continue
        seen.add(key)
        plan.append(combo)

    while len(plan) < days:  # 菜色太少時只能重複
        plan.append(list(plan[len(plan) % max(len(plan), 1)]) if plan else [0])

    return [_split_into_meals(combo, rng) for combo in plan[:days]]


def build_week_records(user_id: str, dishes: list, days: int, source: str, end_date, user: dict) -> list[dict]:
    """把菜色發到每天三餐，盡量符合疾病別每日目標，且七天彼此不重複。"""
    tzinfo = get_app_timezone()
    targets = calculate_pdf_daily_targets(user)
    goal_types = build_nutrition_goal_types(user)
    records = []
    plan = plan_daily_dishes(dishes, days, f"{user_id}:{source}:{end_date.isoformat()}", targets, goal_types)
    for day_index, meal_plan in enumerate(plan):
        day = end_date - timedelta(days=days - 1 - day_index)
        for meal_index, dish_indexes in enumerate(meal_plan):
            meal_type = MEAL_ORDER[meal_index]
            hour, minute = MEAL_HOURS[meal_type]
            foods = [dict(dishes[dish_index]) for dish_index in dish_indexes]
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
        storage,
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
    by_day = {}
    for record in records:
        by_day.setdefault(record["timestamp"][:10], []).extend(record["foods"])
    fully_compliant = sum(
        1
        for day_foods in by_day.values()
        if score_day(day_foods, range(len(day_foods)), targets, goal_types)[0] == len(NUTRITION_FIELDS)
    )

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
