"""Seven opt-in Tavily requests comparing documented retrieval controls."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import time

import requests

from probe_tavily_nutrition import OUT, PRIVATE, ROOT, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Skip cases already saved in the same report")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live for three basic searches and four single-URL extracts")
    keys = re.findall(r"tvly-[A-Za-z0-9_-]+", (ROOT / "TavilyKey.txt").read_text(encoding="utf-8-sig"))
    if len(keys) != 1:
        raise ValueError("Expected exactly one private Tavily key")
    headers = {"Authorization": "Bearer " + keys[0], "Content-Type": "application/json"}
    url = "https://www.green-n-safe.com/Products/Content?id=MEG0028ABCS"
    searches = [
        ("rice_taiwan", {"query": "糯米腸 營養", "country": "taiwan"}),
        ("exact_soup", {"query": '"香菇赤肉羹" 營養', "exact_match": True,
                        "include_domains": ["green-n-safe.com"], "include_domains_mode": "restrict"}),
        ("exact_fake", {"query": '"不存在品牌_測試XQ_20261113藍光地瓜球" 營養標示', "exact_match": True}),
    ]
    extracts = [
        ("basic_text_control", {"extract_depth": "basic", "format": "text"}),
        ("basic_markdown", {"extract_depth": "basic"}),
        ("advanced_markdown", {"extract_depth": "advanced"}),
        ("advanced_targeted", {"extract_depth": "advanced", "chunks_per_source": 5,
                               "query": "香菇赤肉羹 營養標示 每一份量 本包裝含 每份 每100公克 熱量 蛋白質 脂肪 碳水化合物 鈉"}),
    ]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "max_requests": 7,
              "mode": "documented_settings_small_comparison_not_accuracy_benchmark", "requests": []}
    if args.resume:
        report = json.loads((OUT / "tavily-settings.json").read_text(encoding="utf-8"))
        report["max_requests"] = 7
    jobs = [("search", case, {"search_depth": "basic", "auto_parameters": False, "topic": "general",
                              "include_answer": False, "include_raw_content": False, "include_images": False,
                              "include_usage": True, "max_results": 5, **settings}) for case, settings in searches]
    jobs.extend(("extract", case, {"urls": [url], "format": "markdown", "include_usage": True,
                                   "include_images": False, "timeout": 20, **settings}) for case, settings in extracts)
    for endpoint, case, payload in jobs:
        if args.resume and any(item["case"] == case for item in report["requests"]):
            continue
        started = time.monotonic()
        row = {"endpoint": endpoint, "case": case, "parameters": payload}
        try:
            response = requests.post("https://api.tavily.com/" + endpoint, headers=headers, json=payload,
                                     timeout=(8, 35), allow_redirects=False)
            row["http_status"] = response.status_code
            if response.status_code == 200:
                body = response.json()
                save(PRIVATE / ("settings-" + case + ".json"), body)
                row.update(request_id=body.get("request_id"), usage=body.get("usage"))
                if endpoint == "search":
                    row["results"] = [{"url": item.get("url"), "title": item.get("title"),
                                       "score": item.get("score")} for item in body.get("results", [])]
                else:
                    row["results"] = []
                    for item in body.get("results", []):
                        content = item.get("raw_content") or ""
                        row["results"].append({"url": item.get("url"), "characters": len(content),
                                               "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                               "numeric_markers": {n: n in content for n in ("94.6", "283.8", "1506", "502", "300")},
                                               "label_markers": {s: s in content for s in ("香菇赤肉羹", "營養標示", "每100", "蛋白質", "鈉")}})
                    row["failed_results"] = body.get("failed_results", [])
            else:
                row["error"] = "upstream_http_error"
        except (requests.RequestException, ValueError) as exc:
            row["error"] = type(exc).__name__
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["requests"].append(row)
        report["reported_credits"] = sum((item.get("usage") or {}).get("credits", 0) for item in report["requests"])
        save(OUT / "tavily-settings.json", report)
        print(json.dumps(row, ensure_ascii=True), flush=True)
        if row.get("http_status") in {401, 403, 429, 432, 433}:
            break


if __name__ == "__main__":
    main()
