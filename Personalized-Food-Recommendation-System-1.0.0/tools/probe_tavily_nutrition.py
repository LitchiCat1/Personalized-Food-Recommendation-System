"""Bounded Tavily feasibility experiment. No application routes are changed."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import requests

from probe_food_nutrition import ROOT, save


OUT = ROOT / "docs/food-nutrition-evaluation/2026-11-13"
PRIVATE = ROOT / ".planning/web-nutrition-fallback/tavily"
QUERIES = [
    ("hollow_balls", "炸地瓜球 空心 熟食 營養標示 每100公克 熱量 蛋白質 鈉", []),
    ("rice_sausage", "糯米腸 烤 營養標示 每100公克 熱量 蛋白質 鈉", []),
    ("fried_tofu", "炸臭豆腐 熟重 每100公克 營養 鈉", []),
    ("exact_brand_soup", "香菇赤肉羹 營養標示 每100公克", ["green-n-safe.com"]),
    ("government_soup", "肉羹 總重量 330 營養", ["obesity.chshb.gov.tw"]),
    ("nonexistent_food", '"不存在品牌_測試XQ_20261113藍光地瓜球" 營養標示', []),
]
EXTRACT_URLS = [
    "https://www.green-n-safe.com/Products/Content?id=MEG0028ABCS",
    "https://handian.co.uk/zh-tw/products/catering-products/sticky-rice-roll/",
    "https://obesity.chshb.gov.tw/snack_content01.aspx?mno=37&sno=96",
    "https://www.gqfood.com.tw/product_d.php?id=256&lang=tw&tb=1",
    "https://obesity.chshb.gov.tw/snack_content01.aspx?mno=26&sno=39",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--followup", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live for six basic searches and one five-URL extract")
    candidates = re.findall(r"tvly-[A-Za-z0-9_-]+", (ROOT / "TavilyKey.txt").read_text(encoding="utf-8-sig"))
    if len(candidates) != 1:
        raise ValueError("Expected one Tavily API key in the private local file")
    key = candidates[0]
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    PRIVATE.mkdir(parents=True, exist_ok=True)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "max_requests": 3 if args.followup else 7,
              "searches": [], "extract": None, "key_logged": False}
    suffix = "-followup" if args.followup else ""
    queries = QUERIES if not args.followup else [
        ("rice_short_query", "糯米腸 營養", []),
        ("hospital_balls", "地瓜球 營養", ["tahsda.org.tw"]),
    ]
    urls = EXTRACT_URLS if not args.followup else [
        "https://www.tahsda.org.tw/communitymedicine/files/20161126_RAOHEStreetMarketNight/QQ%E7%8E%8B%E5%AD%90%E5%9C%B0%E7%93%9C%E7%90%83.pdf",
        "https://www.green-n-safe.com/__nutrilens_probe_missing_20261113__",
    ]

    def request(endpoint, payload):
        started = time.monotonic()
        row = {}
        body = {}
        try:
            response = requests.post("https://api.tavily.com/" + endpoint, json=payload,
                                     headers=headers, timeout=(8, 30), allow_redirects=False)
            row["http_status"] = response.status_code
            if response.status_code == 200:
                body = response.json()
                row.update(request_id=body.get("request_id"), response_time=body.get("response_time"),
                           usage=body.get("usage"), answer_returned=body.get("answer") is not None)
            else:
                row["error"] = "upstream_http_error"
        except (requests.RequestException, ValueError) as exc:
            row["error"] = type(exc).__name__
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return row, body

    for query_id, query, domains in queries:
        payload = {"query": query, "search_depth": "basic", "max_results": 5,
                   "include_answer": False, "include_raw_content": False, "include_usage": True,
                   "auto_parameters": False, "include_images": False}
        if domains:
            payload["include_domains"] = domains
        row, body = request("search", payload)
        row.update(query_id=query_id, query=query, include_domains=domains)
        row["results"] = [{"title": r.get("title"), "url": r.get("url"), "score": r.get("score")}
                          for r in body.get("results", [])]
        save(PRIVATE / f"search-{query_id}.json", body)
        report["searches"].append(row)
        save(OUT / f"tavily{suffix}.json", report)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if row.get("http_status") in {401, 403, 429, 432, 433}:
            break

    if any(r.get("http_status") == 200 for r in report["searches"]):
        row, body = request("extract", {"urls": urls, "extract_depth": "basic", "format": "text",
                                       "include_usage": True, "include_images": False, "timeout": 20})
        row["results"] = []
        for index, result in enumerate(body.get("results", [])):
            content = result.get("raw_content") or ""
            source_id = "tavily" + suffix + "_" + str(index)
            (PRIVATE / f"{source_id}.txt").write_text(content, encoding="utf-8")
            row["results"].append({"source_id": source_id, "url": result.get("url"), "characters": len(content),
                                   "text_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                   "contains_nutrition_heading": bool(re.search(r"營養|Nutrition", content, re.I))})
        row["failed_results"] = body.get("failed_results", [])
        report["extract"] = row
        save(PRIVATE / f"extract{suffix}.json", body)
        save(OUT / f"tavily{suffix}.json", report)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    credits = [row.get("usage", {}).get("credits", 0) for row in report["searches"] if row.get("usage")]
    if report.get("extract") and report["extract"].get("usage"):
        credits.append(report["extract"]["usage"].get("credits", 0))
    report["reported_credits"] = sum(credits)
    save(OUT / f"tavily{suffix}.json", report)


if __name__ == "__main__":
    main()
