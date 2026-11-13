import os
import math

import requests

from services.medical_risk_service import evaluate_meal_medical_risk
from services.food_analysis_service import build_detection_reliability, build_portion_range, check_food_safety
from services.nutrition_label_service import (
    call_gemini_with_rotation,
    extract_json_block,
    extract_number,
    gemini_generate_url,
    gemini_headers,
    get_gemini_models,
)
from services.nutrient_service import is_fried_food_name
from services.ai_relay_service import get_relay_config, relay_chat
from services.vision_nutrition_service import find_vision_food_matches


VISION_FOOD_MIN_CONFIDENCE = float(os.environ.get("VISION_FOOD_MIN_CONFIDENCE", "0.45"))


def call_gemini_food_recognition_with_rotation(image_b64: str, mime_type: str, api_keys: list[str]) -> dict:
    return call_gemini_with_rotation(
        api_keys,
        lambda api_key, model: call_gemini_food_recognition(image_b64, mime_type, api_key, model),
        "food",
    )


def call_gemini_food_recognition(image_b64: str, mime_type: str, api_key: str, gemini_model: str | None = None) -> dict:
    gemini_model = gemini_model or get_gemini_models()[0]
    prompt = build_food_recognition_prompt()
    if get_relay_config():
        text, _finish = relay_chat(prompt, image_base64=image_b64, image_mime_type=mime_type)
        if _finish in ("length", "max_tokens"):
            raise ValueError("Food recognition output was truncated")
        return normalize_vision_result(extract_json_block(text))
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
    resp = requests.post(gemini_generate_url(gemini_model), headers=gemini_headers(api_key), json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return normalize_vision_result(extract_json_block(text))


def build_food_recognition_prompt():
    return (
        "你是台灣餐點照片辨識器。先辨識可見食物，不要為了符合資料庫而改名，也不要產生任何營養數字。"
        "請先逐區檢查每個容器及便當隔間：由左上到右下，檢查主食上方的肉、蛋與配菜、邊緣及被部分遮住的食物。"
        "最後再檢查一次各區域，避免只認出白飯、主菜或面積最大的食物而漏掉小份配菜。"
        "meal_guess 寫整餐常見名稱（例如滷肉飯、雞腿便當），items 則列出互不重疊的可食項目。"
        "滷肉飯應分白飯、可見滷肉、可見蛋與配菜；不可用白飯代替整碗滷肉飯。"
        "便當分主食、主菜與各樣配菜；一格混合蔬菜如能看清豆干、紅蘿蔔、毛豆，分開列出並各估重量。"
        "湯麵分熟麵條、肉、青菜與湯；不要同時列整碗麵及相同食材而重複計算。"
        "水餃、包子、蛋糕、香腸、地瓜球等本身是一項食品，不拆成不可見的餡料或原料。"
        "沖泡泡麵可整杯列為泡麵（含湯），不可再重複列其麵與湯。大腸包小腸可分香腸與糯米腸。"
        "只能根據照片可見證據，不能因典型配方就加蛋、肉或醬料；不要猜隱藏餡料、品牌口味或蛋糕內餡。"
        "不確定菜種時使用較保守的名稱（如葉菜、黃色瓜類），降低 confidence 並說明可能名稱。"
        "不要把看不清楚的背景餐盤加入已確認項目；若背景有部分小菜，請在 uncertainty_notes 註明未納入。"
        "每種食品多個相同個體只列一項，count 寫可見數量，estimated_weight_g 是全部個體的總可食重量。"
        "重量以照片中已烹調、可食的狀態估算，骨頭、容器不算；湯與麵分開時不能把湯重算進麵。"
        "整顆蛋糕是整顆重量，不當成一片；照片無比例尺時 weight_confidence 請降低，無法估重則 null。"
        "food_state 只能是 prepared（熟食或沖泡後）、raw（生食材）、dry（未沖泡乾品）。"
        "alternatives 僅可列同一食品的同義名稱，不可列其他可能食物、單一原料或整餐。"
        "例如白飯的同義詞為白米飯，不是滷肉飯；糯米腸不是豬大腸；雞腿不是雞腿菇。"
        "只回合法 JSON，無 markdown，JSON schema: "
        '{"meal_guess":"","items":[{"name_zh":"","name_en":"",'
        '"confidence":0.0,"estimated_weight_g":null,"weight_confidence":0.0,'
        '"food_state":"prepared","count":null,"portion_description":"",'
        '"visual_evidence":"","alternatives":[]}],"uncertainty_notes":[]}'
    )


def normalize_vision_result(parsed):
    if isinstance(parsed, list):
        parsed = {"items": parsed}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        raise ValueError("Food recognition requires an items array")
    items = []
    for item in parsed["items"]:
        if not isinstance(item, dict) or not normalize_text(item.get("name_zh")):
            continue
        normalized = dict(item)
        alternatives = item.get("alternatives") or []
        normalized["alternatives"] = alternatives if isinstance(alternatives, list) else [alternatives]
        items.append(normalized)
    notes = parsed.get("uncertainty_notes") or []
    return dict(parsed, items=items, uncertainty_notes=notes if isinstance(notes, list) else [notes])


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

    parsed = normalize_vision_result(parsed)
    allergen_taxonomy = allergen_taxonomy or {"groups": []}
    user = storage.get_user(user_id) if user_id else None
    detections = []
    # 一餐合計的檢查需要所有道菜——逐道檢查抓不到「每道都在額度內、
    # 加起來卻超過整餐上限」的情況。
    meal_items = []
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
        food_matches = find_vision_food_matches(storage, tfda_db, item, user_id, build_custom_food_search_result)

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
                    "reason": "已辨識食物，但缺少相同食品與食用狀態的可信營養資料；未計入營養合計，請以標示或自訂食品補充",
                    "recognition_status": "recognized",
                    "nutrition_status": "unmatched",
                    "search_hints": search_terms[:5],
                }
            )
            continue

        matched_food = food_matches[0]
        optional_nutrients = {
            "fiber": "膳食纖維", "sugar": "總糖", "saturated_fat": "飽和脂肪", "trans_fat": "反式脂肪",
        }
        missing_nutrients = [field for field in optional_nutrients if matched_food.get(field) is None]
        estimated_weight = normalize_weight(item.get("estimated_weight_g"))
        missing_weight = estimated_weight is None
        if estimated_weight is None:
            estimated_weight = 100.0

        match_notes = matched_food.get("match_notes", [])
        needs_confirmation = (confidence < 0.75 or len(food_matches) > 1 or bool(match_notes)
                              or missing_weight or bool(missing_nutrients)
                              or normalize_confidence(item.get("weight_confidence", 0.5)) < 0.75)
        nutrients = {
            # 過敏原與疾病禁忌（例如痛風的豬肝）是比對名稱找出來的；TFDA 的品項
            # 沒有標過敏原，名字沒帶進來的話，對蛋過敏的人拍荷包蛋也不會被提醒。
            "label": name_zh,
            "name_zh": matched_food.get("name_zh") or name_zh,
            "calories": matched_food.get("calories", 0),
            "protein": matched_food.get("protein", 0),
            "fat": matched_food.get("fat", 0),
            "carbs": matched_food.get("carbs", 0),
            "sodium": matched_food.get("sodium", 0),
            "fiber": matched_food.get("fiber", 0),
            "sugar": matched_food.get("sugar", 0),
            "saturated_fat": matched_food.get("saturated_fat", 0),
            "trans_fat": matched_food.get("trans_fat", 0),
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
            "is_fried": nutrients.get("is_fried") is True,
        }
        total_calories += scaled_nutrition["calories"]
        total_sodium += scaled_nutrition["sodium"]
        meal_items.append({"nutrients": nutrients, "portion_g": estimated_weight})

        warnings = []
        if needs_confirmation:
            warnings.append("影像辨識與份量為估計值，請確認食品名稱與可食重量")
        warnings.extend(match_notes)
        if missing_nutrients:
            labels = "、".join(optional_nutrients[field] for field in missing_nutrients)
            warnings.append(f"資料來源未提供{labels}；缺值不代表實測為 0，相關營養合計可能低估")
        if missing_weight:
            warnings.append("照片無法估重，暫以 100 g 換算；請修改重量後再記錄")
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

        detections.append(
            {
                "label": name_zh,
                "name_zh": name_zh,
                "detected_name_zh": name_zh,
                "confidence": confidence,
                "needs_confirmation": needs_confirmation,
                "source": matched_food.get("source", "TFDA"),
                "nutrition_match_type": "reference" if match_notes else "name_or_alias",
                "nutrition_source_url": matched_food.get("source_url"),
                "nutrition_status": "reference_estimate" if match_notes else "database_estimate",
                "bounding_box": build_placeholder_bbox(index),
                "estimated_weight_g": estimated_weight,
                "portion_range_g": portion_range,
                "portion_estimation_method": "gemini_vision_portion_estimate_v1",
                "portion_description": item.get("portion_description") or "",
                "visual_evidence": item.get("visual_evidence") or "",
                "reliability": reliability,
                "nutrition": scaled_nutrition,
                "missing_nutrition_fields": missing_nutrients,
                "gi": nutrients.get("gi"),
                "allergens": nutrients.get("allergens", []),
                "warnings": warnings,
                "matched_food": matched_food,
                "alternatives": food_matches[1:5],
            }
        )

    meal_risk = evaluate_meal_medical_risk(
        meal_items, user_conditions, user_allergens, disease_rules, allergen_taxonomy, user_profile=user
    )

    if rejected_detections:
        for detection in detections:
            detection["warnings"].append(f"本餐有 {len(rejected_detections)} 項尚未計入，營養合計不完整")

    return {
        "engine": "gemini-vision-db-lookup",
        # 這一餐加起來超過單餐上限的提醒。逐道 warnings 看不出來這件事。
        "meal_warnings": meal_risk["caution_reasons"],
        "nutrition_grounding": "database_only",
        "database_sources": ["user_custom_foods", "TFDA", "USDA FNDDS"],
        "nutrition_database_priority": ["TFDA", "USDA FNDDS"],
        "meal_guess": parsed.get("meal_guess") or "",
        "detections": detections,
        "rejected_detections": rejected_detections,
        "uncertainty_notes": parsed.get("uncertainty_notes") or [],
        "summary": {
            "total_items": len(detections),
            "recognized_items": len(parsed["items"]),
            "rejected_items": len(rejected_detections),
            "nutrition_complete": not rejected_detections and bool(detections),
            "nutrition_totals_scope": "matched_items_only",
            "optional_nutrients_complete": not rejected_detections and bool(detections)
                and not any(item["missing_nutrition_fields"] for item in detections),
            "total_calories": total_calories,
            "total_sodium": total_sodium,
            "requires_user_confirmation": bool(rejected_detections) or any(item.get("needs_confirmation") for item in detections),
        },
    }


def find_food_matches(storage, tfda_db, search_terms: list[str], user_id: str | None, build_custom_food_search_result) -> list[dict]:
    if not search_terms:
        return []
    return find_vision_food_matches(storage, tfda_db, {"name_zh": search_terms[0]}, user_id, build_custom_food_search_result)


def normalize_text(value) -> str:
    return str(value or "").strip()


def normalize_confidence(value) -> float:
    confidence = extract_number(value)
    if confidence is None:
        return 0.5
    if not math.isfinite(confidence):
        return 0.0
    if confidence > 1:
        confidence = confidence / 100.0
    return round(max(0.0, min(1.0, confidence)), 4)


def normalize_weight(value) -> float | None:
    weight = extract_number(value)
    if weight is None or not math.isfinite(weight) or weight <= 0:
        return None
    return round(max(1.0, min(2000.0, weight)), 1)


def build_placeholder_bbox(index: int) -> dict:
    offset = (index % 3) * 0.08
    return {"x": round(0.08 + offset, 4), "y": round(0.08 + offset, 4), "w": 0.32, "h": 0.24}
