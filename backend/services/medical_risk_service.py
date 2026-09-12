from services.disease_rule_service import normalize_allergen_ids, normalize_condition_ids
from services.nutrient_service import get_nutrient_value, is_fried_food_name
from services.profile_service import compute_bmr, resolve_energy_factor


# 一天切成幾餐。disease_rules.json 的 personalized_limits 用它把每日總量
# 換算成單餐上限，前端 lib/meal.ts 的 MEALS_PER_DAY 是同一個數字。
MEALS_PER_DAY = 3

NUTRIENT_FIELDS = {
    "calories": ("calories", "kcal"),
    "sodium": ("sodium", "mg"),
    "carbs": ("carbs", "g"),
    "protein": ("protein", "g"),
    "fat": ("fat", "g"),
    "sugar": ("sugar", "g"),
    "saturated_fat": ("saturated_fat", "g"),
    "trans_fat": ("trans_fat", "g"),
    "fiber": ("fiber", "g"),
}


def _is_fried_food(candidate: dict) -> bool:
    return candidate.get("is_fried") is True or is_fried_food_name(
        candidate.get("name_zh"),
        candidate.get("name"),
        candidate.get("label"),
    )



def normalize_number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_text(value) -> str:
    return str(value or "").strip()


def scale_nutrients(nutrients: dict, portion_g: float | None = None) -> dict:
    if not portion_g:
        return {
            key: normalize_number(get_nutrient_value(nutrients, source_key))
            for key, (source_key, _unit) in NUTRIENT_FIELDS.items()
        }

    scale = normalize_number(portion_g) / 100.0
    return {
        key: normalize_number(get_nutrient_value(nutrients, source_key)) * scale
        for key, (source_key, _unit) in NUTRIENT_FIELDS.items()
    }


def build_allergen_groups(taxonomy: dict) -> dict:
    return {group["id"]: group for group in taxonomy.get("groups", [])}


def _candidate_text(candidate: dict) -> str:
    values = [
        candidate.get("label"),
        candidate.get("name"),
        candidate.get("name_zh"),
        candidate.get("item_name"),
        candidate.get("ingredients_text"),
        " ".join(candidate.get("ingredients") or []),
        " ".join(candidate.get("allergens") or []),
    ]
    return " ".join(normalize_text(value).lower() for value in values if value)


def detect_allergen_hits(candidate: dict, user_allergens: list, taxonomy: dict) -> list[dict]:
    selected = normalize_allergen_ids(user_allergens, taxonomy)
    groups = build_allergen_groups(taxonomy)
    haystack = _candidate_text(candidate)
    explicit_allergens = normalize_allergen_ids(candidate.get("allergens") or [], taxonomy)
    hits = []

    for allergen_id in selected:
        group = groups.get(allergen_id)
        if not group:
            continue
        explicit_match = allergen_id in explicit_allergens
        keyword = next((word for word in group.get("keywords", []) if normalize_text(word).lower() in haystack), None)
        if explicit_match or keyword:
            hits.append(
                {
                    "type": "allergen",
                    "severity": "block",
                    "allergen_id": allergen_id,
                    "label_zh": group["label_zh"],
                    "message": f"含有或疑似含有過敏原：{group['label_zh']}",
                    "matched_by": "explicit_allergen" if explicit_match else "keyword",
                    "matched_value": group["label_zh"] if explicit_match else keyword,
                }
            )
    return hits


def _condition_keyword_hits(candidate: dict, condition_id: str, rule: dict) -> list[dict]:
    haystack = _candidate_text(candidate)
    hits = []
    for keyword in rule.get("blocked_keywords", []):
        if normalize_text(keyword).lower() in haystack:
            hits.append(
                {
                    "type": "condition_keyword",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": rule.get("label_zh", condition_id),
                    "message": f"{rule.get('label_zh', condition_id)}需避開或確認：{keyword}",
                    "matched_value": keyword,
                }
            )
    return hits


def _condition_label_hits(candidate: dict, condition_id: str, rule: dict) -> list[dict]:
    label = normalize_text(candidate.get("label") or candidate.get("item_id") or candidate.get("item_name")).lower()
    blocked_labels = [normalize_text(value).lower() for value in rule.get("blocked_labels", [])]
    if label and label in blocked_labels:
        return [
            {
                "type": "condition_label",
                "severity": "block",
                "condition_id": condition_id,
                "condition_label_zh": rule.get("label_zh", condition_id),
                "message": f"{rule.get('label_zh', condition_id)}不建議此品項",
                "matched_value": label,
            }
        ]
    return []


