"""Summarize saved evidence without making network requests."""

from collections import Counter
import itertools
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from services.vision_nutrition_service import food_identity
from services.nutrition_label_service import extract_json_block

OUT = ROOT / "docs/food-nutrition-evaluation/2026-11-13"


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def vision(name):
    report = read(name)
    rows = report["results"]
    seconds = [r["elapsed_seconds"] for r in rows]
    grouped = {}
    for row in rows:
        grouped.setdefault(row["filename"], []).append(row)
    photos = []
    for filename, repeats in grouped.items():
        repeats.sort(key=lambda r: r["repeat"])
        exact = [Counter(i["name_zh"] for i in r.get("parsed", {}).get("items", [])) for r in repeats]
        canonical = [Counter(food_identity(i["name_zh"]) for i in r.get("parsed", {}).get("items", [])) for r in repeats]
        photos.append({"filename": filename, "item_counts": [sum(s.values()) for s in exact],
                       "exact_name_multiset_stable": all(s == exact[0] for s in exact),
                       "current_identity_multiset_stable": all(s == canonical[0] for s in canonical),
                       "weight_totals_g": [sum(i.get("estimated_weight_g") or 0 for i in r.get("parsed", {}).get("items", [])) for r in repeats],
                       "matched_calories": [r.get("response", {}).get("summary", {}).get("total_calories") for r in repeats],
                       "matched_items": [len(r.get("response", {}).get("detections", [])) for r in repeats]})
    items = [i for r in rows for i in r.get("parsed", {}).get("items", [])]
    matched = sum(len(r.get("response", {}).get("detections", [])) for r in rows)
    rejected = [i for r in rows for i in r.get("response", {}).get("rejected_detections", [])]
    return {"calls": len(rows), "successful_grounding_responses": sum("response" in r for r in rows),
            "recognized_items": len(items), "matched_items": matched, "excluded_items": len(rejected),
            "excluded_by_nutrition_status": dict(Counter(i.get("nutrition_status", "not_evaluated") for i in rejected)),
            "excluded_by_reason": dict(Counter(i.get("reason", "unspecified") for i in rejected)),
            "matching_coverage": matched / len(items),
            "name_confidence_below_045": sum(isinstance(i.get("confidence"), (float, int)) and i["confidence"] < .45 for i in items),
            "weight_confidence_below_075": sum(isinstance(i.get("weight_confidence"), (float, int)) and i["weight_confidence"] < .75 for i in items),
            "needs_confirmation_count": sum(i.get("needs_confirmation", False) for r in rows for i in r.get("response", {}).get("detections", [])),
            "p50_seconds": statistics.median(seconds), "p95_nearest_rank_seconds": percentile(seconds, .95),
            "max_seconds": max(seconds), "photos": photos}


