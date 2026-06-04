import json

import requests

from services.nutrition_label_service import extract_json_block, get_gemini_api_keys, get_gemini_models


RETRYABLE_GEMINI_STATUS_CODES = {401, 403, 404, 429, 500, 502, 503, 504}


def normalize_restaurant_summary(parsed: dict, budget: int) -> dict:
    price = parsed.get("price_range_twd") or {}
    try:
        min_price = int(price.get("min") or 0)
    except (TypeError, ValueError):
        min_price = 0
    try:
        max_price = int(price.get("max") or 0)
    except (TypeError, ValueError):
        max_price = 0

    confidence = parsed.get("confidence") if parsed.get("confidence") in {"low", "medium", "high"} else "low"
    budget_fit = parsed.get("budget_fit") if parsed.get("budget_fit") in {"適合", "可能超出", "不確定"} else "不確定"
    likely_foods = [str(item).strip() for item in (parsed.get("likely_foods") or []) if str(item).strip()]
    health_tips = [str(item).strip() for item in (parsed.get("health_tips") or []) if str(item).strip()]

    if max_price and max_price <= budget:
        budget_fit = "適合"
    elif min_price and min_price > budget:
        budget_fit = "可能超出"

    return {
        "restaurant_type": str(parsed.get("restaurant_type") or "餐廳").strip()[:30],
        "likely_foods": likely_foods[:6],
        "price_range_twd": {"min": min_price, "max": max_price},
        "budget_fit": budget_fit,
        "health_tips": health_tips[:4],
        "confidence": confidence,
        "source_note": "Google Places + Gemini 推測，非店家正式菜單；實際品項與價格請以店家現場為準。",
    }


def call_gemini_restaurant_summary(restaurant: dict, budget: int, category: str, health_conditions: list[str], api_key: str, model: str) -> dict:
    prompt = (
        "你是台灣飲食推薦 App 的店家摘要器。根據 Google Places 店家資料推測可能販售食物、價格區間與健康點餐建議。"
        "不得假裝知道正式菜單；不可輸出精準營養數字。只回傳合法 JSON，不要 markdown。"
        "固定 JSON schema: "
        '{"restaurant_type":"","likely_foods":[""],"price_range_twd":{"min":0,"max":0},'
        '"budget_fit":"適合|可能超出|不確定","health_tips":[""],"confidence":"low|medium|high"}'
        f"\n使用者預算: {budget} TWD"
        f"\n搜尋類型: {category or 'all'}"
        f"\n健康條件: {', '.join(health_conditions or []) or '無'}"
        f"\nGoogle Places 店家資料: {json.dumps(restaurant, ensure_ascii=False)[:1800]}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    resp = requests.post("" + url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return extract_json_block(text)


def build_restaurant_ai_summary(restaurant: dict, budget: int, category: str, health_conditions: list[str]) -> dict:
    api_keys = get_gemini_api_keys()
    if not api_keys:
        raise ValueError("缺少 Gemini API key，請設定 GEMINI_API_KEYS 或 GEMINI_API_KEY")

    models = get_gemini_models()
    total_attempts = len(api_keys) * len(models)
    attempt = 0
    last_error: requests.HTTPError | None = None

    for key_index, api_key in enumerate(api_keys):
        for model in models:
            attempt += 1
            try:
                parsed = call_gemini_restaurant_summary(restaurant, budget, category, health_conditions, api_key, model)
                return normalize_restaurant_summary(parsed, budget)
            except requests.HTTPError as e:
                last_error = e
                status_code = e.response.status_code if e.response is not None else None
                if status_code not in RETRYABLE_GEMINI_STATUS_CODES or attempt == total_attempts:
                    raise
                print(f"[WARN] Gemini restaurant key #{key_index + 1} model {model} failed with HTTP {status_code}; trying next option")

    if last_error:
        raise last_error
    raise ValueError("Gemini 店家摘要失敗")
