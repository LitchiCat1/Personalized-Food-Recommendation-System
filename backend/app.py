"""
NutriLens Backend — Flask API
PRD-aligned: Gemini Vision food recognition + nutrition analysis + user management + recommendations
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
from services.auth_service import AuthError, is_auth_required, verify_supabase_user
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
from services.profile_service import build_bmr_response, build_user_profile
from services.recommend_service import build_recommendation_response
from services.restaurant_ai_service import build_restaurant_ai_summary
from services.robust_restaurant_scraper_service import scrape_and_enrich_restaurant
from services.vision_food_service import (

    build_vision_food_response,
    call_gemini_food_recognition_with_rotation,
)


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
_mem_recommendation_feedback = []
storage = StorageRepository(db, USE_MONGO, _mem_users, _mem_records, _mem_custom_foods, _mem_recommendation_feedback, pg_conn=pg_conn)

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
def ensure_user_profile(user_id: str):
    user = storage.get_user(user_id)
    if not user:
        user = {
            "user_id": user_id,
            "name": "探索者",
            "gender": "male",
            "height": 175.0,
            "weight": 70.0,
            "age": 28,
            "activity_level": "輕度活動 (每週運動 1-3 天)",
            "activity_multiplier": 1.375,
            "bmi": 22.9,
            "bmr": 1650,
            "tdee": 2268,
            "daily_calorie_target": 2000,
            "health_conditions": [],
            "allergens": [],
            "diet_type": "均衡飲食"
        }
        storage.upsert_user(user)
    return user


@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    require_user_access(user_id)
    user = ensure_user_profile(user_id)
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
@app.route("/record", methods=["POST"])
def add_record():
    data = request.get_json()
    if not data:
        return jsonify({"error": "缺少資料"}), 400
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))
    if not data.get("client_record_id"):
        data["client_record_id"] = f"server_record_{uuid.uuid4().hex}"

    record = {
        "user_id": data.get("user_id"),
        "client_record_id": data.get("client_record_id"),
        "timestamp": data.get("timestamp", datetime.now(timezone.utc).replace(tzinfo=None).isoformat()),
        "meal_type": data.get("meal_type", "午餐"),
        "foods": data.get("foods", []),
        "total_calories": data.get("total_calories", 0),
        "total_protein": data.get("total_protein", 0),
        "total_carbs": data.get("total_carbs", 0),
        "total_fat": data.get("total_fat", 0),
        "total_sodium": data.get("total_sodium", 0),
        "total_fiber": data.get("total_fiber", 0),
        "source": data.get("source", "camera"),  # camera | manual
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
    records = storage.get_records(user_id, date_str, limit=50)
    return jsonify({"records": records, "count": len(records)})


# ─── 4. History & Trends (PRD: 飲食趨勢回顧) ─────────────────
@app.route("/history/<user_id>", methods=["GET"])
def get_history(user_id):
    require_user_access(user_id)
    days = int(request.args.get("days", 7))
    return jsonify(build_history_response(storage, user_id, days))


# ─── 5. Recommendations (PRD: 個人化雙軌推薦引擎) ────────────
@app.route("/recommend/<user_id>", methods=["GET"])
def recommend(user_id):
    """
    雙軌推薦:
    1. 安全過濾層: 根據疾病禁忌排除不安全食物
    2. 口味排序層: 餘弦相似度 (placeholder, 目前用隨機分數)
    """
    require_user_access(user_id)
    ensure_user_profile(user_id)
    result = build_recommendation_response(storage, NUTRITION_DB, TFDA_DB, DISEASE_RULES, user_id, ALLERGEN_TAXONOMY)
    if not result:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404
    return jsonify(result)


@app.route("/healthy-food-recommend/<user_id>", methods=["GET"])
def healthy_food_recommend(user_id):
    require_user_access(user_id)
    ensure_user_profile(user_id)
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
    ensure_user_profile(user_id)
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


@app.route("/map-food-recommend/<user_id>/restaurant-summary", methods=["POST"])
def map_food_restaurant_summary(user_id):
    require_user_access(user_id)
    user = ensure_user_profile(user_id)
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


@app.route("/recommend/<user_id>/feedback", methods=["POST"])
def create_recommendation_feedback(user_id):
    require_user_access(user_id)
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in {"accepted", "skipped", "disliked"}:
        return jsonify({"error": "action 必須是 accepted、skipped 或 disliked"}), 400

    item = data.get("item") or {}
    item_label = item.get("label") or data.get("item_label")
    if not item_label:
        return jsonify({"error": "缺少 item.label"}), 400

    feedback_doc = {
        "user_id": user_id,
        "action": action,
        "item_label": item_label,
        "item_name": item.get("name_zh") or item.get("item_name") or data.get("item_name"),
        "item_source": item.get("source") or data.get("item_source"),
        "item": item,
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }
    saved = storage.insert_recommendation_feedback(feedback_doc)
    return jsonify({"message": "推薦回饋已儲存", "feedback": saved}), 201


@app.route("/recommend/<user_id>/feedback", methods=["GET"])
def list_recommendation_feedback(user_id):
    require_user_access(user_id)
    limit = min(int(request.args.get("limit", 100)), 500)
    feedback = storage.get_recommendation_feedback(user_id, limit=limit)
    return jsonify({"feedback": feedback, "count": len(feedback)})


# ─── 6. BMR/TDEE Calculator (PRD: 動態計算) ─────────────────
@app.route("/calculate/bmr", methods=["POST"])
def calc_bmr():
    data = request.get_json()
    return jsonify(build_bmr_response(data))


# ─── 7. Anti-blocking Scraper & AI Menu Enrichment Endpoint ───────
@app.route("/restaurant/search", methods=["GET"])
def search_restaurant():
    """
    模糊搜尋餐廳名稱或標籤
    ?q=餐廳名稱
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"restaurants": []})

    q_lower = q.lower()
    matches = []
    for r in RESTAURANT_CATALOG:
        if q_lower in r["name"].lower() or any(q_lower in tag.lower() for tag in r.get("tags", [])):
            matches.append(r)

    return jsonify({"restaurants": matches})


@app.route("/restaurant/scrape-and-enrich", methods=["POST"])
def api_scrape_and_enrich_restaurant():
    """
    接收餐廳名稱、地址、可選的菜單網址與菜單文字，結合抗封鎖 HTTP 請求與 Gemini AI
    自動將店家菜單寫入或更新到系統資料庫。
    """
    data = request.get_json(silent=True) or {}
    restaurant_name = data.get("restaurant_name") or data.get("name")
    if not restaurant_name:
        return jsonify({"error": "缺少 restaurant_name"}), 400

    address = data.get("address", "台北市信義區")
    lat = float(data.get("lat", 25.0338))
    lng = float(data.get("lng", 121.5645))
    menu_url = data.get("menu_url", "")
    menu_text = data.get("menu_text", "")

    result = scrape_and_enrich_restaurant(restaurant_name, address, lat, lng, menu_url, menu_text)
    
    # Reload RESTAURANT_CATALOG in memory
    global RESTAURANT_CATALOG
    RESTAURANT_CATALOG = load_restaurant_catalog(BASE_DIR)
    
    return jsonify({
        "message": "餐廳與菜單已成功擷取並由 AI 完成營養標註並寫入資料庫！",
        "restaurant": result,
        "total_catalog_restaurants": len(RESTAURANT_CATALOG)
    }), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)

