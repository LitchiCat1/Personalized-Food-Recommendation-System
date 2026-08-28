import os

import requests

from services.food_service import search_foods
from services.food_analysis_service import build_detection_reliability, build_portion_range, check_food_safety
from services.nutrition_label_service import extract_json_block, extract_number, get_gemini_models
from services.nutrient_service import is_fried_food_name


VISION_FOOD_MIN_CONFIDENCE = float(os.environ.get("VISION_FOOD_MIN_CONFIDENCE", "0.45"))
RETRYABLE_GEMINI_STATUS_CODES = {401, 403, 404, 429, 500, 502, 503, 504}


def call_gemini_food_recognition_with_rotation(image_b64: str, mime_type: str, api_keys: list[str]) -> dict:
    if not api_keys:
        raise ValueError("缺少 Gemini API key，請設定 GEMINI_API_KEYS 或 GEMINI_API_KEY 環境變數")

    last_error: requests.HTTPError | None = None
    models = get_gemini_models()
    total_attempts = len(api_keys) * len(models)
    attempt = 0
    for key_index, api_key in enumerate(api_keys):
        for model in models:
            attempt += 1
            try:
                return call_gemini_food_recognition(image_b64, mime_type, api_key, model)
            except requests.HTTPError as e:
                last_error = e
                status_code = e.response.status_code if e.response is not None else None
                if status_code not in RETRYABLE_GEMINI_STATUS_CODES or attempt == total_attempts:
                    raise
                print(f"[WARN] Gemini food key #{key_index + 1} model {model} failed with HTTP {status_code}; trying next option")

    if last_error:
        raise last_error
    raise ValueError("Gemini food recognition key rotation failed")


def call_gemini_food_recognition(image_b64: str, mime_type: str, api_key: str, gemini_model: str | None = None) -> dict:
    gemini_model = gemini_model or get_gemini_models()[0]
    prompt = (
        "你是台灣飲食紀錄 App 的食物影像分析器。請辨識照片中可食用項目，"
        "特別注意台灣常見餐點、便當、白飯、麵、湯、肉類、青菜與飲料。"
        "你不能連線資料庫，也不要直接產生營養數字；營養資料會由後端用你提供的候選名稱查 TFDA 與使用者自訂食品資料庫。"
        "請提供常見中文食品名稱與可查資料庫的同義候選，例如白飯/白米飯、雞腿便當/雞腿/白飯/青菜。"
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
    *args,
) -> dict:
    if len(args) == 4:
        allergen_taxonomy = None
        user_conditions, user_allergens, user_id, build_custom_food_search_result = args
    elif len(args) == 5:
        allergen_taxonomy, user_conditions, user_allergens, user_id, build_custom_food_search_result = args
    else:
        raise TypeError(
            "build_vision_food_response expected 4 or 5 trailing arguments "
            "(user_conditions, user_allergens, user_id, build_custom_food_search_result"
            " or allergen_taxonomy, user_conditions, user_allergens, user_id, build_custom_food_search_result)"
        )

    allergen_taxonomy = allergen_taxonomy or {"groups": []}
    user = storage.get_user(user_id) if user_id else None
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
            "sugar": matched_food.get("sugar", 0),
            "saturated_fat": matched_food.get("saturated_fat", 0),
            "trans_fat": matched_food.get("trans_fat", 0),
            "calcium": matched_food.get("calcium", 0),
            "iron": matched_food.get("iron", 0),
            "is_fried": matched_food.get("is_fried") is True
            or is_fried_food_name(matched_food.get("name_zh"), matched_food.get("name_en"), name_zh),
            "source": matched_food.get("source", "TFDA"),
            "allergens": matched_food.get("allergens", []),
            "gi": "medium",
        }
        reliability = build_detection_reliability(name_zh, confidence, needs_confirmation, nutrients)
        portion_range = build_portion_range(estimated_weight, reliability["level"])
        scale = estimated_weight / 100.0
        scaled_nutrition = {
            "calories": round((nutrients.get("calories") or 0) * scale),
            "protein": round((nutrients.get("protein") or 0) * scale, 1),
            "carbs": round((nutrients.get("carbs") or 0) * scale, 1),
            "sugar": round((nutrients.get("sugar") or 0) * scale, 1),
            "fat": round((nutrients.get("fat") or 0) * scale, 1),
            "saturated_fat": round((nutrients.get("saturated_fat") or 0) * scale, 1),
            "trans_fat": round((nutrients.get("trans_fat") or 0) * scale, 1),
            "sodium": round((nutrients.get("sodium") or 0) * scale),
            "fiber": round((nutrients.get("fiber") or 0) * scale, 1),
            "calcium": round((nutrients.get("calcium") or 0) * scale),
            "iron": round((nutrients.get("iron") or 0) * scale, 1),
            "is_fried": nutrients.get("is_fried") is True,
        }
        total_calories += scaled_nutrition["calories"]
        total_sodium += scaled_nutrition["sodium"]

        warnings = []
        if needs_confirmation:
            warnings.append("Gemini Vision 初判結果，請確認食品名稱與份量")
        if item.get("portion_description"):
            warnings.append(f"份量描述：{item['portion_description']}")
        warnings.extend(
            check_food_safety(
                nutrients,
                estimated_weight,
                user_conditions,
                user_allergens,
                disease_rules,
                allergen_taxonomy,
                user_profile=user,
            )
        )

        swap_suggestion = find_swap_suggestion(tfda_db, nutrients, name_zh)
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
                "swap_suggestion": swap_suggestion,
            }
        )

    return {
        "engine": "gemini-vision-db-lookup",
        "nutrition_grounding": "database_only",
        "database_sources": ["user_custom_foods", "TFDA"],
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


def find_swap_suggestion(tfda_db: dict, nutrients: dict, name_zh: str) -> dict | None:
    """Return a healthier TFDA alternative for high-sodium, fried, or high-GI foods."""
    sodium_per100 = float(nutrients.get("sodium") or 0)
    is_fried = nutrients.get("is_fried") is True

    if sodium_per100 < 600 and not is_fried:
        return None  # no swap needed

    # Determine swap category keyword from food name
    categories = []
    if any(kw in name_zh for kw in ["飯", "白飯", "米飯"]):
        categories = ["糙米", "十穀米", "燕麥"]
    elif any(kw in name_zh for kw in ["麵", "拉麵", "炒麵"]):
        categories = ["蒟蒻麵", "蔬菜麵", "冬粉"]
    elif any(kw in name_zh for kw in ["肉", "豬", "牛", "雞腿"]):
        categories = ["雞胸肉", "豆腐", "魚"]
    elif any(kw in name_zh for kw in ["炸", "油炸", "薯條"]):
        categories = ["烤", "蒸", "水煮"]
    else:
        categories = ["蔬菜", "沙拉", "豆腐"]

    for keyword in categories:
        for key, food in list(tfda_db.items())[:3000]:
            fname = food.get("name_zh", "")
            if keyword in fname:
                food_sodium = float(food.get("sodium") or 0)
                food_fried = bool(food.get("is_fried"))
                if food_sodium < sodium_per100 * 0.7 and not food_fried:
                    return {
                        "name": fname,
                        "reason": f"鈉含量較低（{round(food_sodium)}mg），{'' if not is_fried else '且非油炸'}建議替換",
                        "calories": food.get("calories"),
                        "sodium": round(food_sodium),
                        "protein": food.get("protein"),
                    }
    return None


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
