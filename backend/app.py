"""
NutriLens Backend — Flask API
PRD-aligned: Gemini Vision food recognition + nutrition analysis + user management
"""

import json
import math
import os
import uuid
from datetime import datetime, timezone

import psycopg2
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from repositories.storage import StorageRepository
from services.auth_service import AuthError, is_auth_required, is_supabase_auth_configured, verify_supabase_user
from services.disease_rule_service import build_disease_rules_response, build_medical_metadata_response, load_allergen_taxonomy, load_disease_rules
from services.env_service import load_local_env
from services.history_service import build_history_response
from services.google_places_service import GooglePlacesAPIError, GooglePlacesConfigError
from services.healthy_food_service import build_google_places_food_recommendations, build_healthy_food_recommendations, load_restaurant_catalog
from services.food_service import build_custom_food_doc, search_foods
from services.nutrition_label_service import (
    build_custom_food_search_result,
    call_gemini_nutrition_ocr,
    call_gemini_nutrition_ocr_with_rotation,
    decode_image_base64,
    extract_number,
    get_gemini_api_keys,
    normalize_nutrition_payload,
    normalize_ocr_result,
    scale_nutrition_per_100g,
)
from services.nutrition_progress_service import build_daily_nutrition_progress
from services.nutrient_service import NUTRITION_FIELDS, get_nutrient_value
from services.profile_service import build_bmr_response, build_user_profile
from services.restaurant_ai_service import build_restaurant_ai_summary
from services.vision_food_service import (
    build_vision_food_response,
    call_gemini_food_recognition_with_rotation,
)
from services.robust_restaurant_scraper_service import enrich_restaurant_with_gemini
from services.medical_risk_service import evaluate_medical_risk


load_local_env()

BASE_DIR = os.path.dirname(__file__)

pg_conn = None
database_url = os.environ.get("DATABASE_URL")
if database_url:
    try:
        pg_conn = psycopg2.connect(database_url, sslmode="require")
        pg_conn.autocommit = True
        print("[OK] PostgreSQL connected")
    except Exception as e:
        pg_conn = None
        print(f"[WARN] PostgreSQL unavailable - {e}")

# ─── Optional MongoDB (graceful fallback to in-memory) ────────
mongo = None
try:
    from pymongo import MongoClient
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    mongo.server_info()  # trigger connection check
    db = mongo["nutrilens"]
    USE_MONGO = True
    print("[OK] MongoDB connected")
except Exception:
    if mongo is not None:
        mongo.close()
    USE_MONGO = False
    db = None
    print("[WARN] MongoDB unavailable - using in-memory storage")

# ─── In-memory fallback storage ──────────────────────────────
_mem_users = {}
_mem_records = []
_mem_custom_foods = []
storage = StorageRepository(db, USE_MONGO, _mem_users, _mem_records, _mem_custom_foods, pg_conn=pg_conn)

app = Flask(__name__)
CORS(app)


def get_request_user_id():
    if not is_auth_required():
        return None
    if not hasattr(request, "_cached_auth_user"):
        request._cached_auth_user = verify_supabase_user(request.headers.get("Authorization"))
    return request._cached_auth_user["id"]


def require_user_access(user_id: str | None):
    if not is_auth_required():
        return None
    if not user_id:
        raise AuthError("缺少 user_id", 400)

    authenticated_user_id = get_request_user_id()
    if user_id != authenticated_user_id:
        raise AuthError("無權存取其他使用者資料", 403)
    return authenticated_user_id


@app.errorhandler(AuthError)
def handle_auth_error(error):
    return jsonify({"error": str(error)}), error.status_code

# ─── Load nutrition databases ────────────────────────────────
# 1. Original hand-crafted DB (legacy fallback candidates)
DB_PATH = os.path.join(BASE_DIR, "nutrition_db.json")
with open(DB_PATH, "r", encoding="utf-8") as f:
    NUTRITION_DB = json.load(f)

# 2. TFDA 衛福部食品營養成分資料庫 (2,181 筆台灣食品)
TFDA_PATH = os.path.join(BASE_DIR, "nutrition_db_tw.json")
try:
    with open(TFDA_PATH, "r", encoding="utf-8") as f:
        TFDA_DB = json.load(f)
    print(f"[OK] TFDA nutrition DB loaded: {len(TFDA_DB)} foods")