def _condition_gi_hits(candidate: dict, condition_id: str, rule: dict) -> list[dict]:
    gi = candidate.get("gi")
    if gi and gi in rule.get("blocked_gi", []):
        return [
            {
                "type": "glycemic_index",
                "severity": "block",
                "condition_id": condition_id,
                "condition_label_zh": rule.get("label_zh", condition_id),
                "message": f"{rule.get('label_zh', condition_id)}需避免高 GI 餐點",
                "nutrient": "gi",
                "value": gi,
                "limit": rule.get("blocked_gi"),
            }
        ]
    return []


def _condition_nutrient_hits(nutrients: dict, condition_id: str, rule: dict) -> list[dict]:
    hits = []
    condition_label = rule.get("label_zh", condition_id)
    for nutrient, meta in rule.get("risk_nutrients", {}).items():
        # 臨床人員若裁決這個營養素採用公式那一套，規則檔的 block 就不生效。
        decided = threshold_resolution(rule, nutrient)
        if decided and decided["use"] == "derived":
            continue
        value = normalize_number(nutrients.get(nutrient))
        caution = meta.get("caution")
        block = meta.get("block")
        unit = meta.get("unit", "")
        label = meta.get("label_zh", nutrient)
        if block is not None and value > normalize_number(block):
            hits.append(
                {
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：{label} {value:.0f}{unit} 超過建議上限 {block}{unit}",
                    "nutrient": nutrient,
                    "value": round(value, 1),
                    "limit": block,
                    "unit": unit,
                }
            )
        elif caution is not None and value > normalize_number(caution):
            hits.append(
                {
                    "type": "nutrient_limit",
                    "severity": "caution",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}提醒：{label} {value:.0f}{unit} 接近控管門檻",
                    "nutrient": nutrient,
                    "value": round(value, 1),
                    "limit": caution,
                    "unit": unit,
                }
            )
    return hits


NUTRIENT_LABELS_ZH = {
    "calories": "熱量", "protein": "蛋白質", "carbs": "碳水化合物", "sugar": "精緻糖",
    "fat": "總脂肪", "saturated_fat": "飽和脂肪", "trans_fat": "反式脂肪",
    "fiber": "膳食纖維", "sodium": "鈉",
}


def resolve_personalized_limit(spec: dict, daily_energy: float, ideal_weight: float):
    """把 disease_rules.json 宣告的單餐上限算成一個數字。

    只支援三種基準，不做字串求值——規則檔是資料，不該能執行任意運算式。
      daily_energy      每日熱量的一部分，可再用 kcal_per_gram 換算成公克
      ideal_body_weight 每公斤理想體重多少公克
      absolute          直接給每日總量
    """
    meals = float(spec.get("meals_per_day") or MEALS_PER_DAY) or MEALS_PER_DAY
    basis = spec.get("basis")

    if basis == "daily_energy":
        daily = daily_energy * float(spec.get("share", 1.0))
        per_gram = spec.get("kcal_per_gram")
        if per_gram:
            daily = daily / float(per_gram)
    elif basis == "ideal_body_weight":
        daily = ideal_weight * float(spec.get("per_kg", 0))
    elif basis == "absolute":
        daily = float(spec.get("daily_amount", 0))
    else:
        return None

    cap = spec.get("cap")
    if cap is not None:
        daily = min(daily, float(cap))
    return daily / meals


