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


def validate_disease_rules(rules: dict) -> None:
    if not isinstance(rules, dict):
        raise ValueError("disease rules config must be a JSON object")

    for condition, rule in rules.items():
        if not isinstance(rule, dict):
            raise ValueError(f"disease rule for {condition} must be a JSON object")
        missing = [field for field in GOVERNANCE_FIELDS if field not in rule]
        if missing:
            raise ValueError(f"disease rule for {condition} missing governance fields: {', '.join(sorted(missing))}")
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
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    validate_disease_rules(rules)
    return rules


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
                "condition": condition,
                "description": rule.get("description", ""),
                "rule_version": rule.get("rule_version"),
                "review_status": review_status,
                "last_reviewed": rule.get("last_reviewed"),
                "reviewed_by": rule.get("reviewed_by"),
                "evidence_level": rule.get("evidence_level"),
                "references": rule.get("references", []),
                "medical_disclaimer": rule.get("medical_disclaimer"),
                "limits": {
                    key: rule[key]
                    for key in ("blocked_gi", "blocked_labels", "max_sodium_per_meal", "max_carbs_per_meal", "max_protein_per_meal", "max_fat_per_meal")
                    if key in rule
                },
            }
        )

    return {
        "count": len(conditions),
        "versions": sorted(versions),
        "review_status_counts": review_status_counts,
        "conditions": conditions,
        "medical_disclaimer": "系統提供的疾病與營養提醒僅供健康管理參考，不可取代醫師、營養師或其他醫療專業人員建議。",
    }
