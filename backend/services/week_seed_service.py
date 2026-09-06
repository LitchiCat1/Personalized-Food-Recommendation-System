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
        # 灌入七天要按用餐時段挑店，所以菜色要記得自己來自哪個營業時段
        "opening_periods": restaurant.get("opening_periods") or [],
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


# 熱量是區間，不是天花板：一天只吃 460 kcal 不該算「符合每日目標」。
# 只當上限的話，貪婪法會發現「少吃」永遠不扣分，整天就停在三小道菜。
# 0.85 跟趨勢頁的達標判定同一個下緣，兩邊才不會給出相反的結論。
CALORIE_FLOOR_RATIO = 0.85


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
        if nutrient == "calories" and target > 0:
            floor = target * CALORIE_FLOOR_RATIO
            if floor <= actual <= target:
                passed += 1
            elif actual > target:
                shortfall += (actual - target) / target
            else:
                shortfall += (floor - actual) / target
        elif goal_types[nutrient] == "upper_limit":
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


def _venue_open_at(periods: list, weekday: int, minute: int):
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


def _meal_eligibility(dishes: list, weekday: int) -> list[list[int]]:
    """每一餐可以選哪些菜——店家在那個時段有開才算數。

    營業時間不明的店留在每一餐的候選裡，否則資料一缺就整份計畫排不出來。
    """
    eligibility = []
    for meal_type in MEAL_ORDER:
        hour, minute = MEAL_HOURS[meal_type]
        at_minute = hour * 60 + minute
        allowed = [
            index
            for index, dish in enumerate(dishes)
            if _venue_open_at(dish.get("opening_periods") or [], weekday, at_minute) is not False
        ]
        # 那個時段一家店都沒開就不設限，至少排得出東西，不會整週開天窗
        eligibility.append(allowed or list(range(len(dishes))))
    return eligibility


def _best_addition(dishes: list, combo: list, targets: dict, goal_types: dict, order=None, allowed=None):
    """挑一道加進來後最有幫助、且不會撐破任何上限的菜。

    `order` 決定同分時先看哪一道。每天給不同的順序，營養值相同的菜色
    才不會讓七天全部收斂成同一組。
    """
    passed, shortfall = score_day(dishes, combo, targets, goal_types)
    best = None
    allowed_set = None if allowed is None else set(allowed)
    for index in (order if order is not None else range(len(dishes))):
        if allowed_set is not None and index not in allowed_set:
            continue
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


def _least_harmful_addition(dishes: list, combo: list, targets: dict, goal_types: dict, allowed=None) -> int:
    """一定要再加一道時，挑破壞最小的那道。"""
    return min(
        allowed if allowed else range(len(dishes)),
        key=lambda index: score_day(dishes, combo + [index], targets, goal_types)[1],
    )


def _build_day(dishes: list, targets: dict, goal_types: dict, first_index: int, eligibility: list, order=None) -> list[list[int]]:
    """逐餐挑菜，每餐只從那個時段有開的店裡選，並讓整天加總逼近每日目標。

    先前是「先湊出最佳的一天，再隨機分成三餐」，所以早上八點會排到炸雞。
    現在改成一餐一餐長：先讓每餐都有東西吃，再把剩下的額度加在幫助最大的
    那一餐上。挑的時候仍以整天加總計分，不是各餐各自最佳化——疾病目標
    本來就是一整天的。
    """
    meals = len(MEAL_ORDER)
    plate = [[] for _ in range(meals)]

    # 起始那道放進它吃得到的最早一餐，讓每天有不同的起點
    first_meal = next((index for index in range(meals) if first_index in eligibility[index]), None)
    if first_meal is None:
        first_meal = 0
        first_index = eligibility[0][0]
    plate[first_meal].append(first_index)

    def flat():
        return [index for meal in plate for index in meal]

    # 每一餐都要有東西吃
    for meal_index in range(meals):
        if plate[meal_index]:
            continue
        addition = _best_addition(dishes, flat(), targets, goal_types, order, eligibility[meal_index])
        if addition is None:
            addition = _least_harmful_addition(dishes, flat(), targets, goal_types, eligibility[meal_index])
        plate[meal_index].append(addition)

    # 還有額度就補在最有幫助的那一餐
    while len(flat()) < MAX_DISHES_PER_DAY:
        if score_day(dishes, flat(), targets, goal_types)[0] == len(NUTRITION_FIELDS):
            break
        best = None
        for meal_index in range(meals):
            if len(plate[meal_index]) >= MAX_DISHES_PER_MEAL:
                continue
            addition = _best_addition(dishes, flat(), targets, goal_types, order, eligibility[meal_index])
            if addition is None:
                continue
            score = score_day(dishes, flat() + [addition], targets, goal_types)
            if best is None or (score[0], -score[1]) > (best[0][0], -best[0][1]):
                best = (score, meal_index, addition)
        if best is None:
            break
        plate[best[1]].append(best[2])

    return plate