def evaluate_medical_risk(
    candidate: dict,
    user_conditions: list,
    user_allergens: list,
    disease_rules: dict,
    allergen_taxonomy: dict,
    portion_g: float | None = None,
    user_profile: dict | None = None,
) -> dict:
    conditions = normalize_condition_ids(user_conditions, disease_rules)
    allergens = normalize_allergen_ids(user_allergens, allergen_taxonomy)
    nutrients = scale_nutrients(candidate, portion_g)

    # 理想體重 W 與每日熱量 E。先前這裡自己抄了一份公式，跟下面的
    # resolve_user_energy_and_weight 是兩套會各自漂移的數字——這個檔案已經
    # 因為「同一個數字兩套算法」出過事，所以只留一份。
    E, W = resolve_user_energy_and_weight(conditions, user_profile)

    risks = []
    risks.extend(detect_allergen_hits(candidate, allergens, allergen_taxonomy))

    for condition_id in conditions:
        rule = disease_rules.get(condition_id)
        if not rule:
            continue
        risks.extend(_condition_gi_hits(candidate, condition_id, rule))
        risks.extend(_condition_label_hits(candidate, condition_id, rule))
        risks.extend(_condition_keyword_hits(candidate, condition_id, rule))
        risks.extend(_condition_nutrient_hits(nutrients, condition_id, rule))
        
        condition_label = rule.get("label_zh", condition_id)
        
        # A. 判斷油炸食物 (根據 PDF 疾病推薦烹調方式)
        if _is_fried_food(candidate):
            if condition_id in ["gout", "hyperlipidemia"]:
                risks.append({
                    "type": "fried_food",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：油炸食物屬於【嚴格禁止】類別。",
                })
            elif condition_id in ["diabetes", "hypertension", "kidney_disease"]:
                risks.append({
                    "type": "fried_food",
                    "severity": "caution",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}提醒：油炸食物應【極力避免】。",
                })

        # B. 判斷反式脂肪 (反式脂肪 0g 完全禁止 for all 5 conditions)
        trans_fat_val = normalize_number(nutrients.get("trans_fat"))
        if trans_fat_val > 0.1:
            risks.append({
                "type": "nutrient_limit",
                "severity": "block",
                "condition_id": condition_id,
                "condition_label_zh": condition_label,
                "message": f"{condition_label}風險：含有反式脂肪 {trans_fat_val:.1f}g，【完全禁止】攝取。",
                "nutrient": "trans_fat",
                "value": trans_fat_val,
                "limit": 0.0,
                "unit": "g",
            })

        # 依個人理想體重推算的單餐上限。公式宣告在 disease_rules.json 的
        # personalized_limits，這裡只負責求值——先前每個疾病各寫一段 if，
        # 跟規則檔的 risk_nutrients 形成兩套會各自漂移的數字。
        for nutrient, spec in (rule.get("personalized_limits") or {}).items():
            decided = threshold_resolution(rule, nutrient)
            if decided and decided["use"] == "configured":
                continue
            limit = resolve_personalized_limit(spec, E, W)
            if limit is None:
                continue
            value = normalize_number(nutrients.get(nutrient))
            if value <= limit:
                continue
            unit = spec.get("unit", "")
            note = spec.get("note")
            label = NUTRIENT_LABELS_ZH.get(nutrient, nutrient)
            risks.append({
                "type": "nutrient_limit",
                "severity": "block",
                "condition_id": condition_id,
                "condition_label_zh": condition_label,
                # 這裡評的是「一道菜」，但門檻是整餐的額度（每日 ÷ 3）。
                # 先前訊息寫「單餐」，讓人以為整餐都算過了，其實一餐點兩道
                # 各 490mg 會全部通過。用詞要說清楚在比什麼。
                "message": (
                    f"{condition_label}風險：這一道{label} {value:.1f}{unit}，"
                    f"已超過整餐上限 {limit:.1f}{unit}" + (f"（{note}）。" if note else "。")
                ),
                "scope": "item",
                "nutrient": nutrient,
                "value": value,
                "limit": limit,
                "unit": unit,
            })

    block_reasons = [risk["message"] for risk in risks if risk["severity"] == "block"]
    caution_reasons = [risk["message"] for risk in risks if risk["severity"] == "caution"]
    return {
        "is_safe": not block_reasons,
        "has_caution": bool(caution_reasons),
        "risks": risks,
        "block_reasons": block_reasons,
        "caution_reasons": caution_reasons,
        "normalized_conditions": conditions,
        "normalized_allergens": allergens,
    }


