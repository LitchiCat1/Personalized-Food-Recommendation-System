import json
import os


GOVERNANCE_FIELDS = {
    "rule_version",
    "review_status",
    "last_reviewed",
    "reviewed_by",
    "evidence_level",
    "references",
    "medical_disclaimer",
}


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_text(value) -> str:
    return str(value or "").strip()


def validate_disease_rules(rules: dict) -> None:
    if not isinstance(rules, dict):
        raise ValueError("disease rules config must be a JSON object")

    for condition, rule in rules.items():
        if not isinstance(rule, dict):
            raise ValueError(f"disease rule for {condition} must be a JSON object")
        missing = [field for field in GOVERNANCE_FIELDS if field not in rule]
        if missing:
            raise ValueError(f"disease rule for {condition} missing governance fields: {', '.join(sorted(missing))}")
        if not rule.get("id") or not rule.get("label_zh"):
            raise ValueError(f"disease rule for {condition} must include id and label_zh")
        if condition != rule["id"]:
            raise ValueError(f"disease rule key {condition} must match id {rule['id']}")
        if not isinstance(rule.get("aliases"), list):
            raise ValueError(f"disease rule for {condition} must include aliases list")
        if not isinstance(rule.get("references"), list) or not rule["references"]:
            raise ValueError(f"disease rule for {condition} must include at least one reference")
        for field in ("max_sodium_per_meal", "max_carbs_per_meal", "max_protein_per_meal", "max_fat_per_meal"):
            if field in rule and (not isinstance(rule[field], (int, float)) or rule[field] <= 0):
                raise ValueError(f"disease rule for {condition} has invalid {field}")


def load_disease_rules(base_dir: str) -> dict:
    rules_path = os.environ.get(
        "DISEASE_RULES_PATH",
        os.path.join(base_dir, "config", "disease_rules.json"),
    )
    rules = _load_json(rules_path)
    validate_disease_rules(rules)
    return rules


def validate_allergen_taxonomy(taxonomy: dict) -> None:
    if not isinstance(taxonomy, dict):
        raise ValueError("allergen taxonomy config must be a JSON object")
    if not isinstance(taxonomy.get("groups"), list) or not taxonomy["groups"]:
        raise ValueError("allergen taxonomy must include groups")
    for group in taxonomy["groups"]:
        for field in ("id", "label_zh", "aliases", "keywords", "severity"):
            if field not in group:
                raise ValueError(f"allergen group missing {field}")
        if not isinstance(group["aliases"], list) or not isinstance(group["keywords"], list):
            raise ValueError(f"allergen group {group.get('id')} aliases and keywords must be lists")


def load_allergen_taxonomy(base_dir: str) -> dict:
    taxonomy_path = os.environ.get(
        "ALLERGEN_TAXONOMY_PATH",
        os.path.join(base_dir, "config", "allergen_taxonomy.json"),
    )
    taxonomy = _load_json(taxonomy_path)
    validate_allergen_taxonomy(taxonomy)
    return taxonomy


def build_condition_alias_index(rules: dict) -> dict:
    index = {}
    for condition_id, rule in rules.items():
        values = [condition_id, rule.get("label_zh"), *(rule.get("aliases") or [])]
        for value in values:
            normalized = _normalize_text(value).lower()
            if normalized:
                index[normalized] = condition_id
    return index


def build_allergen_alias_index(taxonomy: dict) -> dict:
    index = {}
    for group in taxonomy.get("groups", []):
        values = [group.get("id"), group.get("label_zh"), *(group.get("aliases") or [])]
        for value in values:
            normalized = _normalize_text(value).lower()
            if normalized:
                index[normalized] = group["id"]
    return index


def normalize_condition_ids(values: list, rules: dict) -> list[str]:
    alias_index = build_condition_alias_index(rules)
    normalized = []
    seen = set()
    for value in values or []:
        raw = _normalize_text(value)
        condition_id = alias_index.get(raw.lower(), raw)
        if condition_id and condition_id not in seen:
            normalized.append(condition_id)
            seen.add(condition_id)
    return normalized


def normalize_allergen_ids(values: list, taxonomy: dict) -> list[str]:
    alias_index = build_allergen_alias_index(taxonomy)
    normalized = []
    seen = set()
    for value in values or []:
        raw = _normalize_text(value)
        allergen_id = alias_index.get(raw.lower(), raw)
        if allergen_id and allergen_id not in seen:
            normalized.append(allergen_id)
            seen.add(allergen_id)
    return normalized


def build_disease_rules_response(rules: dict) -> dict:
    conditions = []
    review_status_counts = {}
    versions = set()

    for condition, rule in sorted(rules.items()):
        review_status = rule.get("review_status", "unknown")
        review_status_counts[review_status] = review_status_counts.get(review_status, 0) + 1
        versions.add(rule.get("rule_version", "unknown"))
        conditions.append(
            {
                "id": rule.get("id", condition),
                "condition": condition,
                "label_zh": rule.get("label_zh", condition),
                "aliases": rule.get("aliases", []),
                "category": rule.get("category"),
                "description": rule.get("description", ""),
                "screening_focus": rule.get("screening_focus", []),
                "severity_options": rule.get("severity_options", []),
                "rule_version": rule.get("rule_version"),
                "review_status": review_status,
                "last_reviewed": rule.get("last_reviewed"),
                "reviewed_by": rule.get("reviewed_by"),
                "evidence_level": rule.get("evidence_level"),
                "references": rule.get("references", []),
                "medical_disclaimer": rule.get("medical_disclaimer"),
                "limits": {
                    key: rule[key]
                    for key in (
                        "blocked_gi",
                        "blocked_labels",
                        "blocked_keywords",
                        "max_sodium_per_meal",
                        "max_carbs_per_meal",
                        "max_protein_per_meal",
                        "max_fat_per_meal",
                        "caution_sodium_per_meal",
                        "caution_carbs_per_meal",
                        "caution_protein_per_meal",
                        "caution_fat_per_meal",
                    )
                    if key in rule
                },
                "risk_nutrients": rule.get("risk_nutrients", {}),
            }
        )

    return {
        "count": len(conditions),
        "versions": sorted(versions),
        "review_status_counts": review_status_counts,
        "conditions": conditions,
        "medical_disclaimer": "疾病與營養提醒僅供健康管理與餐點篩選參考，不可取代醫師、藥師或營養師的個人化診斷與治療建議。",
    }


def build_allergen_taxonomy_response(taxonomy: dict) -> dict:
    groups = sorted(taxonomy.get("groups", []), key=lambda item: item["id"])
    return {
        "version": taxonomy.get("version"),
        "review_status": taxonomy.get("review_status"),
        "last_reviewed": taxonomy.get("last_reviewed"),
        "references": taxonomy.get("references", []),
        "medical_disclaimer": taxonomy.get("medical_disclaimer"),
        "count": len(groups),
        "groups": groups,
    }


def build_medical_metadata_response(rules: dict, taxonomy: dict) -> dict:
    disease_response = build_disease_rules_response(rules)
    return {
        "disease_rules": disease_response,
        "allergen_taxonomy": build_allergen_taxonomy_response(taxonomy),
        "medical_disclaimer": disease_response["medical_disclaimer"],
        "data_sources": [
            {"name": "TFDA Taiwan nutrition database", "role": "nutrition_grounding"},
            {"name": "Open Food Facts", "role": "optional_packaged_food_allergen_enrichment"},
            {"name": "Public health guideline references", "role": "rule_governance"},
        ],
    }
