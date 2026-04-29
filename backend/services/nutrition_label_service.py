import json
import os
import re

import requests


def extract_number(value, as_int: bool = False):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if as_int else float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    number = float(match.group(0))
    return int(round(number)) if as_int else number


def round_nutrient(value, digits: int = 1):
    if value is None:
        return None
    return round(float(value), digits)


def normalize_nutrition_payload(nutrition: dict) -> dict:
    return {
        "calories": round_nutrient(nutrition.get("calories"), 0),
        "protein": round_nutrient(nutrition.get("protein"), 1),
        "fat": round_nutrient(nutrition.get("fat"), 1),
        "carbs": round_nutrient(nutrition.get("carbs"), 1),
        "sodium": round_nutrient(nutrition.get("sodium"), 0),
        "fiber": round_nutrient(nutrition.get("fiber"), 1),
        "sugar": round_nutrient(nutrition.get("sugar"), 1),
        "saturated_fat": round_nutrient(nutrition.get("saturated_fat"), 1),
        "trans_fat": round_nutrient(nutrition.get("trans_fat"), 1),
    }


def scale_nutrition_per_100g(nutrition_per_serving: dict, serving_size_g: float | None):
    if not serving_size_g or serving_size_g <= 0:
        return None
    scale = 100.0 / serving_size_g
    return normalize_nutrition_payload(
        {key: (value * scale if value is not None else None) for key, value in nutrition_per_serving.items()}
    )


def build_custom_food_search_result(food_doc: dict) -> dict:
    base_nutrition = food_doc.get("nutrition_per_100g") or food_doc.get("nutrition_per_serving") or {}
    return {
        "key": food_doc["food_id"],
        "food_id": food_doc["food_id"],
        "name_zh": food_doc.get("name_zh", food_doc["food_id"]),
        "name_en": food_doc.get("name_en", ""),
        "category": food_doc.get("category", "自訂食品"),
        "calories": base_nutrition.get("calories", 0),
        "protein": base_nutrition.get("protein", 0),
        "fat": base_nutrition.get("fat", 0),
        "carbs": base_nutrition.get("carbs", 0),
        "sodium": base_nutrition.get("sodium", 0),
        "fiber": base_nutrition.get("fiber", 0),
        "unit": food_doc.get("unit", "per serving"),
        "source": food_doc.get("source", "custom-food"),
        "serving_size_g": food_doc.get("serving_size_g"),
    }


def extract_json_block(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def detect_image_mime(img_bytes: bytes) -> str:
    if img_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if img_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if img_bytes.startswith(b"GIF8"):
        return "image/gif"
    if img_bytes.startswith(b"RIFF") and b"WEBP" in img_bytes[:16]:
        return "image/webp"
    return "image/jpeg"


def call_gemini_nutrition_ocr(image_b64: str, mime_type: str, api_key: str) -> dict:
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    prompt = (
        "請辨識這張食品營養標示圖片，盡量依台灣常見營養標示格式擷取資訊。"
        "只回傳合法 JSON，不要加 markdown、不要加解釋。"
        "JSON schema: "
        '{"product_name":"","brand":"","serving_size_g":null,'
        '"servings_per_container":null,'
        '"nutrition_per_serving":{"calories":null,"protein":null,"fat":null,'
        '"saturated_fat":null,"trans_fat":null,"carbs":null,"sugar":null,'
        '"sodium":null,"fiber":null},'
        '"ocr_text":"","confidence_note":""}'
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                ]
            }
        ]
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return extract_json_block(text)


def normalize_ocr_result(parsed: dict) -> dict:
    serving_size_g = extract_number(parsed.get("serving_size_g"))
    servings_per_container = extract_number(parsed.get("servings_per_container"), as_int=False)
    nutrition_per_serving = normalize_nutrition_payload(
        {
            "calories": extract_number((parsed.get("nutrition_per_serving") or {}).get("calories")),
            "protein": extract_number((parsed.get("nutrition_per_serving") or {}).get("protein")),
            "fat": extract_number((parsed.get("nutrition_per_serving") or {}).get("fat")),
            "carbs": extract_number((parsed.get("nutrition_per_serving") or {}).get("carbs")),
            "sodium": extract_number((parsed.get("nutrition_per_serving") or {}).get("sodium")),
            "fiber": extract_number((parsed.get("nutrition_per_serving") or {}).get("fiber")),
            "sugar": extract_number((parsed.get("nutrition_per_serving") or {}).get("sugar")),
            "saturated_fat": extract_number((parsed.get("nutrition_per_serving") or {}).get("saturated_fat")),
            "trans_fat": extract_number((parsed.get("nutrition_per_serving") or {}).get("trans_fat")),
        }
    )
    nutrition_per_100g = scale_nutrition_per_100g(nutrition_per_serving, serving_size_g)
    return {
        "product_name": (parsed.get("product_name") or "未命名食品").strip(),
        "brand": (parsed.get("brand") or "").strip(),
        "serving_size_g": serving_size_g,
        "servings_per_container": servings_per_container,
        "nutrition_per_serving": nutrition_per_serving,
        "nutrition_per_100g": nutrition_per_100g,
        "ocr_text": (parsed.get("ocr_text") or "").strip(),
        "confidence_note": (parsed.get("confidence_note") or "").strip(),
    }
