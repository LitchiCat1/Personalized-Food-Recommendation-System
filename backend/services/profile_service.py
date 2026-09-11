from datetime import datetime, timezone

from services.disease_rule_service import normalize_allergen_ids, normalize_condition_ids


# 運動係數先前寫死 1.55（中等活動量），而編輯表單根本沒有這一欄，
# 所以每個人的 TDEE 都是 BMR x 1.55——臥床的人和運動員拿到同一個數字。
DEFAULT_DIET_TYPE = "葷食"

# 前端「我的」頁的選單只有這兩個（frontend/constants/diet.ts）。
DIET_TYPES = ("葷食", "素食")

# 身體數值的合理範圍。
#
# 先前前後端都只檢查「大於 0」：身高 1cm、體重 1kg、年齡 1 歲存得進去，
# 而這些值會直接餵進 BMR/TDEE/BMI，再變成每日目標與單餐上限。醫療情境下
# 一個離譜的身高不該安靜地變成一份餐點建議。
#
# 上下界取的是「人類可能的極端值」而不是「健康範圍」——這裡要擋的是
# 打錯字與單位搞錯（170 公尺、50 公克），不是替使用者判斷胖瘦。
PROFILE_LIMITS = {
    "height": {"min": 80, "max": 250, "unit": "cm", "label_zh": "身高"},
    "weight": {"min": 20, "max": 400, "unit": "kg", "label_zh": "體重"},
    "age": {"min": 13, "max": 120, "unit": "歲", "label_zh": "年齡"},
    "target_weight": {"min": 20, "max": 400, "unit": "kg", "label_zh": "目標體重"},
    "daily_calorie_target": {"min": 800, "max": 6000, "unit": "kcal", "label_zh": "每日熱量基準"},
}


def normalize_diet_type(value) -> str:
    """把不在選單裡的飲食型態換成預設值。

    先前這裡是 `data.get("diet_type") or DEFAULT_DIET_TYPE`：預設值修好了，
    但舊帳號存的「均衡飲食」是 truthy，永遠不會被換掉。而前端的
    isKnownDietType 不認得它——結果是「編輯資料」一打開，什麼都還沒改，
    儲存鈕就已經是灰的，訊息還叫你「在下方選一個」，畫面上卻顯示你已經
    選了「均衡飲食」。舊帳號等於再也存不了檔。
    """
    if isinstance(value, str) and value.strip() in DIET_TYPES:
        return value.strip()
    return DEFAULT_DIET_TYPE


def _validate_range(field: str, value) -> float:
    limit = PROFILE_LIMITS[field]
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{limit['label_zh']}要填數字。")
    if not (limit["min"] <= number <= limit["max"]):
        raise ValueError(
            f"{limit['label_zh']}要在 {limit['min']}~{limit['max']} {limit['unit']} 之間，"
            f"目前填的是 {number:g}。"
        )
    return number


def normalize_stored_user(user: dict) -> tuple[dict, bool]:
    """讀取舊資料時把已經不合法的欄位補正，回傳 (資料, 有沒有被改過)。

    寫入路徑修好不會救到已經存在的那些帳號，而這個 App 的帳號是長期的：
    沒有這一段，任何一次選項收斂都會把既有使用者鎖在一個存不了檔的表單裡。
    """
    if not user:
        return user, False

    fixed = dict(user)
    changed = False

    diet_type = normalize_diet_type(fixed.get("diet_type"))
    if diet_type != fixed.get("diet_type"):
        fixed["diet_type"] = diet_type
        changed = True

    return fixed, changed

ACTIVITY_LEVELS = [
    {"id": "sedentary", "label_zh": "久坐（幾乎不運動）", "multiplier": 1.2},
    {"id": "light", "label_zh": "輕度活動（每週 1-3 天）", "multiplier": 1.375},
    {"id": "moderate", "label_zh": "中等活動（每週 3-5 天）", "multiplier": 1.55},
    {"id": "active", "label_zh": "高度活動（每週 6-7 天）", "multiplier": 1.725},
    {"id": "very_active", "label_zh": "極高活動（勞力工作或每日訓練）", "multiplier": 1.9},
]

ACTIVITY_MULTIPLIER_BY_LABEL = {level["label_zh"]: level["multiplier"] for level in ACTIVITY_LEVELS}
ACTIVITY_MULTIPLIER_BY_ID = {level["id"]: level["multiplier"] for level in ACTIVITY_LEVELS}
MIN_ACTIVITY_MULTIPLIER = ACTIVITY_LEVELS[0]["multiplier"]
MAX_ACTIVITY_MULTIPLIER = ACTIVITY_LEVELS[-1]["multiplier"]