except FileNotFoundError:
    TFDA_DB = {}
    print("[WARN] TFDA nutrition_db_tw.json not found - using fallback only")

# ─── Disease filter rules (PRD: 硬性排除規則) ────────────────
DISEASE_RULES = load_disease_rules(BASE_DIR)
print(f"[OK] Disease rules loaded: {len(DISEASE_RULES)} conditions")
ALLERGEN_TAXONOMY = load_allergen_taxonomy(BASE_DIR)
print(f"[OK] Allergen taxonomy loaded: {len(ALLERGEN_TAXONOMY.get('groups', []))} groups")

RESTAURANT_CATALOG = load_restaurant_catalog(BASE_DIR)
print(f"[OK] Restaurant catalog loaded: {len(RESTAURANT_CATALOG)} restaurants")


# ═══════════════════════════════════════════════════════════════
#  API Routes
# ═══════════════════════════════════════════════════════════════


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "Personalized Food Recommendation Backend",
        "status": "ok",
        "message": "This is the backend API. Use /health for health checks or connect the Expo frontend to this base URL.",
        "health_url": "/health",
        "docs": {
            "health": "/health",
            "disease_rules": "/disease-rules",
            "food_search": "/search/food?q=蘋果",
        },
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "postgres": pg_conn is not None,
        "mongo": USE_MONGO,
        "recognition_engine": "gemini-vision-db-lookup",
        "foods_in_db": len(NUTRITION_DB),
        "foods_in_tfda": len(TFDA_DB),
        "disease_rules": len(DISEASE_RULES),
        "disease_rule_review_status": build_disease_rules_response(DISEASE_RULES)["review_status_counts"],
        "restaurants": len(RESTAURANT_CATALOG),
        "places_enabled": bool(os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY")),
        "auth_required": is_auth_required(),
        "supabase_auth_configured": is_supabase_auth_configured(),
        "custom_foods": len(storage.get_custom_foods()),
    })


@app.route("/disease-rules", methods=["GET"])
def disease_rules():
    return jsonify(build_disease_rules_response(DISEASE_RULES))


@app.route("/medical-metadata", methods=["GET"])
def medical_metadata():
    return jsonify(build_medical_metadata_response(DISEASE_RULES, ALLERGEN_TAXONOMY))


# ─── 0. Food Search (TFDA 中文食品搜尋) ──────────────────────
@app.route("/search/food", methods=["GET"])
def search_food():
    """
    中文食品名搜尋 — 查詢 TFDA 資料庫
    ?q=蘋果&limit=20
    """
    q = request.args.get("q", "").strip()
    q_lower = q.lower()
    limit = min(int(request.args.get("limit", 20)), 100)

    if not q:
        return jsonify({"error": "缺少 q 參數"}), 400

    user_id = request.args.get("user_id")
    if is_auth_required():
        user_id = user_id or get_request_user_id()
        require_user_access(user_id)
    results = search_foods(storage, TFDA_DB, q, limit, user_id, build_custom_food_search_result)
    return jsonify({"query": q, "results": results, "count": len(results)})


# ─── 0.5 Food Detail (TFDA 單筆食品完整資料) ─────────────────
@app.route("/food/<path:food_key>", methods=["GET"])
def get_food_detail(food_key):
    """取得 TFDA 單筆食品完整營養資訊"""
    user_id = request.args.get("user_id")
    if is_auth_required():
        user_id = user_id or get_request_user_id()
        require_user_access(user_id)

    if user_id:
        custom_food = storage.get_custom_food(food_key, user_id)
        if custom_food:
            return jsonify(custom_food)

    food = TFDA_DB.get(food_key)
    if not food:
        return jsonify({"error": f"找不到食品: {food_key}"}), 404
    return jsonify(food)


