"""Offline official nutrition data, also usable by the photo evaluation script."""

import json
from pathlib import Path


def load_usda_foods(base_dir):
    path = Path(base_dir) / "nutrition_db_usda.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
