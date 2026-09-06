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
from collections import Counter
from datetime import datetime, timedelta

from services.app_time_service import app_now, get_app_timezone
from services.medical_risk_service import evaluate_medical_risk
from services.nutrient_service import NUTRITION_FIELDS, normalize_nutrition_fields
from services.robust_restaurant_scraper_service import validate_and_balance_nutrition
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

    快取存的是模型的原始輸出，所以在這裡再跑一次一致性校正：已經建檔的
    店家不必重新分析，也能補上模型留白的飽和脂肪與糖。校正是冪等的，
    對建檔時就已經校正過的資料不會再動。
    """
    item = validate_and_balance_nutrition(dict(item))
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


_BLOCK_LABELS = {
    "calories": "單餐熱量超標",
    "sodium": "單餐鈉超標",
    "protein": "單餐蛋白質超標",
    "fat": "單餐脂肪超標",
    "saturated_fat": "飽和脂肪超標",
    "trans_fat": "含反式脂肪",
    "carbs": "單餐碳水超標",
    "sugar": "精緻糖超標",
}


def _block_reason(item: dict, restaurant: dict, budget: int, conditions, allergens, disease_rules, allergen_taxonomy, user) -> str | None:
    """回傳擋掉這道菜的原因；通過就回 None。

    只回 True/False 的話，看到「30 道只剩 3 道」也不知道是預算太緊、
    過敏原、還是疾病規則的單餐上限，沒辦法決定下一步該調什麼。
    """
    if _number(item.get("price")) > budget:
        return f"超過預算 {budget} 元"
    candidate = {
        "label": item.get("item_id", item.get("name")),
        "name_zh": item.get("name"),
        "gi": item.get("gi"),
        "allergens": item.get("allergens", []),
        "is_fried": item.get("is_fried"),
        **{nutrient: item.get(nutrient) for nutrient in NUTRITION_FIELDS},
    }
    risk = evaluate_medical_risk(candidate, conditions, allergens, disease_rules, allergen_taxonomy, user_profile=user)
    blocks = [entry for entry in risk.get("risks", []) if entry.get("severity") == "block"]
    if not blocks:
        return None
    first = blocks[0]
    if first.get("type") == "allergen":
        return "過敏原"
    nutrient = first.get("nutrient")
    return _BLOCK_LABELS.get(nutrient, first.get("type") or "疾病條件")


def _passes_filters(item: dict, restaurant: dict, budget: int, conditions, allergens, disease_rules, allergen_taxonomy, user) -> bool:
    return _block_reason(item, restaurant, budget, conditions, allergens, disease_rules, allergen_taxonomy, user) is None


def collect_recommendation_dishes(
    user: dict,
    params: dict,
    disease_rules: dict,
    allergen_taxonomy: dict,
    storage,
) -> tuple[list[dict], str, str]:
    """從建檔好的店家菜單挑出這位使用者能吃的餐點。

    先前這裡會再打一次 Google Places，但兩次搜尋回的店家不保證相同
    （新版 API 回空就會退回舊版，名單就不一樣），結果建檔了 10 家卻只有
    1 家對得上。建檔就是為了這件事，所以這裡直接讀資料庫。
    """
    budget = int(params.get("budget", 150))
    conditions = user.get("health_conditions", []) or []
    allergens = user.get("allergens", []) or []

    venues = storage.list_restaurant_menus()
    if not venues:
        raise SeedDataUnavailable(
            "資料庫裡還沒有任何店家菜單。請先按「① 建立附近店家菜單檔案」，建好之後再灌入七天資料。"
        )

    dishes = []
    used_venues = 0
    considered = 0
    blocked = Counter()
    for venue in venues:
        items = venue.get("items") or []
        added = 0
        for item in items:
            considered += 1
            reason = _block_reason(item, venue, budget, conditions, allergens, disease_rules, allergen_taxonomy, user)
            if reason is None:
                dishes.append(_dish_from_item(item, venue))
                added += 1
            else:
                blocked[reason] += 1
        if added:
            used_venues += 1

    top_blocks = "、".join(f"{reason} {count} 道" for reason, count in blocked.most_common(3))

    if not dishes:
        raise SeedDataUnavailable(
            f"已建檔 {len(venues)} 家店共 {considered} 道餐點，但沒有一道通過篩選"
            + (f"（{top_blocks}）。" if top_blocks else "。")
            + "請調高預算，或先按①建檔更多店家。"
        )

    note = (
        f"已建檔 {len(venues)} 家店共 {considered} 道餐點，通過篩選 {len(dishes)} 道"
        f"（來自 {used_venues} 家）。"
    )
    if top_blocks:
        note += f"被擋掉的主因：{top_blocks}。"
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


def index_nearby_venues(
    storage,
    params: dict,
    fetch_places,
    enrich_restaurant,
    budget_seconds: float = MENU_ANALYSIS_BUDGET_SECONDS,
) -> dict:
    """把附近店家的菜單建檔進資料庫。

    分析一家店要 20~30 秒，塞在「灌入七天」那個請求裡會逾時。拆成獨立的
    建檔動作，可以重複按，每次在時間預算內處理幾家沒建過的，累積下去。
    """
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    radius_km = min(max(float(params.get("radius_km", 3)), 0.5), 10)
    category = str(params.get("category", "all") or "all").strip().lower()
    budget = int(params.get("budget", 150))
    limit = min(max(int(params.get("limit", 20)), 1), 20)

    try:
        places = fetch_places(lat, lng, radius_km, category, budget, limit=limit)
    except Exception as error:
        raise SeedDataUnavailable(f"店家搜尋失敗：{error}") from error
    if not places:
        raise SeedDataUnavailable(f"半徑 {radius_km} km 內搜尋不到店家，請調整定位或把半徑放大。")

    deadline = time.monotonic() + budget_seconds
    already_cached = 0
    analysed = 0
    failed = 0
    remaining = 0
    for place in places:
        name = str(place.get("name", "")).strip()
        if not name:
            continue
        place_id = str(place.get("google_place_id") or "").strip()
        if storage.get_restaurant_menu(name, place_id):
            already_cached += 1
            continue
        if time.monotonic() >= deadline:
            remaining += 1
            continue
        try:
            enriched = enrich_restaurant(name, place.get("address") or "台灣", "", deadline)
        except Exception as error:
            print(f"[venue-index] {name} 菜單分析失敗: {error}")
            failed += 1
            continue
        items = enriched.get("items", []) or []
        if not items:
            failed += 1
            continue
        storage.save_restaurant_menu(
            name,
            items,
            venue={
                "address": place.get("address", ""),
                "lat": place.get("lat"),
                "lng": place.get("lng"),
                "google_place_id": place_id,
                # 存下來才查得出這筆快取是什麼時候、什麼狀態下建的
                "business_status": place.get("business_status", ""),
                "is_open_at_index_time": place.get("is_open"),
            },
        )
        analysed += 1

    return {
        "found": len(places),
        "already_cached": already_cached,
        "analysed": analysed,
        "failed": failed,
        "remaining": remaining,
        "total_cached": storage.count_restaurant_menus(),
    }


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
    disease_rules: dict,
    allergen_taxonomy: dict,
) -> dict:
    days = min(max(int(days), 1), MAX_DAYS)
    budget = int(params.get("budget", 150))
    end_date = app_now().date()

    dishes, data_source, note = collect_recommendation_dishes(
        {**user},
        params,
        disease_rules,
        allergen_taxonomy,
        storage,
    )

    records = build_week_records(user_id, dishes, days, source, end_date, user)

    # 灌入是「重跑」而不是「補寫」：紀錄 id 是固定推導出來的，不先刪掉的話
    # insert_record 會判定重複而整批跳過，建檔了更多店家也看不出差別。
    replaced = sum(
        1 for record in records if storage.delete_record(user_id, record["client_record_id"])
    )

    created = 0
    for record in records:
        storage.insert_record(record)
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
        "replaced": replaced,
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
