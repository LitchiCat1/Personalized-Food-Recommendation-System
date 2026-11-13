"""Evaluate real photos through the production vision and nutrition pipeline.

No filename or expected label is sent to the model. --replay performs database
grounding on saved model output without another paid API call.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.nutrition_label_service import build_custom_food_search_result, get_gemini_api_keys
from services.disease_rule_service import load_allergen_taxonomy, load_disease_rules
from services.nutrition_database_service import load_usda_foods
from services.vision_food_service import build_vision_food_response, call_gemini_food_recognition_with_rotation
from services.vision_food_service import build_food_recognition_prompt, normalize_vision_result
from services.ai_relay_service import relay_chat
from services.nutrition_label_service import extract_json_block


class EmptyStorage:
    def get_custom_foods(self, _user_id):
        return []

    def get_user(self, _user_id):
        return None


def ground(parsed):
    database = json.loads((ROOT / "backend/nutrition_db_tw.json").read_text(encoding="utf-8"))
    database.update(load_usda_foods(ROOT / "backend"))
    rules = load_disease_rules(str(ROOT / "backend"))
    taxonomy = load_allergen_taxonomy(str(ROOT / "backend"))
    return build_vision_food_response(parsed, EmptyStorage(), database, rules, taxonomy, [], [], None, build_custom_food_search_result)


def evaluate(path, audit=False):
    started = time.monotonic()
    content = path.read_bytes()
    result = {"filename": path.name, "sha256": hashlib.sha256(content).hexdigest()}
    try:
        parsed = call_gemini_food_recognition_with_rotation(
            base64.b64encode(content).decode("ascii"), "image/jpeg", get_gemini_api_keys(),
        )
        result["parsed"] = parsed
        if audit and len(parsed.get("items", [])) >= 3:
            result["first_pass"] = parsed
            prompt = (build_food_recognition_prompt() +
                      "\n以下是第一次辨識，可能有漏項或誤認。請獨立重看原圖每格、主菜下方與配菜邊緣，"
                      "只在有可見證據時補漏或修正，不要為了增加數量而新增。綠色豆仁、橘色塊等小配料也要檢查。"
                      "不確定種類仍保留保守名稱，不可受第一次名稱引導硬猜。回傳完整修正後 JSON，不要重複食品。"
                      "第一次結果：" + json.dumps(parsed, ensure_ascii=False))
            text, finish = relay_chat(prompt, image_base64=base64.b64encode(content).decode("ascii"), image_mime_type="image/jpeg")
            if finish == "length":
                raise ValueError("Audit truncated")
            parsed = normalize_vision_result(extract_json_block(text))
            result["parsed"] = parsed
        result["response"] = ground(parsed)
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "http_status": getattr(getattr(exc, "response", None), "status_code", None)}
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--names", nargs="*")
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--coverage-audit", action="store_true", help="Experimental extra vision call on multi-item meals")
    args = parser.parse_args()
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_replay" if args.replay else "live_vision",
        "replay_source": args.replay.name if args.replay else None,
        "coverage_audit": args.coverage_audit,
        "database_hash_normalization": "UTF-8 with LF line endings",
        "database_sha256": {name: hashlib.sha256((ROOT / "backend" / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                            for name in ("nutrition_db_tw.json", "nutrition_db_usda.json")},
        "results": [],
    }
    if not args.replay:
        report["prompt_sha256"] = hashlib.sha256(build_food_recognition_prompt().encode("utf-8")).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save(result):
        report["results"].append(result)
        report["results"].sort(key=lambda row: row["filename"])
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        response = result.get("response", {})
        print(json.dumps({
            "filename": result["filename"], "seconds": result.get("elapsed_seconds"),
            "model_items": [item.get("name_zh") for item in result.get("parsed", {}).get("items", [])],
            "accepted": [item["name_zh"] for item in response.get("detections", [])],
            "rejected": [item["label"] for item in response.get("rejected_detections", [])],
            "summary": response.get("summary"), "error": result.get("error"),
        }, ensure_ascii=False), flush=True)

    if args.replay:
        for previous in json.loads(args.replay.read_text(encoding="utf-8"))["results"]:
            if "parsed" in previous:
                save({"filename": previous["filename"], "sha256": previous["sha256"],
                      "parsed": previous["parsed"], "response": ground(previous["parsed"])})
    else:
        photos = sorted((ROOT / "food_picture").glob("*.jpg"))
        if args.names:
            photos = [path for path in photos if path.name in args.names]
        if not photos:
            parser.error("No matching photos")
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for future in as_completed([executor.submit(evaluate, path, args.coverage_audit) for path in photos]):
                save(future.result())


if __name__ == "__main__":
    main()
