"""Bounded, opt-in live experiments; never imports the application database.

Uses the configured relay and production payload/parser/grounding functions.
No retries or key rotation: one job is one HTTP request. Results are evidence,
not calibrated accuracy. Generated reports contain no credentials or photos.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import statistics
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from services.ai_relay_service import get_relay_config
from services.nutrition_label_service import decode_image_base64, extract_json_block
from services.openai_service import openai_chat_payload, openai_headers, openai_response_text
from services.vision_food_service import build_food_recognition_prompt, normalize_vision_result
from evaluate_food_images import ground


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def call(prompt, image=None, overrides=None, timeout=60):
    config = get_relay_config()
    if config is None:
        raise ValueError("No relay configured")
    payload = openai_chat_payload(config.model, prompt, 4096,
                                  base64.b64encode(image).decode("ascii") if image else None,
                                  "image/jpeg" if image else None)
    payload.update(overrides or {})
    started = time.monotonic()
    result = {"requested_model": config.model, "prompt_sha256": digest(prompt.encode("utf-8")),
              "retry_count": 0}
    try:
        response = requests.post(config.chat_url, headers=openai_headers(config.keys[0]),
                                 json=payload, timeout=(8, timeout), allow_redirects=False)
        result["http_status"] = response.status_code
        if response.status_code == 200:
            body = response.json()
            text, finish = openai_response_text(body)
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            result.update(text=text, finish_reason=finish, returned_model=body.get("model"),
                          usage=body.get("usage"), annotations=message.get("annotations"),
                          tool_calls=message.get("tool_calls"),
                          grounding_metadata=body.get("groundingMetadata") or message.get("groundingMetadata"),
                          response_keys=sorted(body.keys()))
            try:
                result["json"] = json.loads(text)
            except (ValueError, TypeError):
                result["json_error"] = True
        else:
            result["error"] = "upstream_http_error"
            try:
                err = response.json().get("error", {})
                result["error_code"] = str(err.get("code") or err.get("type") or "")[:120]
            except (ValueError, AttributeError):
                pass
    except requests.RequestException as exc:
        result["error"] = type(exc).__name__
    except (ValueError, TypeError, AttributeError) as exc:
        result["error"] = type(exc).__name__
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def vision_job(path, repeat, variant="original"):
    content = path.read_bytes()
    if variant != "original":
        from PIL import Image, ImageOps
        picture = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
        if variant == "max640_q70":
            picture.thumbnail((640, 640))
        buffer = io.BytesIO()
        picture.save(buffer, format="JPEG", quality=70)
        content = buffer.getvalue()
    encoded = base64.b64encode(content).decode("ascii")
    decode_image_base64(encoded)
    result = {"filename": path.name, "repeat": repeat, "variant": variant,
              "image_sha256": digest(content), "image_bytes": len(content)}
    result.update(call(build_food_recognition_prompt(), image=content))
    if result.get("text") and result.get("finish_reason") not in {"length", "max_tokens"}:
        try:
            parsed = normalize_vision_result(extract_json_block(result["text"]))
            result["parsed"] = parsed
            result["response"] = ground(parsed)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            result["pipeline_error"] = type(exc).__name__
    return result


def vision(args):
    paths = sorted((ROOT / "food_picture").glob("*.jpg"))
    if args.names:
        paths = [p for p in paths if p.name in args.names]
    jobs = [(p, n, args.variant) for n in range(1, args.repeats + 1) for p in paths]
    if not jobs or len(jobs) > 45:
        raise ValueError("Expected between 1 and 45 image calls")
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
              "mode": "live_same_production_payload_no_retries", "workers": args.workers,
              "max_http_requests": len(jobs), "ground_truth": "not_available",
              "database_sha256": {n: digest((ROOT / "backend" / n).read_bytes().replace(b"\r\n", b"\n"))
                                  for n in ("nutrition_db_tw.json", "nutrition_db_usda.json")}, "results": []}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(vision_job, *job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            report["results"].append(result)
            save(args.output, report)
            text = {k: result.get(k) for k in ("filename", "repeat", "variant", "elapsed_seconds", "http_status", "error")}
            text["items"] = [i["name_zh"] for i in result.get("parsed", {}).get("items", [])]
            text["summary"] = result.get("response", {}).get("summary")
            print(json.dumps(text, ensure_ascii=False), flush=True)
    latencies = [r["elapsed_seconds"] for r in report["results"]]
    report["latency_p50_seconds"] = statistics.median(latencies)
    report["latency_max_seconds"] = max(latencies)
    save(args.output, report)


def capabilities(args):
    prompt = ("請實際搜尋並讀取 https://www.gqfood.com.tw/product_d.php?id=256&lang=tw&tb=1 的食品名稱、"
              "食用前處理方式與營養標示。沒有實際網頁內容不得依記憶補數字。"
              "只回JSON，格式為 {\"status\":\"found或no_evidence\",\"food_name\":null,"
              "\"preparation\":null,\"serving_g\":null,\"calories\":null,\"source_url\":null,\"evidence\":null}。")
    schema = {"type": "object", "properties": {"probe_marker": {"type": "string", "enum": ["SCHEMA_20261113"]}},
              "required": ["probe_marker"], "additionalProperties": False}
    cases = [
        ("current_payload_search_request", prompt, {}),
        ("web_search_options", prompt, {"web_search_options": {"search_context_size": "low"}}),
        ("strict_schema_adherence_control", 'Return JSON {"different_key":123}.',
         {"response_format": {"type": "json_schema", "json_schema": {"name": "probe", "strict": True, "schema": schema}}}),
        ("function_tool_required_control", "Call capability_probe exactly once; do not invent results. Return JSON.",
         {"tools": [{"type": "function", "function": {"name": "capability_probe", "description": "Capability test only",
                     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}],
          "tool_choice": {"type": "function", "function": {"name": "capability_probe"}}}),
    ]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "results": []}
    for name, prompt, overrides in cases:
        result = call(prompt, overrides=overrides, timeout=35)
        result["case"] = name
        report["results"].append(result)
        save(args.output, report)
        print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["vision", "capabilities"])
    parser.add_argument("--live", action="store_true", help="Explicitly authorize bounded real relay usage")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--names", nargs="*")
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 4))
    parser.add_argument("--workers", type=int, default=2, choices=[1, 2])
    parser.add_argument("--variant", default="original", choices=["original", "q70", "max640_q70"])
    args = parser.parse_args()
    if not args.live:
        parser.error("Live calls require --live; there is no implicit paid execution")
    {"vision": vision, "capabilities": capabilities}[args.mode](args)


if __name__ == "__main__":
    main()