def resolve_user_energy_and_weight(conditions: list, user_profile: dict | None) -> tuple[float, float]:
    """算出這個人的每日熱量需求 E 與理想體重 W。

    單餐上限（disease_rules.json 的 personalized_limits）都是從 E 換算出來的，
    所以這裡的 E 必須跟「我的」頁面顯示的每日目標是同一個數字——那邊走的是
    nutrition_progress_service.calculate_daily_targets_with_basis()。先前這裡
    寫死每公斤 25／30 大卡、不看活動量也不設下限，於是選「中等活動」的人，
    單餐額度是用一個比他 BMR 還低的每日熱量推出來的，跟畫面上的目標對不起來。
    """
    height_cm = 170.0
    weight_kg = 65.0
    daily_calorie_target = 0.0
    activity_multiplier = 1.55

    if user_profile:
        height_cm = normalize_number(user_profile.get("height")) or 170.0
        weight_kg = normalize_number(user_profile.get("weight")) or 65.0
        daily_calorie_target = normalize_number(
            user_profile.get("daily_calorie_target") or user_profile.get("dailyCalorieTarget")
        )
        activity_multiplier = normalize_number(
            user_profile.get("activity_multiplier") or user_profile.get("activityMultiplier")
        ) or 1.55

    height_m = height_cm / 100.0
    W = 22.0 * (height_m ** 2)
    if W <= 0:
        W = weight_kg

    bmi = weight_kg / (height_m ** 2) if height_m > 0 else 22.0
    is_overweight = bmi >= 24.0

    energy_factor = resolve_energy_factor(activity_multiplier)
    # 糖尿病與高血脂的指引本身就含減重目標，過重時往下調一級；
    # 痛風／高血壓／腎病不做這個減量。
    weight_managed_factor = max(energy_factor - 5, 20) if is_overweight else energy_factor

    e_candidates = []
    if "diabetes" in conditions:
        e_candidates.append(W * weight_managed_factor)
    if "gout" in conditions:
        e_candidates.append(W * energy_factor)
    if "hyperlipidemia" in conditions:
        e_candidates.append(W * weight_managed_factor)
    if "hypertension" in conditions:
        e_candidates.append(W * energy_factor)
    if "kidney_disease" in conditions:
        e_candidates.append(W * energy_factor)  # 熱量需足夠防肌肉流失

    if e_candidates:
        E = min(e_candidates)
        # 疾病目標是 App 幫使用者決定的，不能低到基礎代謝以下；
        # 使用者自己填的數字則尊重他的選擇。
        bmr = _profile_bmr(user_profile, weight_kg, height_cm)
        if bmr > 0 and E < bmr:
            E = bmr
    else:
        E = daily_calorie_target

    if E <= 0:
        E = W * energy_factor
    return E, W


def _profile_bmr(user_profile: dict | None, weight_kg: float, height_cm: float) -> float:
    """拿 profile 存好的 BMR，沒有就用同一條公式現算。"""
    profile = user_profile or {}
    stored = normalize_number(profile.get("bmr") or profile.get("bmr_kcal"))
    if stored > 0:
        return stored
    gender = normalize_text(profile.get("gender")) or "male"
    age = normalize_number(profile.get("age")) or 30.0
    return float(compute_bmr(gender, weight_kg, height_cm, int(age)))


def evaluate_meal_medical_risk(
    items: list[dict],
    user_conditions: list,
    user_allergens: list,
    disease_rules: dict,
    allergen_taxonomy: dict,
    user_profile: dict | None = None,
) -> dict:
    """檢查「一餐合計」有沒有超過單餐上限。

    personalized_limits 是每日總量 ÷ 3，也就是**一餐**的額度，但
    evaluate_medical_risk 是逐道菜呼叫的。結果是：一餐點兩道各 490mg 的菜
    全部通過（合計 980mg，遠超 667mg 的上限），單獨一道 510mg 的反而被擋。
    逐道檢查抓的是「單一道菜就爆掉」，抓不到「加起來爆掉」——這裡補上後者。

    items 每個元素是 {"nutrients": {...}, "portion_g": 份量或 None}。
    """
    conditions = normalize_condition_ids(user_conditions, disease_rules)
    if not conditions or not items:
        return {"is_safe": True, "has_caution": False, "risks": [], "block_reasons": [], "caution_reasons": []}

    totals = {key: 0.0 for key in NUTRIENT_FIELDS}
    for item in items:
        scaled = scale_nutrients(item.get("nutrients") or {}, item.get("portion_g"))
        for key, value in scaled.items():
            totals[key] += normalize_number(value)

    E, W = resolve_user_energy_and_weight(conditions, user_profile)

    risks = []
    for condition_id in conditions:
        rule = disease_rules.get(condition_id)
        if not rule:
            continue
        condition_label = rule.get("label_zh", condition_id)
        for nutrient, spec in (rule.get("personalized_limits") or {}).items():
            decided = threshold_resolution(rule, nutrient)
            if decided and decided["use"] == "configured":
                continue
            limit = resolve_personalized_limit(spec, E, W)
            if limit is None:
                continue
            value = totals.get(nutrient, 0.0)
            if value <= limit:
                continue
            unit = spec.get("unit", "")
            label = NUTRIENT_LABELS_ZH.get(nutrient, nutrient)
            risks.append({
                "type": "meal_nutrient_limit",
                # 每一道都在額度內、加起來才超過，是提醒而不是封鎖：
                # 使用者已經把這些菜放在一起了，該做的是告訴他總量超了。
                "severity": "caution",
                "scope": "meal",
                "condition_id": condition_id,
                "condition_label_zh": condition_label,
                "message": (
                    f"{condition_label}提醒：這一餐合計{label} {value:.1f}{unit}，"
                    f"超過單餐上限 {limit:.1f}{unit}（每道菜單獨看都在範圍內）。"
                ),
                "nutrient": nutrient,
                "value": round(value, 1),
                "limit": round(limit, 1),
                "unit": unit,
                "item_count": len(items),
            })

    caution_reasons = [risk["message"] for risk in risks]
    return {
        "is_safe": True,
        "has_caution": bool(caution_reasons),
        "risks": risks,
        "block_reasons": [],
        "caution_reasons": caution_reasons,
    }


