import base64
import binascii
import json
import os
import re

import requests

from services.nutrient_service import get_nutrient_value


RETRYABLE_GEMINI_STATUS_CODES = {401, 403, 404, 429, 500, 502, 503, 504}
# Keep defaults aligned with models currently exposed by the v1beta API. Older
# 1.5/2.0 model ids are retained only when explicitly configured by deployers.
# 固定版號的模型會被停用：gemini-2.5-flash 與 gemini-2.5-flash-lite 對新金鑰
# 已經回 404「no longer available to new users」，只有最早開通的那把還能用。
# 所以把不會過期的 -latest 別名排在前面，固定版號只當備援。
# 目前實際可用的組合可用 GET /health/gemini?generate=1 查。
DEFAULT_GEMINI_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
]
MAX_IMAGE_BYTES = 8 * 1024 * 1024



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
        "sugar": round_nutrient(get_nutrient_value(nutrition, "sugar", None), 1),
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
        "sugar": base_nutrition.get("sugar", base_nutrition.get("refined_sugar", 0)),
        "saturated_fat": base_nutrition.get("saturated_fat", 0),
        "trans_fat": base_nutrition.get("trans_fat", 0),
        "is_fried": food_doc.get("is_fried", False),
        "unit": food_doc.get("unit", "per serving"),
        "source": food_doc.get("source", "custom-food"),
        "serving_size_g": food_doc.get("serving_size_g"),
        "allergens": food_doc.get("allergens", []) or [],
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


def detect_image_mime(img_bytes: bytes) -> str | None:
    if img_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if img_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if img_bytes.startswith(b"GIF8"):
        return "image/gif"
    if img_bytes.startswith(b"RIFF") and b"WEBP" in img_bytes[:16]:
        return "image/webp"
    return None


