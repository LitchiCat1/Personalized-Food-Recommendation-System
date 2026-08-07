from services.disease_rule_service import normalize_allergen_ids, normalize_condition_ids


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
    "calcium": ("calcium", "mg"),
    "iron": ("iron", "mg"),
}


def _is_fried_food(candidate: dict) -> bool:
    if candidate.get("is_fried") is True:
        return True
    name = (candidate.get("name_zh") or candidate.get("name") or candidate.get("label") or "").lower()
    fried_keywords = ["油炸", "炸雞", "炸排骨", "炸魚", "炸豬排", "炸蝦", "薯條", "天婦羅", "雞塊", "炸物", "炸起司", "酥炸"]
    return any(k in name for k in fried_keywords)



def normalize_number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_text(value) -> str:
    return str(value or "").strip()


def scale_nutrients(nutrients: dict, portion_g: float | None = None) -> dict:
    if not portion_g:
        return {key: normalize_number(nutrients.get(source_key)) for key, (source_key, _unit) in NUTRIENT_FIELDS.items()}

    scale = normalize_number(portion_g) / 100.0
    return {
        key: normalize_number(nutrients.get(source_key)) * scale
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
        height_cm = float(user_profile.get("height") or 170.0)
        weight_kg = float(user_profile.get("weight") or 65.0)
        daily_calorie_target = float(user_profile.get("daily_calorie_target") or user_profile.get("dailyCalorieTarget") or (weight_kg * 30))
        
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

        # C. 糖尿病 (Diabetes) 專屬評估 (單餐 = 每日目標 / 3)
        if condition_id == "diabetes":
            # 總熱量
            cal_val = normalize_number(nutrients.get("calories"))
            cal_limit = E / 3.0
            if cal_val > cal_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐熱量 {cal_val:.0f} kcal 超過建議 {cal_limit:.0f} kcal (目標 W*30 或 W*25)。",
                    "nutrient": "calories",
                    "value": cal_val,
                    "limit": cal_limit,
                    "unit": "kcal",
                })
            # 總碳水 (比例 45%-50% -> 上限取 50%)
            carbs_val = normalize_number(nutrients.get("carbs"))
            carbs_limit = (E * 0.50) / 4.0 / 3.0
            if carbs_val > carbs_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐碳水化合物 {carbs_val:.1f}g 超過上限 {carbs_limit:.1f}g (限制比例 50%)。",
                    "nutrient": "carbs",
                    "value": carbs_val,
                    "limit": carbs_limit,
                    "unit": "g",
                })
            # 精緻糖 (< 5% 且 < 25g)
            sugar_val = normalize_number(nutrients.get("sugar"))
            sugar_limit = min((E * 0.05) / 4.0, 25.0) / 3.0
            if sugar_val > sugar_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐精緻糖 {sugar_val:.1f}g 超過上限 {sugar_limit:.1f}g (上限 5% 且 < 25g)。",
                    "nutrient": "sugar",
                    "value": sugar_val,
                    "limit": sugar_limit,
                    "unit": "g",
                })

        # D. 痛風 (Gout) 專屬評估 (單餐 = 每日目標 / 3)
        elif condition_id == "gout":
            # 總熱量
            cal_val = normalize_number(nutrients.get("calories"))
            cal_limit = E / 3.0
            if cal_val > cal_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐熱量 {cal_val:.0f} kcal 超過建議 {cal_limit:.0f} kcal。",
                    "nutrient": "calories",
                    "value": cal_val,
                    "limit": cal_limit,
                    "unit": "kcal",
                })
            # 總脂肪 (< 25%)
            fat_val = normalize_number(nutrients.get("fat"))
            fat_limit = (E * 0.25) / 9.0 / 3.0
            if fat_val > fat_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐總脂肪 {fat_val:.1f}g 超過建議 {fat_limit:.1f}g (高脂影響尿酸排泄)。",
                    "nutrient": "fat",
                    "value": fat_val,
                    "limit": fat_limit,
                    "unit": "g",
                })

        # E. 高血脂 (Hyperlipidemia) 專屬評估 (單餐 = 每日目標 / 3)
        elif condition_id == "hyperlipidemia":
            # 總熱量
            cal_val = normalize_number(nutrients.get("calories"))
            cal_limit = E / 3.0
            if cal_val > cal_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐熱量 {cal_val:.0f} kcal 超過建議 {cal_limit:.0f} kcal。",
                    "nutrient": "calories",
                    "value": cal_val,
                    "limit": cal_limit,
                    "unit": "kcal",
                })
            # 總脂肪 (< 25% 低脂飲食)
            fat_val = normalize_number(nutrients.get("fat"))
            fat_limit = (E * 0.25) / 9.0 / 3.0
            if fat_val > fat_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐總脂肪 {fat_val:.1f}g 超過低脂上限 {fat_limit:.1f}g。",
                    "nutrient": "fat",
                    "value": fat_val,
                    "limit": fat_limit,
                    "unit": "g",
                })
            # 飽和脂肪 (< 7% 嚴格控管)
            sat_fat_val = normalize_number(nutrients.get("saturated_fat"))
            sat_fat_limit = (E * 0.07) / 9.0 / 3.0
            if sat_fat_val > sat_fat_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐飽和脂肪 {sat_fat_val:.1f}g 超過限額 {sat_fat_limit:.1f}g (嚴格控管 7%)。",
                    "nutrient": "saturated_fat",
                    "value": sat_fat_val,
                    "limit": sat_fat_limit,
                    "unit": "g",
                })

        # F. 高血壓 (Hypertension) 專屬評估 (單餐 = 每日目標 / 3)
        elif condition_id == "hypertension":
            # 總熱量
            cal_val = normalize_number(nutrients.get("calories"))
            cal_limit = E / 3.0
            if cal_val > cal_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐熱量 {cal_val:.0f} kcal 超過建議 {cal_limit:.0f} kcal。",
                    "nutrient": "calories",
                    "value": cal_val,
                    "limit": cal_limit,
                    "unit": "kcal",
                })
            # 鈉含量 (< 2000mg 得舒飲食)
            sodium_val = normalize_number(nutrients.get("sodium"))
            sodium_limit = 2000.0 / 3.0
            if sodium_val > sodium_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐鈉含量 {sodium_val:.0f} mg 超過限額 {sodium_limit:.0f} mg (得舒飲食核心)。",
                    "nutrient": "sodium",
                    "value": sodium_val,
                    "limit": sodium_limit,
                    "unit": "mg",
                })

        # G. 慢性腎臟病 (Kidney Disease, 3-5期) 專屬評估 (單餐 = 每日目標 / 3)
        elif condition_id == "kidney_disease":
            # 蛋白質 (W*0.6 ~ W*0.8, 嚴格限量上限為 W*0.8)
            prot_val = normalize_number(nutrients.get("protein"))
            prot_limit = (W * 0.8) / 3.0
            if prot_val > prot_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐蛋白質 {prot_val:.1f}g 超過【嚴格限量】上限 {prot_limit:.1f}g (依體重 W*0.8 計)。",
                    "nutrient": "protein",
                    "value": prot_val,
                    "limit": prot_limit,
                    "unit": "g",
                })
            # 鈉含量 (< 1500mg)
            sodium_val = normalize_number(nutrients.get("sodium"))
            sodium_limit = 1500.0 / 3.0
            if sodium_val > sodium_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐鈉含量 {sodium_val:.0f} mg 超過慢性腎臟病建議上限 {sodium_limit:.0f} mg。",
                    "nutrient": "sodium",
                    "value": sodium_val,
                    "limit": sodium_limit,
                    "unit": "mg",
                })
            # 鈣含量 (< 800mg)
            calcium_val = normalize_number(nutrients.get("calcium"))
            calcium_limit = 800.0 / 3.0
            if calcium_val > calcium_limit:
                risks.append({
                    "type": "nutrient_limit",
                    "severity": "block",
                    "condition_id": condition_id,
                    "condition_label_zh": condition_label,
                    "message": f"{condition_label}風險：單餐鈣含量 {calcium_val:.0f} mg 超過限額 {calcium_limit:.0f} mg (防高磷高血鈣)。",
                    "nutrient": "calcium",
                    "value": calcium_val,
                    "limit": calcium_limit,
                    "unit": "mg",
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
