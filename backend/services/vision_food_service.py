import os

import requests

from services.food_service import search_foods
from services.nutrition_label_service import extract_json_block, extract_number
from services.predict_service import build_detection_reliability, build_portion_range, check_food_safety


VISION_FOOD_MIN_CONFIDENCE = float(os.environ.get("VISION_FOOD_MIN_CONFIDENCE", "0.45"))
RETRYABLE_GEMINI_STATUS_CODES = {401, 403, 429, 500, 502, 503, 504}


def call_gemini_food_recognition_with_rotation(image_b64: str, mime_type: str, api_keys: list[str]) -> dict:
    if not api_keys:
        raise ValueError("缺少 Gemini API key，請設定 GEMINI_API_KEYS 或 GEMINI_API_KEY 環境變數")

    last_error: requests.HTTPError | None = None
    for index, api_key in enumerate(api_keys):
        try:
            return call_gemini_food_recognition(image_b64, mime_type, api_key)
        except requests.HTTPError as e:
            last_error = e
            status_code = e.response.status_code if e.response is not None else None
            if status_code not in RETRYABLE_GEMINI_STATUS_CODES or index == len(api_keys) - 1:
                raise
            print(f"[!] Gemini food key #{index + 1} failed with HTTP {status_code}; trying next key")

    if last_error:
        raise last_error
    raise ValueError("Gemini food recognition key rotation failed")