@app.route("/custom-food", methods=["POST"])
def create_custom_food():
    data = request.get_json(silent=True) or {}
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))
    try:
        food_doc = build_custom_food_doc(
            data,
            normalize_nutrition_payload,
            scale_nutrition_per_100g,
            extract_number,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    saved = storage.upsert_custom_food(food_doc)
    return jsonify({"message": "自訂食品已儲存", "food": saved}), 201


@app.route("/custom-foods", methods=["GET"])
def list_custom_foods():
    user_id = request.args.get("user_id")
    if is_auth_required():
        user_id = user_id or get_request_user_id()
        require_user_access(user_id)
    foods = storage.get_custom_foods(user_id)
    return jsonify({"foods": foods, "count": len(foods)})


@app.route("/ocr/nutrition-label", methods=["POST"])
def ocr_nutrition_label():
    data = request.get_json(silent=True) or {}
    if "image" not in data:
        return jsonify({"error": "缺少 image 欄位（Base64）"}), 400

    try:
        _, image_base64, mime_type = decode_image_base64(data["image"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    api_keys = get_gemini_api_keys(data.get("api_key"))
    if not api_keys:
        return jsonify({"error": "缺少 Gemini API key，請設定 GEMINI_API_KEYS 或 GEMINI_API_KEY 環境變數"}), 400

    try:
        parsed = call_gemini_nutrition_ocr_with_rotation(image_base64, mime_type, api_keys)
        normalized = normalize_ocr_result(parsed)
        return jsonify(
            {
                "source": "Gemini OCR",
                **normalized,
                "suggested_custom_food": {
                    "name_zh": normalized["product_name"],
                    "brand": normalized["brand"],
                    "serving_size_g": normalized["serving_size_g"],
                    "servings_per_container": normalized["servings_per_container"],
                    "nutrition_per_serving": normalized["nutrition_per_serving"],
                    "nutrition_per_100g": normalized["nutrition_per_100g"],
                    "ocr_text": normalized["ocr_text"],
                    "source": "nutrition-label-ocr",
                },
            }
        )
    except requests.HTTPError as e:
        return jsonify({"error": f"Gemini API 呼叫失敗: {e.response.text[:500]}"}), 502
    except Exception as e:
        return jsonify({"error": f"營養標示辨識失敗: {str(e)}"}), 500


@app.route("/predict/vision-food", methods=["POST"])
def predict_vision_food():
    data = request.get_json(silent=True) or {}
    if "image" not in data:
        return jsonify({"error": "缺少 image 欄位（Base64）"}), 400

    try:
        _, image_base64, mime_type = decode_image_base64(data["image"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    api_keys = get_gemini_api_keys(data.get("api_key"))
    if not api_keys:
        return jsonify({"error": "缺少 Gemini API key，請設定 GEMINI_API_KEYS 或 GEMINI_API_KEY 環境變數"}), 400

    user_conditions = data.get("health_conditions", [])
    user_allergens = data.get("allergens", [])
    user_id = data.get("user_id")
    if is_auth_required():
        user_id = user_id or get_request_user_id()
        require_user_access(user_id)

    try:
        parsed = call_gemini_food_recognition_with_rotation(image_base64, mime_type, api_keys)
        return jsonify(
            build_vision_food_response(
                parsed,
                storage,
                TFDA_DB,
                DISEASE_RULES,
                ALLERGEN_TAXONOMY,
                user_conditions,
                user_allergens,
                user_id,
                build_custom_food_search_result,
            )
        )
    except requests.HTTPError as e:
        return jsonify({"error": f"Gemini Vision 食物辨識呼叫失敗: {e.response.text[:500]}"}), 502
    except Exception as e:
        return jsonify({"error": f"Gemini Vision 食物辨識失敗: {str(e)}"}), 500


# ─── 2. User Profile CRUD (PRD: 健康檔案與疾病管理) ──────────
@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    require_user_access(user_id)
    user = storage.get_user(user_id)

    if not user:
        return jsonify({"error": "使用者不存在"}), 404
    return jsonify(user)


@app.route("/user", methods=["POST"])
def create_or_update_user():
    data = request.get_json()
    if not data or "user_id" not in data:
        return jsonify({"error": "缺少 user_id"}), 400
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))

    user_doc = build_user_profile(data, DISEASE_RULES, ALLERGEN_TAXONOMY)

    storage.upsert_user(user_doc)

    return jsonify({"message": "使用者資料已更新", "user": user_doc})


# ─── 3. Dietary Records (PRD: 飲食紀錄) ──────────────────────
EDITABLE_RECORD_NUTRIENTS = NUTRITION_FIELDS


def normalize_record_foods(foods):
    if not isinstance(foods, list) or not foods:
        raise ValueError("飲食紀錄至少需要一項食物")

    normalized_foods = []
    for food in foods:
        if not isinstance(food, dict):
            raise ValueError("食物資料格式錯誤")
        name = str(food.get("name") or "").strip()
        if not name:
            raise ValueError("食物名稱不可空白")

        normalized_food = {**food, "name": name}
        for nutrient in EDITABLE_RECORD_NUTRIENTS:
            value = get_nutrient_value(food, nutrient)
            if isinstance(value, bool):
                raise ValueError(f"{nutrient} 必須是有效數字")
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{nutrient} 必須是有效數字") from None
            if not math.isfinite(numeric_value):
                raise ValueError(f"{nutrient} 必須是有效數字")
            if numeric_value < 0:
                raise ValueError(f"{nutrient} 不可小於 0")
            normalized_food[nutrient] = round(numeric_value, 2)
        is_fried = food.get("is_fried", False)
        if not isinstance(is_fried, bool):
            raise ValueError("is_fried 必須是布林值")
        normalized_food["is_fried"] = is_fried
        normalized_foods.append(normalized_food)

    return normalized_foods


def normalize_record_timestamp(value):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp 必須是有效的 ISO 日期時間")

    timestamp = value.strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamp 必須是有效的 ISO 日期時間") from None

    comparison_timezone = parsed.tzinfo or timezone.utc
    if parsed.date() > datetime.now(timezone.utc).astimezone(comparison_timezone).date():
        raise ValueError("紀錄日期不得晚於今天")
    return timestamp


@app.route("/record", methods=["POST"])
def add_record():
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "缺少資料"}), 400
    if not data.get("user_id"):
        return jsonify({"error": "缺少 user_id"}), 400
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))
    if not data.get("client_record_id"):
        data["client_record_id"] = f"server_record_{uuid.uuid4().hex}"

    try:
        foods = normalize_record_foods(data.get("foods"))
        timestamp = normalize_record_timestamp(data.get("timestamp"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    totals = {
        nutrient: round(sum(food[nutrient] for food in foods), 2)
        for nutrient in EDITABLE_RECORD_NUTRIENTS
    }
    record = {
        "user_id": data["user_id"],
        "client_record_id": data["client_record_id"],
        "timestamp": timestamp,
        "meal_type": data.get("meal_type", "午餐"),
        "foods": foods,
        **{f"total_{nutrient}": total for nutrient, total in totals.items()},
        "source": data.get("source", "camera"),  # camera | manual | nutrition-label
    }

    saved_record = storage.insert_record(record)

    if saved_record.get("_deduplicated"):
        saved_record = {key: value for key, value in saved_record.items() if key != "_deduplicated"}
        return jsonify({"message": "飲食紀錄已存在", "record": saved_record, "deduplicated": True}), 200

    return jsonify({"message": "飲食紀錄已儲存", "record": saved_record, "deduplicated": False}), 201


@app.route("/records/<user_id>", methods=["GET"])
def get_records(user_id):
    require_user_access(user_id)
    date_str = request.args.get("date")  # YYYY-MM-DD
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "limit 與 offset 必須是有效數字"}), 400
    records = storage.get_records(user_id, date_str, limit=limit, offset=offset)
    return jsonify({"records": records, "count": len(records)})


