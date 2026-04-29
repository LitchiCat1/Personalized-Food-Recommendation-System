import json
import os


def load_disease_rules(base_dir: str) -> dict:
    rules_path = os.environ.get(
        "DISEASE_RULES_PATH",
        os.path.join(base_dir, "config", "disease_rules.json"),
    )
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    if not isinstance(rules, dict):
        raise ValueError("disease rules config must be a JSON object")
    return rules
