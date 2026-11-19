"""Observe current production edge cases with isolated, non-network data."""

import base64
from contextlib import redirect_stdout
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["NUTRILENS_SKIP_LOCAL_ENV"] = "1"
os.environ["DATABASE_PATH"] = ""
os.environ["AUTH_REQUIRED"] = "false"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("MONGODB_URI", None)

from evaluate_food_images import ground
from probe_food_nutrition import save
from services.nutrition_label_service import decode_image_base64
from services.vision_food_service import normalize_confidence, normalize_weight
from services.vision_nutrition_service import find_vision_food_matches
from services.nutrition_label_service import build_custom_food_search_result
from repositories.sqlite_db import SqliteDatabase
from repositories.storage import StorageRepository


def main():
    result = {"mode": "offline_current_production_observations", "feature_code_modified": False}
    confidence_cases = [("missing", None), ("boolean_true", True), ("invalid_text", "bad"),
                        ("out_of_range", 110), ("ambiguous_fraction", 1.2)]
    result["confidence"] = []
    for label, value in confidence_cases:
        response = ground({"items": [{"name_zh": "白飯", "confidence": value, "estimated_weight_g": 100}]})
        result["confidence"].append({"case": label, "normalized": normalize_confidence(value),
                                     "accepted_items": len(response["detections"])})
    result["boolean_weight"] = normalize_weight(True)
    result["invalid_images"] = []
    for name, data in [("truncated_jpeg", b"\xff\xd8not-a-real-image"), ("truncated_png", b"\x89PNGbroken")]:
        accepted = True
        try:
            decode_image_base64(base64.b64encode(data).decode("ascii"))
        except ValueError:
            accepted = False
        result["invalid_images"].append({"case": name, "accepted_by_input_decoder": accepted})
    result["aliases"] = []
    for name in ["滷牛肉", "紅燒牛肉", "燉牛肉", "熟麵條", "熟白麵條", "糯米腸", "豬大腸", "炸臭豆腐", "泡麵"]:
        response = ground({"items": [{"name_zh": name, "confidence": 0.95, "estimated_weight_g": 100}]})
        result["aliases"].append({"name": name, "matches": [{"key": i["matched_food"]["key"],
                                  "source": i["source"], "reference_name": i["matched_food"]["name_zh"]}
                                  for i in response["detections"]]})

    with patch("requests.sessions.Session.request", side_effect=RuntimeError("Network forbidden in offline probe")):
        with redirect_stdout(io.StringIO()):
            import app
        client = app.app.test_client()
        app.storage.upsert_user({"user_id": "probe-only", "health_conditions": ["hypertension"]})
        payload = {"user_id": "probe-only", "client_record_id": "probe-partial", "source": "camera",
                   "nutrition_context": {"unresolved": [{"name": "炸臭豆腐"}], "scope": "partial"},
                   "foods": [{"name": "只知道熱量", "calories": 290, "protein": 12.2, "carbs": 22,
                              "fat": 17, "sodium": None, "fiber": None, "sugar": None,
                              "missing_nutrition_fields": ["sodium", "fiber", "sugar"],
                              "nutrition_source_url": "https://example.invalid/probe", "is_fried": False}]}
        post = client.post("/record", json=payload)
        record = post.get_json().get("record", {})
        result["memory_api_persistence"] = {"status": post.status_code, "record": record,
                                            "unresolved_context_preserved": "nutrition_context" in record}
        get = client.get("/records/probe-only")
        result["memory_api_read"] = {"status": get.status_code, "response": get.get_json()}
        with tempfile.TemporaryDirectory() as folder:
            db_path = str(Path(folder) / "probe.db")
            db = SqliteDatabase(db_path)
            repository = StorageRepository({}, [], [], sql=db)
            with patch.object(app, "storage", repository):
                sql_post = client.post("/record", json=payload)
                result["sqlite_api_persistence"] = {"status": sql_post.status_code,
                                                    "record": sql_post.get_json().get("record")}
            db.close()
            reopened = SqliteDatabase(db_path)
            repository = StorageRepository({}, [], [], sql=reopened)
            result["sqlite_after_reopen"] = repository.get_records("probe-only")
            reopened.close()

    per100 = Decimal("450") * 100 / Decimal("180")
    result["reference_arithmetic"] = {"synthetic_control": True, "source_g": 180, "source_kcal": 450,
                                     "per100g_kcal": float(per100), "consumed_g": 160,
                                     "consumed_kcal": float(per100 * Decimal(160) / 100)}
    result["official_source_sanity_counterexamples"] = [
        {"source": "handian_rice", "kJ": 1506.2, "reported_kcal": 301.2, "kcal_from_kJ": round(1506.2 / 4.184, 2),
         "carbs_g": 90, "fat_g": 0, "saturated_fat_g": 0.1, "kcal_from_4_4_9": 360,
         "requires_source_review": True},
        {"source": "changhua_noodles", "reported_weight_g": 130, "protein_carbs_fat_sum_g": 33 + 82.3 + 28.9,
         "requires_source_review": True},
    ]
    save(ROOT / "docs/food-nutrition-evaluation/2026-11-13/offline.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in {
        "memory_api_read", "sqlite_after_reopen", "memory_api_persistence", "sqlite_api_persistence"}}, ensure_ascii=False), flush=True)
    print(json.dumps({"memory_status": result["memory_api_persistence"]["status"],
                      "sql_status": result["sqlite_api_persistence"]["status"],
                      "saved_sodium": result["memory_api_persistence"]["record"].get("total_sodium"),
                      "context_preserved": result["memory_api_persistence"]["unresolved_context_preserved"]}), flush=True)


if __name__ == "__main__":
    main()