def decode_image_base64(value, max_bytes: int = MAX_IMAGE_BYTES) -> tuple[bytes, str, str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("image 必須是非空的 Base64 圖片")

    encoded = value.strip()
    if encoded.lower().startswith("data:"):
        match = re.fullmatch(
            r"data:image/(?:png|jpe?g|gif|webp);base64,([\s\S]+)",
            encoded,
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError("image Data URI 格式不正確或不是支援的圖片類型")
        encoded = match.group(1)

    encoded = "".join(encoded.split())
    max_encoded_length = ((max_bytes + 2) // 3) * 4
    if len(encoded) > max_encoded_length:
        raise ValueError(f"圖片大小不可超過 {max_bytes // (1024 * 1024)} MB")

    try:
        img_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("image 不是有效的 Base64 圖片") from error

    if not img_bytes:
        raise ValueError("image 不可為空圖片")
    if len(img_bytes) > max_bytes:
        raise ValueError(f"圖片大小不可超過 {max_bytes // (1024 * 1024)} MB")

    mime_type = detect_image_mime(img_bytes)
    if not mime_type:
        raise ValueError("僅支援 JPEG、PNG、GIF 或 WebP 圖片")

    return img_bytes, encoded, mime_type


def get_gemini_api_keys(explicit_key: str | None = None) -> list[str]:
    raw_keys = [
        explicit_key,
        os.environ.get("GEMINI_API_KEYS"),
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GOOGLE_API_KEY"),
    ]
    keys: list[str] = []
    seen = set()
    for raw in raw_keys:
        if not raw:
            continue
        for key in raw.split(","):
            normalized = key.strip()
            if normalized and normalized not in seen:
                keys.append(normalized)
                seen.add(normalized)
    return keys


def _try_generate(key: str, model: str, timeout: float) -> tuple[int, str]:
    """實際打一次最小的 generateContent，回 (status, 訊息)。"""
    try:
        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": "ping"}]}],
                  "generationConfig": {"maxOutputTokens": 1}},
            timeout=timeout,
        )
        if res.status_code == 200:
            return 200, "ok"
        detail = ""
        try:
            detail = (res.json().get("error") or {}).get("message", "")[:160]
        except Exception:
            detail = res.text[:160]
        return res.status_code, detail
    except Exception as error:
        return 0, str(error)[:160]


def probe_gemini_models(timeout: float = 10.0, generate: bool = False) -> dict:
    """問 Google 每一把金鑰實際能用哪些模型。

    設定裡的模型清單跟金鑰的實際權限對不上時，只會看到一連串 404，
    分不出是模型名寫錯還是金鑰沒開通。這裡直接查，不用猜。
    金鑰只回前 8 碼，不會把完整值吐出來。
    """
    configured = get_gemini_models()
    report = []
    usable_everywhere = None
    for key in get_gemini_api_keys():
        entry = {"key": f"{key[:8]}...", "available": [], "error": None}
        try:
            res = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": key},
                timeout=timeout,
            )
            if res.status_code != 200:
                entry["error"] = f"HTTP {res.status_code}"
            else:
                names = [
                    model.get("name", "").removeprefix("models/")
                    for model in res.json().get("models", [])
                    if "generateContent" in (model.get("supportedGenerationMethods") or [])
                ]
                entry["available"] = sorted(name for name in names if name)
        except Exception as error:
            entry["error"] = str(error)
        if entry["available"]:
            found = set(entry["available"])
            usable_everywhere = found if usable_everywhere is None else (usable_everywhere & found)
        entry["configured_and_usable"] = [m for m in configured if m in set(entry["available"])]

        if generate:
            # ListModels 會列出整個型錄，但免費方案的金鑰對某些模型呼叫
            # generateContent 仍會回 404。真的打一次才知道哪個能用。
            entry["generate_results"] = {}
            for model in entry["configured_and_usable"]:
                status, detail = _try_generate(key, model, timeout)
                entry["generate_results"][model] = status if status == 200 else f"{status} {detail}"
                if status == 200:
                    entry["first_working_model"] = model
                    break

        report.append(entry)

    return {
        "configured_models": configured,
        "keys": report,
        # 設定清單裡沒有任何一把金鑰能用的模型 = 白白浪費重試時間
        "configured_but_unusable": [
            model for model in configured
            if not any(model in set(entry["available"]) for entry in report if entry["available"])
        ],
        "usable_by_every_key": sorted(usable_everywhere or []),
        "keys_that_can_generate": [
            entry["key"] for entry in report if entry.get("first_working_model")
        ] if generate else None,
    }


def get_gemini_models() -> list[str]:
    raw_models = [os.environ.get("GEMINI_MODELS"), os.environ.get("GEMINI_MODEL")]
    models: list[str] = []
    seen = set()
    for raw in raw_models:
        if not raw:
            continue
        for model in raw.split(","):
            normalized = model.strip()
            if normalized and normalized not in seen:
                models.append(normalized)
                seen.add(normalized)
    for model in DEFAULT_GEMINI_MODELS:
        if model not in seen:
            models.append(model)
            seen.add(model)
    return models


def call_gemini_nutrition_ocr_with_rotation(image_b64: str, mime_type: str, api_keys: list[str]) -> dict:
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
                return call_gemini_nutrition_ocr(image_b64, mime_type, api_key, model)
            except requests.HTTPError as e:
                last_error = e
                status_code = e.response.status_code if e.response is not None else None
                if status_code not in RETRYABLE_GEMINI_STATUS_CODES or attempt == total_attempts:
                    raise
                print(f"[WARN] Gemini key #{key_index + 1} model {model} failed with HTTP {status_code}; trying next option")

    if last_error:
        raise last_error
    raise ValueError("Gemini API key 輪替失敗")


def call_gemini_nutrition_ocr(image_b64: str, mime_type: str, api_key: str, gemini_model: str | None = None) -> dict:
    gemini_model = gemini_model or get_gemini_models()[0]
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
