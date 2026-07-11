from services.disease_rule_service import normalize_allergen_ids, normalize_condition_ids


NUTRIENT_FIELDS = {
    "sodium": ("sodium", "mg"),
    "carbs": ("carbs", "g"),
    "protein": ("protein", "g"),
    "fat": ("fat", "g"),
    "sugar": ("sugar", "g"),
}


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
) -> dict:
    conditions = normalize_condition_ids(user_conditions, disease_rules)
    allergens = normalize_allergen_ids(user_allergens, allergen_taxonomy)
    nutrients = scale_nutrients(candidate, portion_g)

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