def risk_messages(risk_result: dict) -> list[str]:
    return [*risk_result.get("block_reasons", []), *risk_result.get("caution_reasons", [])]


# ─── 門檻一致性檢查 ────────────────────────────────────────
# disease_rules.json 是有引用、有審閱紀錄的治理檔案；上面這些依理想體重推算
# 的公式是另一套。兩邊對同一個營養素給不同數字時，寬的那條永遠不會生效——
# 審閱者看檔案簽核的數字，跟系統實際執行的可能不同。臨床門檻不該由程式自行
# 挑選，所以這裡不改數字，只把分歧列出來讓人去對。
def derived_meal_limits(disease_rules: dict, user_profile: dict | None = None) -> dict:
    """把規則檔宣告的個人化上限算成實際數字。

    先前這裡自己抄了一份公式（固定 W×30、不看活動量），等於第三套會漂移的
    數字。現在跟 evaluate_medical_risk 走同一支 resolve_user_energy_and_weight。

    這支是給「門檻一致性檢查」用的，要列出每個疾病各自的上限，所以逐一
    帶入單一疾病去算，而不是取所有疾病的最嚴格值。
    """
    limits = {}
    for condition_id, rule in (disease_rules or {}).items():
        E, W = resolve_user_energy_and_weight([condition_id], user_profile)
        resolved = {}
        for nutrient, spec in (rule.get("personalized_limits") or {}).items():
            value = resolve_personalized_limit(spec, E, W)
            if value is not None:
                resolved[nutrient] = value
        if resolved:
            limits[condition_id] = resolved
    return limits


def threshold_resolution(rule: dict, nutrient: str) -> dict | None:
    """臨床人員對某個營養素「該採用哪一套門檻」的裁決，沒有就回 None。

    規則檔裡長這樣：

        "threshold_resolutions": {
          "sodium": {
            "use": "configured",              # 或 "derived"
            "decided_by": "...", "decided_on": "2026-07-01",
            "note": "…為什麼"
          }
        }

    沒有裁決時，兩套檢查都會跑，等於自動採用較嚴的那一組——那是安全的
    預設，但它是「兩段程式各跑一次」的副作用，不是有人決定的結果。把裁決
    寫進規則檔，才會跟簽核紀錄、引用來源放在同一個地方。
    """
    resolution = ((rule.get("threshold_resolutions") or {}).get(nutrient) or None)
    if not isinstance(resolution, dict):
        return None
    if resolution.get("use") not in ("configured", "derived"):
        return None
    return resolution


def rule_threshold_conflicts(disease_rules: dict, user_profile: dict | None = None) -> list[dict]:
    """列出兩套門檻不一致的地方，並指出實際生效的是哪一個。"""
    derived = derived_meal_limits(disease_rules, user_profile)
    conflicts = []
    for condition_id, rule in (disease_rules or {}).items():
        configured = (rule.get("risk_nutrients") or {})
        for nutrient, formula_limit in derived.get(condition_id, {}).items():
            configured_limit = normalize_number((configured.get(nutrient) or {}).get("block"))
            if not configured_limit or not formula_limit:
                continue
            if abs(configured_limit - formula_limit) < 0.5:
                continue

            resolution = threshold_resolution(rule, nutrient)
            if resolution:
                effective = configured_limit if resolution["use"] == "configured" else formula_limit
                ignored = "derived" if resolution["use"] == "configured" else "configured"
            else:
                # 還沒有人裁決：維持較嚴的那一組。
                effective = min(configured_limit, formula_limit)
                ignored = "derived" if configured_limit < formula_limit else "configured"

            conflicts.append({
                "condition_id": condition_id,
                "nutrient": nutrient,
                "configured_block": round(configured_limit, 1),
                "derived_block": round(formula_limit, 1),
                "effective_block": round(effective, 1),
                "ignored_source": ignored,
                "resolved": bool(resolution),
                "resolution": resolution,
            })
    return conflicts