def _vary_day(plate: list, rotation, seen: set, eligibility: list):
    """把其中一道換掉，換出一組還沒排過的一天。

    換進來的菜必須也是那一餐吃得到的，否則變化會把時段限制破壞掉。
    """
    for meal_index, meal in enumerate(plate):
        allowed = set(eligibility[meal_index])
        for position in range(len(meal)):
            for replacement in rotation:
                if replacement not in allowed or replacement in meal:
                    continue
                candidate = [list(entry) for entry in plate]
                candidate[meal_index][position] = replacement
                key = _plate_key(candidate)
                if key not in seen:
                    return candidate, key
    return plate, None


def _plate_key(plate: list) -> tuple:
    """一天的識別：哪一餐吃哪些菜。同樣的菜換餐吃算不同的一天。"""
    return tuple(tuple(sorted(meal)) for meal in plate)


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
                "opening_periods": place.get("opening_periods") or [],
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


def plan_daily_dishes(
    dishes: list,
    days: int,
    seed: str,
    targets: dict,
    goal_types: dict,
    weekdays: list | None = None,
) -> list[list[list[int]]]:
    """排出每天三餐吃哪些菜，優先讓整天加總符合疾病別的每日目標。

    回傳 [天][餐] = 該餐的菜色索引清單。一餐可以配多道
    （例如主餐 + 一份青菜），否則蛋白質與纖維的下限幾乎不可能達成。

    `weekdays` 是每一天的星期別（0=週日，對齊 Google Places），用來判斷
    那天那個時段哪些店有開；沒給就當成營業時間未知，不做時段限制。
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
        day_index = len(plan)
        weekday = weekdays[day_index] if weekdays and day_index < len(weekdays) else None
        eligibility = (
            _meal_eligibility(dishes, weekday)
            if weekday is not None
            else [list(range(dish_count)) for _ in MEAL_ORDER]
        )
        start = starts[offset % dish_count]
        # 每天用不同的候選順序，營養一樣的菜色才不會七天長成同一組
        rotation = starts[offset % dish_count:] + starts[:offset % dish_count]
        plate = _build_day(dishes, targets, goal_types, start, eligibility, rotation)
        key = _plate_key(plate)
        if key in seen:
            # 菜色營養一樣時貪婪法會收斂成同一組，換掉其中一道湊出不同的一天
            plate, key = _vary_day(plate, rotation, seen, eligibility)
            if key is None:
                continue
        seen.add(key)
        plan.append(plate)

    while len(plan) < days:  # 菜色太少時只能重複
        plan.append([list(meal) for meal in plan[len(plan) % max(len(plan), 1)]] if plan else [[0] for _ in MEAL_ORDER])

    return plan[:days]


def build_week_records(user_id: str, dishes: list, days: int, source: str, end_date, user: dict) -> list[dict]:
    """把菜色發到每天三餐，盡量符合疾病別每日目標，且七天彼此不重複。"""
    tzinfo = get_app_timezone()
    targets = calculate_pdf_daily_targets(user)
    goal_types = build_nutrition_goal_types(user)
    records = []
    day_dates = [end_date - timedelta(days=days - 1 - index) for index in range(days)]
    # Google Places 的 day 是 0=週日，Python 的 isoweekday 是 1=週一…7=週日
    weekdays = [day.isoweekday() % 7 for day in day_dates]
    plan = plan_daily_dishes(
        dishes, days, f"{user_id}:{source}:{end_date.isoformat()}", targets, goal_types, weekdays
    )
    for day_index, meal_plan in enumerate(plan):
        day = day_dates[day_index]
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