def call_gemini_food_recognition(image_b64: str, mime_type: str, api_key: str) -> dict:
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    prompt = (
        "你是台灣飲食紀錄 App 的食物影像分析器。請辨識照片中可食用項目，"
        "特別注意台灣常見餐點、便當、白飯、麵、湯、肉類、青菜與飲料。"
        "不要直接產生營養數字，只估計食物名稱與份量。"
        "只回傳合法 JSON，不要加 markdown、不要加解釋。"
        "若無法確定，confidence 請降低並在 uncertainty_notes 說明。"
        "JSON schema: "
        '{"meal_guess":"","items":[{"name_zh":"","name_en":"",'
        '"confidence":0.0,"estimated_weight_g":null,"portion_description":"",'
        '"visual_evidence":"","alternatives":[""]}],'
        '"uncertainty_notes":[""]}'
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


def build_vision_food_response(
    parsed: dict,
    storage,
    tfda_db: dict,
    disease_rules: dict,
    user_conditions: list,
    user_allergens: list,
    user_id: str | None,
    build_custom_food_search_result,
) -> dict:
    detections = []
    rejected_detections = []
    total_calories = 0
    total_sodium = 0

    for index, item in enumerate(parsed.get("items") or []):
        name_zh = normalize_text(item.get("name_zh"))
        if not name_zh:
            continue

        confidence = normalize_confidence(item.get("confidence"))
        alternatives = [normalize_text(value) for value in (item.get("alternatives") or [])]
        alternatives = [value for value in alternatives if value and value != name_zh]
        search_terms = [name_zh, *alternatives]
        food_matches = find_food_matches(storage, tfda_db, search_terms, user_id, build_custom_food_search_result)

        if confidence < VISION_FOOD_MIN_CONFIDENCE:
            rejected_detections.append(
                {
                    "label": name_zh,
                    "confidence": confidence,
                    "reason": f"Gemini Vision 食物辨識信心過低 ({confidence:.0%})",
                    "search_hints": search_terms[:5],
                }
            )
            continue

        if not food_matches:
            rejected_detections.append(
                {
                    "label": name_zh,
                    "confidence": confidence,
                    "reason": "找不到可信的 TFDA 或自訂食品營養對應，請改用手動搜尋",
                    "search_hints": search_terms[:5],
                }
            )
            continue

        matched_food = food_matches[0]
        estimated_weight = normalize_weight(item.get("estimated_weight_g"))
        if estimated_weight is None:
            estimated_weight = 100.0

        needs_confirmation = confidence < 0.75 or len(food_matches) > 1
        nutrients = {
            "calories": matched_food.get("calories", 0),
            "protein": matched_food.get("protein", 0),
            "fat": matched_food.get("fat", 0),
            "carbs": matched_food.get("carbs", 0),
            "sodium": matched_food.get("sodium", 0),
            "fiber": matched_food.get("fiber", 0),
            "source": matched_food.get("source", "TFDA"),
            "allergens": [],
            "gi": "medium",
        }
        reliability = build_detection_reliability(name_zh, confidence, needs_confirmation, nutrients)
        portion_range = build_portion_range(estimated_weight, reliability["level"])
        scale = estimated_weight / 100.0
        scaled_nutrition = {
            "calories": round((nutrients.get("calories") or 0) * scale),
            "protein": round((nutrients.get("protein") or 0) * scale, 1),
            "carbs": round((nutrients.get("carbs") or 0) * scale, 1),
            "fat": round((nutrients.get("fat") or 0) * scale, 1),
            "sodium": round((nutrients.get("sodium") or 0) * scale),
            "fiber": round((nutrients.get("fiber") or 0) * scale, 1),
        }
        total_calories += scaled_nutrition["calories"]
        total_sodium += scaled_nutrition["sodium"]

        warnings = []
        if needs_confirmation:
            warnings.append("Gemini Vision 初判結果，請確認食品名稱與份量")
        if item.get("portion_description"):
            warnings.append(f"份量描述：{item['portion_description']}")
        warnings.extend(check_food_safety(nutrients, estimated_weight, user_conditions, user_allergens, disease_rules))

        detections.append(
            {
                "label": name_zh,
                "name_zh": matched_food.get("name_zh") or name_zh,
                "detected_name_zh": name_zh,
                "confidence": confidence,
                "needs_confirmation": needs_confirmation,
                "source": matched_food.get("source", "TFDA"),
                "bounding_box": build_placeholder_bbox(index),
                "estimated_weight_g": estimated_weight,
                "portion_range_g": portion_range,
                "portion_estimation_method": "gemini_vision_portion_estimate_v1",
                "portion_description": item.get("portion_description") or "",
                "visual_evidence": item.get("visual_evidence") or "",
                "reliability": reliability,
                "nutrition": scaled_nutrition,
                "gi": nutrients.get("gi"),
                "allergens": nutrients.get("allergens", []),
                "warnings": warnings,
                "matched_food": matched_food,
                "alternatives": food_matches[1:5],
            }
        )

    return {
        "engine": "gemini-vision-tfda",
        "meal_guess": parsed.get("meal_guess") or "",
        "detections": detections,
        "rejected_detections": rejected_detections,
        "uncertainty_notes": parsed.get("uncertainty_notes") or [],
        "summary": {
            "total_items": len(detections),
            "rejected_items": len(rejected_detections),
            "total_calories": total_calories,
            "total_sodium": total_sodium,
            "requires_user_confirmation": any(item.get("needs_confirmation") for item in detections),
        },
    }


def find_food_matches(storage, tfda_db, search_terms: list[str], user_id: str | None, build_custom_food_search_result) -> list[dict]:
    matches = []
    seen = set()
    for term in search_terms:
        for candidate in search_foods(storage, tfda_db, term, 5, user_id, build_custom_food_search_result):
            key = candidate.get("key") or candidate.get("food_id") or candidate.get("name_zh")
            if key in seen:
                continue
            matches.append(candidate)
            seen.add(key)
        if matches:
            break
    return matches


def normalize_text(value) -> str:
    return str(value or "").strip()


def normalize_confidence(value) -> float:
    confidence = extract_number(value)
    if confidence is None:
        return 0.5
    if confidence > 1:
        confidence = confidence / 100.0
    return round(max(0.0, min(1.0, confidence)), 4)


def normalize_weight(value) -> float | None:
    weight = extract_number(value)
    if weight is None or weight <= 0:
        return None
    return round(max(1.0, min(2000.0, weight)), 1)


def build_placeholder_bbox(index: int) -> dict:
    offset = (index % 3) * 0.08
    return {"x": round(0.08 + offset, 4), "y": round(0.08 + offset, 4), "w": 0.32, "h": 0.24}
