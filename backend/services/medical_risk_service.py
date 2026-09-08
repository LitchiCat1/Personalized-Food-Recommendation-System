from services.disease_rule_service import normalize_allergen_ids, normalize_condition_ids
from services.nutrient_service import get_nutrient_value, is_fried_food_name


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
    meals = float(spec.get("meals_per_day") or 3) or 3
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

    # 1. 取得使用者身高體重計算理想體重 (W) 與每日熱量 (E)
    height_cm = 170.0
    weight_kg = 65.0
    daily_calorie_target = 1950.0
    
    if user_profile:
        height_cm = normalize_number(user_profile.get("height")) or 170.0
        weight_kg = normalize_number(user_profile.get("weight")) or 65.0
        daily_calorie_target = normalize_number(
            user_profile.get("daily_calorie_target") or user_profile.get("dailyCalorieTarget")
        ) or (weight_kg * 30)
        
    height_m = height_cm / 100.0
    W = 22.0 * (height_m ** 2)
    if W <= 0:
        W = weight_kg
    
    bmi = weight_kg / (height_m ** 2) if height_m > 0 else 22.0
    is_overweight = bmi >= 24.0
    
    # 決定不同疾病下的每日總熱量需求 E (取各匹配疾病最嚴格值)
    e_candidates = []
    if "diabetes" in conditions:
        e_candidates.append(W * 25 if is_overweight else W * 30)
    if "gout" in conditions:
        e_candidates.append(W * 30)
    if "hyperlipidemia" in conditions:
        e_candidates.append(W * 25 if is_overweight else W * 30)
    if "hypertension" in conditions:
        e_candidates.append(W * 30)
    if "kidney_disease" in conditions:
        e_candidates.append(W * 30) # 慢性腎臟病取 30 (熱量需足夠防肌肉流失)
        
    E = min(e_candidates) if e_candidates else daily_calorie_target
    if E <= 0:
        E = W * 30

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
                "message": (
                    f"{condition_label}風險：單餐{label} {value:.1f}{unit} "
                    f"超過上限 {limit:.1f}{unit}" + (f"（{note}）。" if note else "。")
                ),
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


def risk_messages(risk_result: dict) -> list[str]:
    return [*risk_result.get("block_reasons", []), *risk_result.get("caution_reasons", [])]


# ─── 門檻一致性檢查 ────────────────────────────────────────
# disease_rules.json 是有引用、有審閱紀錄的治理檔案；上面這些依理想體重推算
# 的公式是另一套。兩邊對同一個營養素給不同數字時，寬的那條永遠不會生效——
# 審閱者看檔案簽核的數字，跟系統實際執行的可能不同。臨床門檻不該由程式自行
# 挑選，所以這裡不改數字，只把分歧列出來讓人去對。
def derived_meal_limits(disease_rules: dict, user_profile: dict | None = None) -> dict:
    """把規則檔宣告的個人化上限算成實際數字。

    先前這裡自己抄了一份公式，等於第三套會漂移的數字。現在跟
    evaluate_medical_risk 讀同一份宣告。
    """
    height_cm = normalize_number((user_profile or {}).get("height")) or 170.0
    weight_kg = normalize_number((user_profile or {}).get("weight")) or 65.0
    W = 22.0 * (height_cm / 100.0) ** 2 or weight_kg
    E = W * 30
    limits = {}
    for condition_id, rule in (disease_rules or {}).items():
        resolved = {}
        for nutrient, spec in (rule.get("personalized_limits") or {}).items():
            value = resolve_personalized_limit(spec, E, W)
            if value is not None:
                resolved[nutrient] = value
        if resolved:
            limits[condition_id] = resolved
    return limits


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
            conflicts.append({
                "condition_id": condition_id,
                "nutrient": nutrient,
                "configured_block": round(configured_limit, 1),
                "derived_block": round(formula_limit, 1),
                "effective_block": round(min(configured_limit, formula_limit), 1),
                "ignored_source": "derived" if configured_limit < formula_limit else "configured",
            })
    return conflicts