def main():
    result = {"vision_original": vision("vision-original.json"), "vision_q70": vision("vision-q70.json")}
    result["relay_extractions"] = []
    for name in ["extraction.json", "extraction-json_object-direct.json", "extraction-json_object-tavily.json"]:
        report = read(name)
        rows = report["results"]
        expected_count = len(report["cases"]) * max(r["repeat"] for r in rows)
        result["relay_extractions"].append({"file": name, "calls": len(rows), "expected_items": expected_count,
            "returned_items": sum(len(r.get("json", {}).get("items", [])) for r in rows),
            "latencies_seconds": [r["elapsed_seconds"] for r in rows],
            "http_200": sum(r.get("http_status") == 200 for r in rows),
            "statuses": [{"repeat": r["repeat"], "batch": r["batch"],
                          "items": [{"id": i.get("item_id"), "status": i.get("status"),
                                     "sodium": i.get("nutrients", {}).get("sodium"),
                                     "fiber": i.get("nutrients", {}).get("fiber"),
                                     "source_id": i.get("source_id")} for i in r.get("json", {}).get("items", [])]}
                         for r in rows]})
    tavily = [read(n) for n in ["tavily.json", "tavily-followup.json"]]
    result["tavily"] = {"search_requests": sum(len(d["searches"]) for d in tavily), "extract_requests": 2,
                        "reported_credits": sum(d["reported_credits"] for d in tavily),
                        "search_latencies_seconds": [s["elapsed_seconds"] for d in tavily for s in d["searches"]],
                        "extract_latencies_seconds": [d["extract"]["elapsed_seconds"] for d in tavily]}
    if (OUT / "tavily-settings.json").exists():
        settings = read("tavily-settings.json")
        result["tavily_settings"] = {
            "search_requests": sum(row["endpoint"] == "search" for row in settings["requests"]),
            "extract_requests": sum(row["endpoint"] == "extract" for row in settings["requests"]),
            "http_200": sum(row.get("http_status") == 200 for row in settings["requests"]),
            "reported_credits": settings["reported_credits"],
            "cases": [{"case": row["case"], "seconds": row["elapsed_seconds"], "results": row.get("results", [])}
                      for row in settings["requests"]],
        }
        result["tavily_all_calls"] = {
            "search_requests": result["tavily"]["search_requests"] + result["tavily_settings"]["search_requests"],
            "extract_requests": result["tavily"]["extract_requests"] + result["tavily_settings"]["extract_requests"],
            "reported_credits": result["tavily"]["reported_credits"] + settings["reported_credits"],
        }
    if (OUT / "positive-pipeline.json").exists():
        positive = read("positive-pipeline.json")["results"]
        result["positive_pipeline"] = {"calls": len(positive),
                                       "historical_raw_harness_checks_passed": sum(c["passed"] for r in positive for c in r["checks"]),
                                       "historical_raw_harness_checks": sum(len(r["checks"]) for r in positive),
                                       "historical_harness_limitation": "Absent items incorrectly passed three expected-null checks. Preserve raw evidence; use corrected offline replay below.",
                                       "latencies_seconds": [r["elapsed_seconds"] for r in positive]}
        expected = {
            "hospital_reference": {"calories": 477.3, "protein": 0.6, "fat": 26.9, "carbs": 58.2,
                                   "fiber": 1.4, "sodium": 26, "sugar": 11.5, "saturated_fat": None, "trans_fat": None},
            "exact_soup": {"calories": 94.6, "protein": 9.5, "fat": 2.2, "carbs": 9.2,
                           "fiber": None, "sodium": 502, "sugar": 1.2, "saturated_fat": 0.7, "trans_fat": 0},
        }
        replay = []
        for row in positive:
            parsed = extract_json_block(row.get("text", ""))
            items = parsed.get("items", [])
            checks = [len(items) == 3 and {i.get("item_id") for i in items} == {"hospital_reference", "exact_soup", "fake_identity"}]
            for item_id, nutrients in expected.items():
                item = next((i for i in items if i.get("item_id") == item_id), {})
                basis = item.get("basis_weight_g")
                valid = bool(item) and item.get("status") == "candidate" and type(basis) in {int, float} and basis > 0
                for field, value in nutrients.items():
                    observed = item.get("nutrients", {}).get(field)
                    checks.append(valid and (observed is None if value is None else (
                        isinstance(observed, dict) and type(observed.get("value")) in {int, float}
                        and math.isclose(observed["value"] * 100 / basis, value, abs_tol=.01))))
            fake = next((i for i in items if i.get("item_id") == "fake_identity"), {})
            checks.append(fake.get("status") in {"no_evidence", "incompatible"}
                          and set(fake.get("nutrients", {})) == set(expected["exact_soup"])
                          and all(v is None for v in fake["nutrients"].values()))
            replay.append({"repeat": row["repeat"], "raw_json_parseable": "json" in row,
                           "production_parser_parseable": True, "checks_passed": sum(checks), "checks": len(checks)})
        result["positive_pipeline"]["offline_production_parser_replay"] = replay
        result["positive_pipeline"]["corrected_raw_parser_checks_passed"] = sum(
            row["checks_passed"] if row["raw_json_parseable"] else 0 for row in replay)
        result["positive_pipeline"]["corrected_production_parser_checks_passed"] = sum(row["checks_passed"] for row in replay)
        result["positive_pipeline"]["corrected_checks"] = sum(row["checks"] for row in replay)
    logs = [read(n)["results"] for n in ["vision-original.json", "vision-q70.json", "capabilities.json", "extraction.json",
                                        "extraction-json_object-direct.json", "extraction-json_object-tavily.json", "positive-pipeline.json"]]
    logs.append(read("nullable-schema.json"))
    calls = [r for batch in logs for r in batch]
    result["all_relay_calls"] = {"attempted": len(calls), "http_200": sum(r.get("http_status") == 200 for r in calls),
                                  "errors": [r.get("error") for r in calls if r.get("error")],
                                  "reported_usage_totals": {k: sum((r.get("usage") or {}).get(k, 0) for r in calls)
                                                            for k in ["prompt_tokens", "completion_tokens", "total_tokens"]},
                                  "returned_models": sorted({r["returned_model"] for r in calls if r.get("returned_model")})}
    (OUT / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = dict(result)
    compact["relay_extractions"] = [{k: v for k, v in r.items() if k != "statuses"} for r in result["relay_extractions"]]
    print(json.dumps(compact, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