def resolve_activity_multiplier(data: dict) -> float:
    """從 activity_level 或 activity_multiplier 推出係數，並限制在合理範圍。

    客戶端可以送標籤或數字，但不能送出 1.2~1.9 以外的值——那會讓每日熱量
    目標偏離到沒有意義，而這個數字最後會決定推薦哪些餐點。
    """
    level = data.get("activity_level")
    if level in ACTIVITY_MULTIPLIER_BY_ID:
        return ACTIVITY_MULTIPLIER_BY_ID[level]
    if level in ACTIVITY_MULTIPLIER_BY_LABEL:
        return ACTIVITY_MULTIPLIER_BY_LABEL[level]

    raw = data.get("activity_multiplier")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.55
    return min(max(value, MIN_ACTIVITY_MULTIPLIER), MAX_ACTIVITY_MULTIPLIER)


def compute_bmr(gender: str, weight: float, height: float, age: int) -> float:
    if gender == "male":
        return round(10 * weight + 6.25 * height - 5 * age + 5)
    return round(10 * weight + 6.25 * height - 5 * age - 161)


def compute_tdee(bmr: float, activity_multiplier: float) -> float:
    return round(bmr * activity_multiplier)


def resolve_energy_factor(activity_multiplier: float) -> int:
    """每公斤理想體重要給幾大卡，依活動量分級。

    先前不分活動量一律 25 或 30，等於把每個人都當成輕度活動：一位選了
    「中等活動」的使用者拿到的每日目標會比他的 BMR 還低。臨床營養的熱量
    需求本來就是依活動量分級開的，這裡照同一組級距對應到 App 既有的
    五個活動量選項（ACTIVITY_LEVELS 的 multiplier）。

    放在這裡是因為每日目標（nutrition_progress_service）與單餐上限
    （medical_risk_service）都要用同一個級距；分成兩份就會各自漂移。
    """
    if activity_multiplier <= 1.2:
        return 25  # 久坐／臥床
    if activity_multiplier <= 1.375:
        return 30  # 輕度活動
    if activity_multiplier <= 1.55:
        return 35  # 中等活動
    return 40  # 高度／極高活動


def build_user_profile(data: dict, disease_rules: dict | None = None, allergen_taxonomy: dict | None = None) -> dict:
    user_id = data["user_id"]
    gender = data.get("gender", "male")
    # 範圍檢查放在這裡而不是路由層，是因為每一條寫入路徑都會經過這個函式。
    weight = _validate_range("weight", data.get("weight", 70))
    height = _validate_range("height", data.get("height", 170))
    age = int(_validate_range("age", data.get("age", 25)))
    target_weight = data.get("target_weight")
    if target_weight is not None:
        target_weight = _validate_range("target_weight", target_weight)
    activity_multiplier = resolve_activity_multiplier(data)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity_multiplier)

    health_conditions = data.get("health_conditions", [])
    allergens = data.get("allergens", [])
    if disease_rules:
        health_conditions = normalize_condition_ids(health_conditions, disease_rules)
    if allergen_taxonomy:
        allergens = normalize_allergen_ids(allergens, allergen_taxonomy)

    return {
        "user_id": user_id,
        "name": data.get("name", ""),
        "gender": gender,
        "height": height,
        "weight": weight,
        "age": age,
        "activity_level": next(
            (level["label_zh"] for level in ACTIVITY_LEVELS if level["multiplier"] == activity_multiplier),
            data.get("activity_level", "中等活動量"),
        ),
        "activity_multiplier": activity_multiplier,
        "bmi": round(weight / ((height / 100) ** 2), 1),
        "bmr": bmr,
        "tdee": tdee,
        "daily_calorie_target": (
            int(_validate_range("daily_calorie_target", data["daily_calorie_target"]))
            if data.get("daily_calorie_target") is not None
            else tdee
        ),
        "health_conditions": health_conditions,
        "allergens": allergens,
        "target_weight": target_weight,
        # 「這份檔案的數字是使用者自己填的嗎？」
        #
        # 帳號第一次登入時前端會先建一份空白檔案，否則其他 API 全部 404。
        # 但那份檔案裡的身高體重是預設值，不是任何人填的——沒有這個旗標，
        # 畫面就沒辦法分辨「他填了 170cm」跟「我們猜他 170cm」，於是會把
        # 一組沒人確認過的數字當成健康檔案顯示並拿去算每日目標。
        "profile_complete": bool(data.get("profile_complete", False)),
        # 前端的選項只有葷食／素食（frontend/constants/diet.ts）。
        # 不在選單裡的值（含舊帳號存下來的「均衡飲食」）一律換成預設值，
        # 否則「我的」頁的儲存鈕會永遠是灰的。
        "diet_type": normalize_diet_type(data.get("diet_type")),
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }


def build_bmr_response(data: dict) -> dict:
    gender = data.get("gender", "male")
    weight = data.get("weight", 70)
    height = data.get("height", 170)
    age = data.get("age", 25)
    activity = resolve_activity_multiplier(data)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity)

    return {
        "bmr": bmr,
        "tdee": tdee,
        "formula": "Mifflin-St Jeor",
        "gender": gender,
        "bmi": round(weight / ((height / 100) ** 2), 1),
    }
