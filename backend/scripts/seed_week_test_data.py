"""7 天飲食測試資料產生器 + 目標達成率檢查。

用途：不必真的吃一個星期，就能一次灌入 7 天飲食紀錄，
      再依 `calculate_pdf_daily_targets` 的疾病別條件逐日檢查是否符合。

所有營養值都來自 backend/nutrition_db_tw.json (TFDA)，依克數換算，
所以灌進去的數字跟 App 自己查到的完全一致。

兩種資料來源：
    --source curated   （預設）用本檔案內建的台灣家常菜單，營養值查 TFDA
    --source recommend 直接抓 App 的店家推薦餐點，平均分攤到七天，
                       用來回答「整週都照推薦系統吃，能不能符合設定條件」

打 Render（後端強制 Supabase Auth，token 請走環境變數不要寫在指令裡）：
    $env:NUTRILENS_API_URL      = "https://<backend>.onrender.com"
    $env:NUTRILENS_ACCESS_TOKEN = "<Supabase access token>"
    python backend/scripts/seed_week_test_data.py --source recommend
    （沒給 --user-id 時會自動取 token 的 sub 當 user_id，因為 Render 會擋掉別人的資料）

用法（本機後端要先跑起來）：
    python backend/scripts/seed_week_test_data.py --scenario mixed
    python backend/scripts/seed_week_test_data.py --source recommend --budget 150
    python backend/scripts/seed_week_test_data.py --profile diabetes --scenario compliant
    python backend/scripts/seed_week_test_data.py --dry-run
    python backend/scripts/seed_week_test_data.py --clear
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime, time, timedelta

import requests

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.disease_rule_service import load_allergen_taxonomy, load_disease_rules  # noqa: E402
from services.nutrient_service import NUTRITION_FIELDS, get_nutrient_value  # noqa: E402
from services.profile_service import build_user_profile  # noqa: E402
from services.nutrition_progress_service import (  # noqa: E402
    build_nutrition_goal_types,
    calculate_pdf_daily_targets,
    round_targets_for_display,
)

TFDA_PATH = os.path.join(BACKEND_DIR, "nutrition_db_tw.json")

# ─── 食材對照表 (alias -> TFDA key) ───────────────────────────
# key 必須是 nutrition_db_tw.json 內存在的鍵，啟動時會驗證。
FOODS = {
    # 主食
    "white_rice": ("白飯", "白飯"),
    "oats": ("即食燕麥片", "即食燕麥片"),
    "noodle": ("乾麵條", "麵條(乾重)"),
    "oil_noodle": ("油麵條", "油麵"),
    "sweet_potato": ("黃肉甘藷", "地瓜"),
    "burger_bun": ("漢堡包", "漢堡麵包"),
    # 蛋白質
    "chicken_breast": ("里肌肉(肉雞)", "雞胸肉"),
    "pork_loin": ("豬小里肌", "豬小里肌"),
    "salmon": ("大西洋鮭魚(台灣養殖)", "鮭魚"),
    "tilapia": ("紅色吳郭魚", "台灣鯛魚"),
    "egg": ("雞蛋平均值", "雞蛋"),
    "tofu": ("傳統豆腐", "傳統豆腐"),
    "dried_tofu": ("小方豆干", "小方豆干"),
    "edamame": ("毛豆仁", "毛豆仁"),
    # 蔬菜
    "cabbage": ("甘藍平均值", "高麗菜"),
    "broccoli": ("青花菜(2021年取樣)", "青花菜"),
    "spinach": ("菠菜(葉)(有機)", "菠菜"),
    "cauliflower": ("花椰菜", "白花椰菜"),
    "seaweed_knot": ("海帶結", "海帶結"),
    "tomato": ("大番茄平均值(紅色系)", "大番茄"),
    "nori": ("紫菜", "紫菜"),
    # 水果
    "guava": ("芭樂平均值(白肉)", "芭樂"),
    "kiwi": ("奇異果", "奇異果"),
    "apple": ("蘋果平均值(混色)", "蘋果"),
    "papaya": ("木瓜平均值", "木瓜"),
    "banana": ("北蕉(3天)", "香蕉"),
    # 飲品/乳品/種子
    "low_fat_milk": ("低脂鮮乳", "低脂鮮乳"),
    "soy_milk": ("豆漿(無糖)", "無糖豆漿"),
    "americano": ("美式咖啡(無糖)", "美式咖啡(無糖)"),
    "black_sesame": ("黑芝麻(生)", "黑芝麻"),
    # 高熱量/高鈉（用於超標情境）
    "instant_noodle": ("泡麵(牛肉口味)", "牛肉泡麵"),
    "fries": ("冷凍馬鈴薯條", "薯條"),
    "nuggets": ("冷凍雞塊", "雞塊"),
    "sausage": ("香腸", "香腸"),
    "bacon": ("培根", "培根"),
    "donut": ("糖粒甜甜圈(油炸)", "甜甜圈"),
    "bubble_tea": ("珍珠奶茶(去冰,全糖)", "珍珠奶茶(全糖)"),
    "ham_sandwich": ("火腿蛋三明治", "火腿蛋三明治"),
    "pork_dumpling": ("冷凍豬肉水餃", "豬肉水餃"),
    "oyster_omelet": ("蚵仔煎", "蚵仔煎"),
    "chicken_cutlet": ("雞排平均值", "炸雞排"),
}

FRIED_ALIASES = {"fries", "nuggets", "donut", "chicken_cutlet", "oyster_omelet"}

# ─── 每日菜單樣板 ─────────────────────────────────────────────
# 每個樣板 = [(餐別, [(alias, 公克), ...]), ...]
# 份量已調到：熱量/碳水/脂肪/鈉在上限內，蛋白質/纖維/鈣/鐵達下限，
# 精緻糖壓在 25g 以下（連糖尿病條件的 25g 上限也過得了）。
COMPLIANT_DAYS = [
    [
        ("早餐", [("oats", 60), ("low_fat_milk", 150), ("banana", 60), ("black_sesame", 10)]),
        ("午餐", [("white_rice", 130), ("chicken_breast", 120), ("broccoli", 150), ("edamame", 80), ("seaweed_knot", 60), ("nori", 10)]),
        ("晚餐", [("white_rice", 120), ("tilapia", 120), ("spinach", 250), ("dried_tofu", 70), ("guava", 80)]),
    ],
    [
        ("早餐", [("soy_milk", 400), ("egg", 110), ("sweet_potato", 150), ("black_sesame", 10)]),
        ("午餐", [("white_rice", 130), ("pork_loin", 110), ("cabbage", 150), ("edamame", 80), ("nori", 10)]),
        ("晚餐", [("noodle", 90), ("salmon", 110), ("spinach", 250), ("broccoli", 100), ("dried_tofu", 70), ("kiwi", 50)]),
    ],
    [
        ("早餐", [("oats", 60), ("soy_milk", 300), ("apple", 50), ("black_sesame", 10)]),
        ("午餐", [("white_rice", 200), ("tofu", 150), ("edamame", 80), ("broccoli", 150), ("nori", 5)]),
        ("晚餐", [("sweet_potato", 150), ("chicken_breast", 130), ("spinach", 150), ("dried_tofu", 70), ("tomato", 150)]),
    ],
    [
        ("早餐", [("soy_milk", 400), ("egg", 110), ("white_rice", 120), ("black_sesame", 10)]),
        ("午餐", [("noodle", 90), ("tilapia", 130), ("cauliflower", 200), ("seaweed_knot", 100), ("nori", 5)]),
        ("晚餐", [("white_rice", 100), ("tofu", 150), ("edamame", 60), ("dried_tofu", 70), ("spinach", 250), ("guava", 150)]),
    ],
]

OVER_DAYS = [
    [
        ("早餐", [("ham_sandwich", 200), ("bubble_tea", 500)]),
        ("午餐", [("instant_noodle", 120), ("sausage", 80), ("egg", 60)]),
        ("晚餐", [("chicken_cutlet", 200), ("white_rice", 250), ("fries", 150)]),
    ],
    [
        ("早餐", [("burger_bun", 120), ("bacon", 60), ("egg", 60), ("bubble_tea", 500)]),
        ("午餐", [("pork_dumpling", 300), ("oyster_omelet", 250)]),
        ("晚餐", [("oil_noodle", 200), ("sausage", 100), ("nuggets", 150), ("donut", 80)]),
    ],
    [
        ("早餐", [("donut", 120), ("bubble_tea", 500)]),
        ("午餐", [("chicken_cutlet", 220), ("white_rice", 250), ("nuggets", 120)]),
        ("晚餐", [("instant_noodle", 120), ("oyster_omelet", 250), ("fries", 150)]),
    ],
]

# mixed：真實的一週—多數天達標、少數天破戒
MIXED_PATTERN = ["compliant", "compliant", "over", "compliant", "compliant", "over", "compliant"]

MEAL_TIMES = {"早餐": time(8, 0), "午餐": time(12, 30), "晚餐": time(19, 0), "點心": time(15, 30)}
MEAL_ORDER = ("早餐", "午餐", "晚餐")

# ─── 使用者檔案樣板 ───────────────────────────────────────────
PROFILE_PRESETS = {
    "healthy": {"name": "測試帳號-無疾病", "health_conditions": []},
    "diabetes": {"name": "測試帳號-糖尿病", "health_conditions": ["diabetes"]},
    "hypertension": {"name": "測試帳號-高血壓", "health_conditions": ["hypertension"]},
    "kidney_disease": {"name": "測試帳號-慢性腎臟病", "health_conditions": ["kidney_disease"]},
    "gout": {"name": "測試帳號-痛風", "health_conditions": ["gout"]},
    "hyperlipidemia": {"name": "測試帳號-高血脂", "health_conditions": ["hyperlipidemia"]},
}

BASE_PROFILE = {
    "gender": "male",
    "height": 170,
    "weight": 65,
    "age": 25,
    "activity_level": "中等活動量",
    "activity_multiplier": 1.55,
    "allergens": [],
    "diet_type": "均衡飲食",
}


def load_tfda_db() -> dict:
    with open(TFDA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_food_catalog(tfda_db: dict):
    missing = [f"{alias} -> {key}" for alias, (key, _) in FOODS.items() if key not in tfda_db]
    if missing:
        raise SystemExit("[fail] 食材對照表有找不到的 TFDA 鍵：\n  " + "\n  ".join(missing))


def _number(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def build_food_item(tfda_db: dict, alias: str, grams: float) -> dict:
    key, display_name = FOODS[alias]
    per_100g = tfda_db[key]
    factor = grams / 100.0
    item = {
        "name": f"{display_name} {grams:g}g",
        "food_key": key,
        "grams": grams,
        "is_fried": alias in FRIED_ALIASES,
    }
    for nutrient in NUTRITION_FIELDS:
        item[nutrient] = round(_number(get_nutrient_value(per_100g, nutrient)) * factor, 2)
    return item


def build_day_plans(scenario: str, days: int) -> list:
    """回傳每天的菜單樣板，index 0 = 最舊的一天。"""
    plans = []
    compliant_index = over_index = 0
    for day_index in range(days):
        if scenario == "mixed":
            kind = MIXED_PATTERN[day_index % len(MIXED_PATTERN)]
        else:
            kind = scenario
        if kind == "compliant":
            plans.append(COMPLIANT_DAYS[compliant_index % len(COMPLIANT_DAYS)])
            compliant_index += 1
        else:
            plans.append(OVER_DAYS[over_index % len(OVER_DAYS)])
            over_index += 1
    return plans


def build_records(tfda_db: dict, user_id: str, scenario: str, days: int, end_date, tzinfo) -> list:
    records = []
    for day_index, plan in enumerate(build_day_plans(scenario, days)):
        offset = days - 1 - day_index  # day_index 0 = 最舊
        day = end_date - timedelta(days=offset)
        for meal_type, items in plan:
            timestamp = datetime.combine(day, MEAL_TIMES[meal_type], tzinfo=tzinfo).isoformat()
            records.append(
                {
                    "user_id": user_id,
                    "client_record_id": f"seed_{scenario}_{day.strftime('%Y%m%d')}_{meal_type}",
                    "timestamp": timestamp,
                    "meal_type": meal_type,
                    "source": "manual",
                    "foods": [build_food_item(tfda_db, alias, grams) for alias, grams in items],
                }
            )
    return records


def seed_record_ids(tag: str, days: int, end_date) -> list:
    """同一組 (tag, 日期, 餐別) 永遠對應同一個 client_record_id，重跑不會重複。"""
    return [
        f"seed_{tag}_{(end_date - timedelta(days=offset)).strftime('%Y%m%d')}_{meal_type}"
        for offset in range(days)
        for meal_type in MEAL_ORDER
    ]


def build_recommendation_food(item: dict) -> dict:
    """把一筆推薦餐點轉成飲食紀錄的 food。

    推薦 API 只回傳 calories/protein/carbs/fat/sodium；
    膳食纖維、精緻糖、飽和脂肪、反式脂肪不在 payload 裡，只能記 0。
    """
    food = {
        "name": f"{item.get('item_name', '推薦餐點')}（{item.get('restaurant_name', '未知店家')}）",
        "restaurant_id": item.get("restaurant_id"),
        "item_id": item.get("item_id"),
        "price": item.get("price"),
        "match_score": item.get("match_score"),
        "is_fried": bool(item.get("is_fried")),
    }
    for nutrient in NUTRITION_FIELDS:
        food[nutrient] = round(_number(item.get(nutrient)), 2)
    return food


def build_records_from_recommendations(user_id: str, items: list, days: int, end_date, tzinfo) -> list:
    """把推薦餐點平均分攤到每一天的三餐。

    依 match_score 排序後輪流發牌（第 i 名 -> 第 i%days 天），
    避免高分餐點全部集中在同一天。
    """
    if not items:
        raise SystemExit("[fail] 推薦 API 沒有回傳任何餐點，無法建立紀錄")

    records = []
    for slot_index in range(days * len(MEAL_ORDER)):
        item = items[slot_index % len(items)]
        offset = days - 1 - (slot_index % days)
        meal_type = MEAL_ORDER[slot_index // days]
        day = end_date - timedelta(days=offset)
        records.append(
            {
                "user_id": user_id,
                "client_record_id": f"seed_recommend_{day.strftime('%Y%m%d')}_{meal_type}",
                "timestamp": datetime.combine(day, MEAL_TIMES[meal_type], tzinfo=tzinfo).isoformat(),
                "meal_type": meal_type,
                "source": "manual",
                "foods": [build_recommendation_food(item)],
            }
        )
    records.sort(key=lambda record: record["timestamp"])
    return records


def print_recommendation_plan(records: list):
    print("\n推薦餐點分攤結果")
    current_date = None
    for record in records:
        date_str = record["timestamp"][:10]
        if date_str != current_date:
            current_date = date_str
            print(f"  {date_str}")
        food = record["foods"][0]
        price = food.get("price")
        price_text = f" NT${price}" if price is not None else ""
        print(f"    {record['meal_type']}  {food['name']}{price_text}  {food['calories']:.0f} kcal  Na {food['sodium']:.0f} mg")


# ─── API ─────────────────────────────────────────────────────
def api_headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def user_id_from_token(token: str | None) -> str | None:
    """從 Supabase access token 取出 sub（user id）。

    只解 JWT payload 不驗簽章——驗證是後端的事，這裡只是省去人工查 UUID。
    """
    if not token or token.count(".") != 2:
        return None
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None


def raise_for_auth(response, label: str):
    if response.status_code in (401, 403):
        hint = (
            "token 無效或已過期，請重新登入取得新的 access token"
            if response.status_code == 401
            else "user_id 與 token 的擁有者不符；Render 只允許存取自己的資料，"
            "請拿掉 --user-id 讓腳本自動用 token 的 sub"
        )
        raise SystemExit(f"[fail] {label} 回應 {response.status_code}：{hint}")


def upsert_profile(api_url: str, token: str | None, user_id: str, profile_key: str) -> dict:
    payload = {**BASE_PROFILE, **PROFILE_PRESETS[profile_key], "user_id": user_id}
    response = requests.post(f"{api_url}/user", json=payload, headers=api_headers(token), timeout=60)
    raise_for_auth(response, "POST /user")
    response.raise_for_status()
    return response.json()["user"]


def get_profile(api_url: str, token: str | None, user_id: str) -> dict:
    response = requests.get(f"{api_url}/user/{user_id}", headers=api_headers(token), timeout=60)
    raise_for_auth(response, f"GET /user/{user_id}")
    if response.status_code == 404:
        raise SystemExit(f"[fail] Render 上找不到 {user_id} 的 profile，請先在 App 完成 onboarding，或拿掉 --skip-profile")
    response.raise_for_status()
    return response.json()


def fetch_recommendations(api_url: str, token: str | None, user_id: str, params: dict) -> list:
    response = requests.get(
        f"{api_url}/healthy-food-recommend/{user_id}",
        params=params,
        headers=api_headers(token),
        timeout=60,
    )
    raise_for_auth(response, "GET /healthy-food-recommend")
    response.raise_for_status()
    payload = response.json()
    items = payload.get("recommended") or []
    filtered = payload.get("filtered_out") or []
    print(f"[ok] 推薦 API 回傳 {len(items)} 道可吃餐點、{len(filtered)} 道被預算或疾病條件擋掉")
    return items


def post_record(api_url: str, token: str | None, record: dict) -> tuple[bool, str]:
    response = requests.post(f"{api_url}/record", json=record, headers=api_headers(token), timeout=60)
    raise_for_auth(response, "POST /record")
    if response.status_code not in (200, 201):
        return False, f"HTTP {response.status_code} {response.text[:200]}"
    return True, "已存在" if response.json().get("deduplicated") else "新增"


def delete_record(api_url: str, token: str | None, user_id: str, client_record_id: str) -> bool:
    response = requests.delete(
        f"{api_url}/records/{user_id}/{client_record_id}", headers=api_headers(token), timeout=30
    )
    return response.status_code == 200


def get_day_totals(api_url: str, token: str | None, user_id: str, date_str: str) -> tuple[dict, int, dict]:
    response = requests.get(
        f"{api_url}/records/{user_id}",
        params={"date": date_str, "limit": 500},
        headers=api_headers(token),
        timeout=60,
    )
    raise_for_auth(response, f"GET /records/{user_id}")
    response.raise_for_status()
    payload = response.json()
    records = payload.get("records", [])
    totals = {
        nutrient: round(sum(_number(record.get(f"total_{nutrient}")) for record in records), 1)
        for nutrient in NUTRITION_FIELDS
    }
    return totals, len(records), payload.get("nutrition_targets") or {}


# ─── 條件檢查 ────────────────────────────────────────────────
def evaluate_day(totals: dict, targets: dict, goal_types: dict) -> dict:
    result = {}
    for nutrient in NUTRITION_FIELDS:
        target = _number(targets.get(nutrient))
        consumed = _number(totals.get(nutrient))
        goal = goal_types[nutrient]
        if goal == "upper_limit":
            passed = consumed <= target
        else:
            passed = consumed >= target
        result[nutrient] = {
            "goal": goal,
            "target": target,
            "consumed": consumed,
            "passed": passed,
            "delta": round(consumed - target, 1),
        }
    return result


LABELS = {
    "calories": "熱量",
    "protein": "蛋白質",
    "carbs": "碳水",
    "sugar": "精緻糖",
    "fat": "脂肪",
    "saturated_fat": "飽和脂肪",
    "trans_fat": "反式脂肪",
    "fiber": "纖維",
    "sodium": "鈉",
}


def print_report(days_report: list, targets: dict, goal_types: dict):
    print("\n每日目標值（依健康條件動態計算）")
    for nutrient in NUTRITION_FIELDS:
        goal = "上限" if goal_types[nutrient] == "upper_limit" else "下限"
        print(f"  {LABELS[nutrient]:<6}{goal} {round(_number(targets.get(nutrient)), 1)}")

    print("\n逐日結果")
    header = f"{'日期':<12}{'熱量':>7}{'蛋白':>7}{'碳水':>7}{'脂肪':>7}{'鈉':>7}{'纖維':>7}  達標"
    print(header)
    print("-" * 70)
    for day in days_report:
        checks = day["checks"]
        failed = [LABELS[n] for n in NUTRITION_FIELDS if not checks[n]["passed"]]
        mark = "✅ 全數達標" if not failed else "❌ " + "、".join(failed)
        print(
            f"{day['date']:<12}"
            f"{checks['calories']['consumed']:>7.0f}"
            f"{checks['protein']['consumed']:>7.0f}"
            f"{checks['carbs']['consumed']:>7.0f}"
            f"{checks['fat']['consumed']:>7.0f}"
            f"{checks['sodium']['consumed']:>7.0f}"
            f"{checks['fiber']['consumed']:>7.0f}  {mark}"
        )

    print("\n各營養素 7 天達標次數")
    total_days = len(days_report)
    for nutrient in NUTRITION_FIELDS:
        hits = sum(1 for day in days_report if day["checks"][nutrient]["passed"])
        bar = "█" * hits + "·" * (total_days - hits)
        print(f"  {LABELS[nutrient]:<6}{hits}/{total_days}  {bar}")

    full_pass = sum(1 for day in days_report if all(c["passed"] for c in day["checks"].values()))
    print(f"\n完全符合所有條件的天數：{full_pass}/{total_days}")

    trans_hits = sum(1 for day in days_report if day["checks"]["trans_fat"]["passed"])
    if trans_hits < total_days:
        print(
            "\n注意：反式脂肪目標固定為 0 g（上限），但蛋、乳製品等天然食物本來就含微量反式脂肪，"
            "\n      所以只要有記錄到這類食物就一定判定超標。若要比照 WHO／國健署「低於總熱量 1%」"
            "\n      的建議，需要調整 calculate_pdf_daily_targets 的 trans_fat 目標值。"
        )


def build_local_profile(user_id: str, profile_key: str) -> dict:
    """不連後端也能算出目標值，方便先試菜單。"""
    payload = {**BASE_PROFILE, **PROFILE_PRESETS[profile_key], "user_id": user_id}
    return build_user_profile(payload, load_disease_rules(BACKEND_DIR), load_allergen_taxonomy(BACKEND_DIR))


def build_local_days_report(records: list, targets: dict, goal_types: dict) -> list:
    by_date = {}
    for record in records:
        date_str = record["timestamp"][:10]
        day = by_date.setdefault(
            date_str,
            {"date": date_str, "record_count": 0, "totals": dict.fromkeys(NUTRITION_FIELDS, 0.0)},
        )
        day["record_count"] += 1
        for nutrient in NUTRITION_FIELDS:
            day["totals"][nutrient] += sum(food[nutrient] for food in record["foods"])
    report = []
    for day in sorted(by_date.values(), key=lambda item: item["date"]):
        totals = {nutrient: round(value, 1) for nutrient, value in day["totals"].items()}
        report.append({**day, "totals": totals, "checks": evaluate_day(totals, targets, goal_types)})
    return report



def print_missing_nutrient_note(source: str):
    if source != "recommend":
        return
    print(
        "\n注意：店家推薦 API 每道餐點只回傳熱量、蛋白質、碳水、脂肪、鈉五項，"
        "\n      膳食纖維、精緻糖、飽和脂肪、反式脂肪不在 payload 裡，因此這四項一律記為 0。"
        "\n      也就是說「照推薦吃一週」在目前的資料下，纖維必然不達標，不是菜色本身的問題。"
    )


def main():
    parser = argparse.ArgumentParser(description="灌入 7 天飲食測試資料並檢查是否符合設定條件")
    parser.add_argument("--api-url", default=os.environ.get("NUTRILENS_API_URL", "http://127.0.0.1:5000"))
    parser.add_argument(
        "--user-id",
        default=None,
        help="預設依序取 NUTRILENS_TEST_USER、access token 的 sub、demo_user",
    )
    parser.add_argument("--token", default=os.environ.get("NUTRILENS_ACCESS_TOKEN"), help="Supabase access token（雲端後端才需要）")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--scenario", choices=["mixed", "compliant", "over"], default="mixed")
    parser.add_argument(
        "--source",
        choices=["curated", "recommend"],
        default="curated",
        help="curated=內建台灣家常菜單；recommend=抓 App 店家推薦餐點平攤到七天",
    )
    parser.add_argument("--budget", type=int, default=150, help="--source recommend 的單餐預算")
    parser.add_argument("--lat", type=float, default=25.0338)
    parser.add_argument("--lng", type=float, default=121.5645)
    parser.add_argument("--radius-km", type=float, default=5)
    parser.add_argument("--category", default="all")
    parser.add_argument("--profile", choices=sorted(PROFILE_PRESETS), default="healthy")
    parser.add_argument("--skip-profile", action="store_true", help="沿用後端既有的使用者檔案，不覆蓋")
    parser.add_argument("--clear", action="store_true", help="刪除同情境先前灌入的紀錄後結束")
    parser.add_argument("--dry-run", action="store_true", help="只印出將寫入的資料，不呼叫 API")
    parser.add_argument("--report", help="把完整結果寫成 JSON 檔")
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    args.user_id = (
        args.user_id
        or os.environ.get("NUTRILENS_TEST_USER")
        or user_id_from_token(args.token)
        or "demo_user"
    )
    if args.token:
        print(f"[ok] 目標 {api_url}（帶 Bearer token），user_id={args.user_id}")
    tfda_db = load_tfda_db()
    verify_food_catalog(tfda_db)

    now_local = datetime.now().astimezone()
    tzinfo = now_local.tzinfo
    end_date = now_local.date()
    tag = "recommend" if args.source == "recommend" else args.scenario

    if args.clear:
        # 多往前清一週，日期換過之後舊紀錄才不會留下來
        stale_ids = seed_record_ids(tag, args.days + 7, end_date)
        removed = sum(
            1 for record_id in stale_ids if delete_record(api_url, args.token, args.user_id, record_id)
        )
        print(f"[ok] 已刪除 {removed} 筆 {tag} 紀錄")
        return

    # recommend 模式要先有 profile，推薦 API 才算得出疾病過濾與剩餘熱量
    user = None
    if args.source == "recommend" or not args.dry_run:
        if args.skip_profile:
            user = get_profile(api_url, args.token, args.user_id)
            print(f"[ok] 沿用既有檔案：{user.get('name')} 條件={user.get('health_conditions')}")
        else:
            user = upsert_profile(api_url, args.token, args.user_id, args.profile)
            print(f"[ok] 使用者檔案已設定：{user.get('name')} 條件={user.get('health_conditions')} TDEE={user.get('tdee')}")

    if args.source == "recommend":
        items = fetch_recommendations(
            api_url,
            args.token,
            args.user_id,
            {
                "budget": args.budget,
                "lat": args.lat,
                "lng": args.lng,
                "radius_km": args.radius_km,
                "category": args.category,
            },
        )
        records = build_records_from_recommendations(args.user_id, items, args.days, end_date, tzinfo)
        print_recommendation_plan(records)
    else:
        records = build_records(tfda_db, args.user_id, args.scenario, args.days, end_date, tzinfo)

    if args.dry_run:
        if args.source == "curated":
            for record in records:
                names = "、".join(food["name"] for food in record["foods"])
                print(f"{record['timestamp'][:16]} {record['meal_type']}: {names}")
        print(f"\n[dry-run] 共 {len(records)} 筆紀錄，未寫入後端。")
        report_user = user or build_local_profile(args.user_id, args.profile)
        targets = round_targets_for_display(calculate_pdf_daily_targets(report_user))
        goal_types = build_nutrition_goal_types(report_user)
        print_report(build_local_days_report(records, targets, goal_types), targets, goal_types)
        print_missing_nutrient_note(args.source)
        return

    created = deduplicated = 0
    for record in records:
        ok, status = post_record(api_url, args.token, record)
        if not ok:
            raise SystemExit(f"[fail] {record['client_record_id']}: {status}")
        if status == "新增":
            created += 1
        else:
            deduplicated += 1
    print(f"[ok] 飲食紀錄：新增 {created} 筆、已存在 {deduplicated} 筆（共 {len(records)} 筆 / {args.days} 天）")

    local_targets = round_targets_for_display(calculate_pdf_daily_targets(user))
    goal_types = build_nutrition_goal_types(user)
    days_report = []
    server_targets = {}
    for day_index in range(args.days):
        day = end_date - timedelta(days=args.days - 1 - day_index)
        date_str = day.strftime("%Y-%m-%d")
        totals, count, targets_payload = get_day_totals(api_url, args.token, args.user_id, date_str)
        server_targets = targets_payload or server_targets
        days_report.append(
            {
                "date": date_str,
                "record_count": count,
                "totals": totals,
                "checks": evaluate_day(totals, targets_payload or local_targets, goal_types),
            }
        )

    targets = server_targets or local_targets
    print_report(days_report, targets, goal_types)
    print_missing_nutrient_note(args.source)

    if args.report:
        payload = {
            "generated_at": now_local.isoformat(),
            "api_url": api_url,
            "user_id": args.user_id,
            "profile": args.profile if not args.skip_profile else "existing",
            "source": args.source,
            "scenario": args.scenario,
            "days": args.days,
            "targets": targets,
            "goal_type": goal_types,
            "daily": days_report,
        }
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n[ok] 完整報告已寫入 {args.report}")


if __name__ == "__main__":
    main()