@app.route("/records/<user_id>/<client_record_id>", methods=["PATCH"])
def update_record(user_id, client_record_id):
    require_user_access(user_id)
    existing = storage.get_record_by_client_record_id(user_id, client_record_id)
    if not existing:
        return jsonify({"error": "找不到飲食紀錄"}), 404

    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "缺少資料"}), 400
    try:
        foods = normalize_record_foods(data.get("foods"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    updated = {
        **existing,
        "foods": foods,
        **{
            f"total_{nutrient}": round(sum(food[nutrient] for food in foods), 2)
            for nutrient in EDITABLE_RECORD_NUTRIENTS
        },
    }
    saved = storage.update_record(updated)
    if not saved:
        return jsonify({"error": "找不到飲食紀錄"}), 404
    return jsonify({"message": "飲食紀錄已更新", "record": saved})


@app.route("/records/<user_id>/<client_record_id>", methods=["DELETE"])
def delete_record(user_id, client_record_id):
    require_user_access(user_id)
    deleted = storage.delete_record(user_id, client_record_id)
    if not deleted:
        return jsonify({"error": "找不到飲食紀錄"}), 404
    return jsonify({"message": "飲食紀錄已刪除", "record": deleted})


# ─── 4. History & Trends (PRD: 飲食趨勢回顧) ─────────────────
@app.route("/history/<user_id>", methods=["GET"])
def get_history(user_id):
    require_user_access(user_id)
    days = int(request.args.get("days", 7))
    return jsonify(build_history_response(storage, user_id, days))


@app.route("/healthy-food-recommend/<user_id>", methods=["GET"])
def healthy_food_recommend(user_id):
    require_user_access(user_id)
    params = {
        "budget": request.args.get("budget", 150),
        "lat": request.args.get("lat", 25.0338),
        "lng": request.args.get("lng", 121.5645),
        "radius_km": request.args.get("radius_km", 5),
        "category": request.args.get("category", "all"),
    }
    result = build_healthy_food_recommendations(storage, DISEASE_RULES, RESTAURANT_CATALOG, user_id, params, ALLERGEN_TAXONOMY)
    if not result:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404
    return jsonify(result)


@app.route("/map-food-recommend/<user_id>", methods=["GET"])
def map_food_recommend(user_id):
    require_user_access(user_id)
    params = {
        "budget": request.args.get("budget", 150),
        "lat": request.args.get("lat", 25.0338),
        "lng": request.args.get("lng", 121.5645),
        "radius_km": request.args.get("radius_km", 3),
        "category": request.args.get("category", "all"),
    }
    try:
        result = build_google_places_food_recommendations(storage, user_id, params)
    except GooglePlacesConfigError as e:
        return jsonify({"error": str(e), "places_enabled": False}), 503
    except GooglePlacesAPIError as e:
        return jsonify({"error": str(e), "places_enabled": True}), 502
    if not result:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404
    return jsonify(result)


@app.route("/restaurant/menu", methods=["POST"])
def get_restaurant_menu():
    """
    動態獲取餐廳詳細菜單。如果本地資料庫不存在，則調用爬蟲與 Gemini 動態分析。
    """
    data = request.get_json(silent=True) or {}
    restaurant_id = data.get("restaurant_id", "")
    name = data.get("name", "").strip()
    address = data.get("address", "").strip()
    
    if not name:
        return jsonify({"error": "缺少 restaurant name"}), 400

    # 1. 搜尋本地資料庫是否已有該店
    matched = None
    for r in RESTAURANT_CATALOG:
        if r.get("restaurant_id") == restaurant_id or r["name"].strip().lower() == name.lower():
            matched = r
            break

    if not matched:
        # 2. 本地不存在 ➔ 呼叫爬蟲與 Gemini 即時分析
        print(f"[Scraper] 即時線上擷取並生成 {name} 的菜單")
        enriched = enrich_restaurant_with_gemini(name, address or "台灣", "")
        
        # 建立新餐廳物件
        new_id = restaurant_id or f"scraped_{uuid.uuid4().hex[:6]}"
        matched = {
            "restaurant_id": new_id,
            "name": name,
            "lat": float(data.get("lat") or 25.0338),
            "lng": float(data.get("lng") or 121.5645),
            "address": address or "台灣",
            "phone": "",
            "open_hours": ["11:00-21:00"],
            "tags": ["動態擷取", "AI標記"],
            "price_level": 2,
            "items": enriched.get("items", [])
        }
        
        # 寫入本地 Catalog 與檔案存檔
        RESTAURANT_CATALOG.append(matched)
        catalog_path = os.path.join(BASE_DIR, "data", "restaurant_catalog.json")
        try:
            with open(catalog_path, "w", encoding="utf-8") as f:
                json.dump(RESTAURANT_CATALOG, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[!] 無法寫入本地 catalog 檔案: {e}")

    # 3. 對所有菜單項目進行醫學過濾與個人化偏好契合度評分
    user_id = data.get("user_id", "demo_user")
    user = storage.get_user(user_id)
    conditions = user.get("health_conditions", []) if user else []
    allergens = user.get("allergens", []) if user else []
    budget = int(data.get("budget", 150))
    target_calories = (user.get("daily_calorie_target", 2100) / 3) if user else 650
    
    recommended_items = []
    filtered_items = []
    
    for item in matched.get("items", []):
        candidate = {
            "label": item.get("item_id", item["name"]),
            "name_zh": item["name"],
            "gi": item.get("gi"),
            "allergens": item.get("allergens", []),
            "sodium": item.get("sodium"),
            "carbs": item.get("carbs"),
            "protein": item.get("protein"),
            "fat": item.get("fat"),
            "sugar": item.get("sugar"),
            "saturated_fat": item.get("saturated_fat"),
            "trans_fat": item.get("trans_fat"),
            "fiber": item.get("fiber"),
            "calcium": item.get("calcium"),
            "iron": item.get("iron"),
            "is_fried": item.get("is_fried"),
        }
        medical_risk = evaluate_medical_risk(candidate, conditions, allergens, DISEASE_RULES, ALLERGEN_TAXONOMY, user_profile=user)
        is_over_budget = item.get("price", 0) > budget
        is_blocked = medical_risk.get("action") == "BLOCK" or is_over_budget
        
        block_reasons = []
        if is_over_budget:
            block_reasons.append(f"超出預算 {budget} 元")
        block_reasons.extend(medical_risk.get("block_reasons", []))
        
        if is_blocked:
            filtered_items.append({
                "restaurant_id": matched["restaurant_id"],
                "restaurant_name": matched["name"],
                "item_name": item["name"],
                "reasons": block_reasons,
                "price": item.get("price", 0),
                "medical_risk": medical_risk,
            })
        else:
            # 計算個人化契合度分數
            base_score = 92 if medical_risk.get("action") == "ALLOW" else 78
            item_cal = float(item.get("calories", 0) or 0)
            cal_diff = abs(target_calories - item_cal)
            cal_score = max(0, 10 - int(cal_diff / 40))
            
            prot = float(item.get("protein", 0) or 0)
            prot_bonus = 5 if prot >= 18 else 0
            
            sod = float(item.get("sodium", 0) or 0)
            sod_bonus = 3 if sod <= 600 else -5 if sod >= 1000 else 0
            
            match_score = min(99, max(1, base_score + cal_score + prot_bonus + sod_bonus))
            
            reasons = []
            if medical_risk.get("caution_reasons"):
                reasons.extend(medical_risk["caution_reasons"])
            else:
                reasons.append(f"符合單餐預算 {budget} 元")
                reasons.append(f"熱量契合個人單餐目標 ({int(target_calories)} kcal)")
            if prot >= 18:
                reasons.append("高蛋白質補給")
            if sod <= 600:
                reasons.append("低鈉好選擇")
                
            recommended_items.append({
                "restaurant_id": matched["restaurant_id"],
                "restaurant_name": matched["name"],
                "restaurant_lat": matched["lat"],
                "restaurant_lng": matched["lng"],
                "address": matched.get("address", ""),
                "distance_km": 0.1,
                "tags": matched["tags"],
                "item_id": item.get("item_id", item["name"]),
                "item_name": item["name"],
                "price": item.get("price", 0),
                "calories": item.get("calories", 0),
                "protein": item.get("protein", 0),
                "carbs": item.get("carbs", 0),
                "fat": item.get("fat", 0),
                "sodium": item.get("sodium", 0),
                "gi": item.get("gi"),
                "match_score": match_score,
                "reasons": reasons,
                "medical_risk": medical_risk,
            })

    # 按契合度高低排序，精準截取前 3~5 項推薦品項
    recommended_items.sort(key=lambda x: x["match_score"], reverse=True)
    top_recommended = recommended_items[:5]

    return jsonify({
        "restaurant_id": matched["restaurant_id"],
        "name": matched["name"],
        "recommended_items": top_recommended,
        "filtered_items": filtered_items
    })


@app.route("/map-food-recommend/<user_id>/restaurant-summary", methods=["POST"])
def map_food_restaurant_summary(user_id):
    require_user_access(user_id)
    user = storage.get_user(user_id)
    if not user:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404

    data = request.get_json(silent=True) or {}
    restaurant = data.get("restaurant") or {}
    if not restaurant.get("name"):
        return jsonify({"error": "缺少 restaurant.name"}), 400
    budget = data.get("budget") or 150
    category = data.get("category") or "all"
    try:
        nutrition_progress = build_daily_nutrition_progress(storage, user_id, user)
        summary = build_restaurant_ai_summary(
            restaurant,
            budget,
            category,
            user.get("health_conditions", []),
            nutrition_progress,
            DISEASE_RULES,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        return jsonify({"error": f"Gemini 店家摘要失敗: HTTP {status_code}"}), 502
    return jsonify({"summary": summary}), 200


# ─── 6. BMR/TDEE Calculator (PRD: 動態計算) ─────────────────
@app.route("/calculate/bmr", methods=["POST"])
def calc_bmr():
    data = request.get_json()
    return jsonify(build_bmr_response(data))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
