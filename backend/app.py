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
from services.app_time_service import app_now
from services.auth_service import AuthError, is_auth_required, is_supabase_auth_configured, verify_supabase_user
from services.rate_limit_service import RateLimitExceeded, build_limiter
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
    probe_gemini_models,
    scale_nutrition_per_100g,
)
from services.nutrition_progress_service import build_daily_nutrition_progress, build_nutrition_goal_types, calculate_daily_targets_with_basis, round_targets_for_display
from services.nutrient_service import NUTRITION_FIELDS, get_nutrient_value
from services.profile_service import ACTIVITY_LEVELS, build_bmr_response, build_user_profile
from services.restaurant_ai_service import build_restaurant_ai_summary
from services.vision_food_service import (
    build_vision_food_response,
    call_gemini_food_recognition_with_rotation,
)
from services.robust_restaurant_scraper_service import enrich_restaurant_with_gemini, parse_menu_image_with_gemini
from services.medical_risk_service import MEALS_PER_DAY, evaluate_medical_risk, normalize_number, rule_threshold_conflicts
from services.google_places_service import fetch_google_places_restaurants
from services.venue_index_service import VenueIndexUnavailable, index_nearby_venues


load_local_env()

BASE_DIR = os.path.dirname(__file__)

def connect_postgres(url: str):
    """連 Postgres，SSL 依主機決定。

    先前寫死 sslmode="require"，所以只連得上 Supabase 這種雲端資料庫；
    本機的 Postgres 預設沒開 SSL，會直接被拒絕，等於無法在本地端建資料庫。
    網址自己指定 sslmode 時以它為準。
    """
    if "sslmode=" in url:
        return psycopg2.connect(url)
    local = any(host in url for host in ("@localhost", "@127.0.0.1", "@host.docker.internal", "@db:"))
    return psycopg2.connect(url, sslmode="prefer" if local else "require")


pg_conn = None
database_url = os.environ.get("DATABASE_URL")
if database_url:
    try:
        pg_conn = connect_postgres(database_url)
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
# 店家菜單快取可以放另一個 Supabase／Postgres；沒設定就跟其他資料同一個
menu_pg_conn = None
menu_database_url = os.environ.get("MENU_DATABASE_URL")
if menu_database_url:
    try:
        menu_pg_conn = connect_postgres(menu_database_url)
        menu_pg_conn.autocommit = True
        print("[OK] Menu cache PostgreSQL connected")
    except Exception as e:
        menu_pg_conn = None
        print(f"[WARN] Menu cache PostgreSQL unavailable, falling back to main database - {e}")

storage = StorageRepository(
    db, USE_MONGO, _mem_users, _mem_records, _mem_custom_foods,
    pg_conn=pg_conn, menu_pg_conn=menu_pg_conn,
)

app = Flask(__name__)

# CORS 先前是完全開放的：任何網站都能從瀏覽器呼叫這個後端，包括會花錢的
# 那幾條路由。預設只允許自己的前端，要多開就用 ALLOWED_ORIGINS 明確列出。
def _normalise_origin(value: str) -> str:
    """接受 `example.com` 或 `https://example.com` 都算數。

    Render 的 RENDER_EXTERNAL_HOSTNAME 給的是不帶協定的主機名，而 CORS 比對的
    是完整 origin。不補協定的話，貼上主機名看起來設定好了，實際仍會被擋。
    """
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    local = value.startswith(("localhost", "127.0.0.1"))
    return f"{'http' if local else 'https'}://{value}"


_allowed_origins = [
    normalised
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if (normalised := _normalise_origin(origin))
]
if _allowed_origins:
    CORS(app, origins=_allowed_origins, supports_credentials=True)
    print(f"[OK] CORS 只放行：{', '.join(_allowed_origins)}")
else:
    # 沒設定時放行本機開發，外加本專案自己的前端。列成具名清單而不是萬用字元：
    # 「任何 onrender.com」等於誰都能在 Render 上架個網站來打這個後端。
    CORS(app, origins=[
        "http://localhost:8081",
        "http://localhost:19006",
        "http://127.0.0.1:8081",
        "https://nutrilens-frontend-32ob.onrender.com",
        "https://personalized-food-recommendation-frontend-rt1v.onrender.com",
    ])
    print(
        "[WARN] ALLOWED_ORIGINS 未設定，改用內建的前端清單。"
        "新部署的前端會拿到新網址，不在清單內就會被 CORS 擋掉——"
        "請把前端網址設進 ALLOWED_ORIGINS。"
    )

# 會呼叫 Gemini / Google Places 的路由要限流，那些都是按次計費的
_paid_api_limiter = build_limiter("RATE_LIMIT_PAID_CALLS", 12)
_general_limiter = build_limiter("RATE_LIMIT_GENERAL_CALLS", 120)


def _client_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() or request.remote_addr or "unknown")


def enforce_rate_limit(limiter, bucket: str) -> None:
    limiter.check(f"{bucket}:{_client_key()}")


@app.errorhandler(RateLimitExceeded)
def handle_rate_limit(error):
    response = jsonify({"error": str(error)})
    response.headers["Retry-After"] = str(error.retry_after)
    return response, error.status_code


def require_authenticated_user() -> str | None:
    """只要求「登入過」，不綁定特定 user_id。

    給不屬於單一使用者、但會花錢的路由用（菜單分析、營養標示辨識、
    金鑰診斷）。先前這幾條完全不驗證，任何人都能拿它們燒光額度。
    """
    if not is_auth_required():
        return None
    return get_request_user_id()


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


APP_VERSION = "v0.0.9"
STARTED_AT = app_now().isoformat()


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
        "menu_cache_database": "separate" if menu_pg_conn is not None else ("shared" if pg_conn is not None else "memory"),
        "cached_restaurant_menus": storage.count_restaurant_menus(),
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
        # 部署後可以直接從 /health 看出線上跑的是哪一版，不用靠路由存不存在來猜。
        # RENDER_GIT_BRANCH / RENDER_GIT_COMMIT 由 Render 自動注入。
        "deployed_branch": os.environ.get("RENDER_GIT_BRANCH") or "local",
        "deployed_commit": (os.environ.get("RENDER_GIT_COMMIT") or "local")[:7],
        "app_version": APP_VERSION,
        "started_at": STARTED_AT,
    })


@app.route("/disease-rules", methods=["GET"])
def disease_rules():
    return jsonify(build_disease_rules_response(DISEASE_RULES))


@app.route("/medical-metadata", methods=["GET"])
def medical_metadata():
    # 兩套門檻不一致時要看得見。寬的那條永遠不會生效，審閱者在規則檔上
    # 簽核的數字可能跟系統實際執行的不同——這種事不該只存在於原始碼裡。
    conflicts = rule_threshold_conflicts(DISEASE_RULES)
    return jsonify({
        **build_medical_metadata_response(DISEASE_RULES, ALLERGEN_TAXONOMY),
        "activity_levels": ACTIVITY_LEVELS,
        "threshold_conflicts": conflicts,
        "threshold_conflict_note": (
            f"{len(conflicts)} 項營養素在規則檔與程式公式之間數字不一致，"
            "實際生效的是較嚴的那個。需要臨床人員確認要採用哪一邊。"
            if conflicts else None
        ),
    })


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
    require_authenticated_user()
    enforce_rate_limit(_paid_api_limiter, "ocr")
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
        # 用本地時間，讓 timestamp 的日期前綴＝使用者的當天（掃描紀錄沒有帶 timestamp）
        return app_now().isoformat()
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
    user = storage.get_user(user_id) or {}
    daily = calculate_daily_targets_with_basis(user)
    return jsonify({
        "records": records,
        "count": len(records),
        "nutrition_targets": round_targets_for_display(daily["targets"]),
        # 每日熱量先前在畫面上有三個版本（tdee、使用者自填、疾病目標）互相打架，
        # 而且沒有任何說明。basis 說明現在生效的是哪一個、依據是什麼。
        "nutrition_target_basis": daily["basis"],
        # 目標值本身看不出方向。蛋白質對一般人是「至少吃到」，對慢性腎臟病
        # 是「不可超過」，前端沒有這個就只能猜，超標也標不出來。
        "nutrition_goal_types": build_nutrition_goal_types(user),
    })


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


# ─── 3.5 一週測試資料（我的 → 開發者工具） ──────────────────
def _venue_search_params(data: dict) -> dict:
    return {
        "budget": data.get("budget", 150),
        "lat": data.get("lat", 25.0338),
        "lng": data.get("lng", 121.5645),
        "radius_km": data.get("radius_km", 3),
        "category": data.get("category", "all"),
    }


@app.route("/restaurants/index/<user_id>", methods=["POST"])
def index_nearby_restaurants(user_id):
    """把附近店家的菜單建檔，推薦才能逐道菜比對疾病禁忌與過敏原。"""
    require_user_access(user_id)
    data = request.get_json(silent=True) or {}
    try:
        summary = index_nearby_venues(
            storage,
            {**_venue_search_params(data), "limit": data.get("limit", 20)},
            fetch_google_places_restaurants,
            enrich_restaurant_with_gemini,
        )
    except VenueIndexUnavailable as error:
        return jsonify({"error": str(error)}), 409
    return jsonify({"message": f"已建檔 {summary['analysed']} 家店", **summary})


@app.route("/health/gemini", methods=["GET"])
def gemini_model_diagnostics():
    require_authenticated_user()
    enforce_rate_limit(_paid_api_limiter, "gemini-probe")
    """每把金鑰實際能用哪些模型。設定的清單對不上權限時只會看到一堆 404。"""
    try:
        generate = request.args.get("generate") in {"1", "true", "yes"}
        return jsonify(probe_gemini_models(generate=generate))
    except ValueError as error:
        return jsonify({"error": str(error)}), 503


@app.route("/restaurants/index/<user_id>", methods=["GET"])
def list_nearby_restaurant_index(user_id):
    """列出建檔過的店家。

    先前只回得出一個數字，建了哪些店、資料多舊、有沒有營業時段，
    都只能翻伺服器 log 才看得到。
    """
    require_user_access(user_id)
    venues = []
    for doc in storage.list_restaurant_menus(limit=200):
        age = storage.restaurant_menu_age_days(doc)
        venues.append({
            "name": doc.get("name", ""),
            "address": doc.get("address", ""),
            "items": len(doc.get("items") or []),
            "has_opening_hours": bool(doc.get("opening_periods")),
            "business_status": doc.get("business_status", ""),
            "age_days": round(age, 1) if age is not None else None,
            "stale": storage.restaurant_menu_is_stale(doc),
        })
    venues.sort(key=lambda venue: venue["name"])
    return jsonify({
        "count": len(venues),
        "stale": sum(1 for venue in venues if venue["stale"]),
        "without_opening_hours": sum(1 for venue in venues if not venue["has_opening_hours"]),
        "venues": venues,
    })


@app.route("/restaurants/index/<user_id>", methods=["DELETE"])
def clear_nearby_restaurant_index(user_id):
    """清空店家菜單快取，讓建檔可以用目前的規則重來一次。"""
    require_user_access(user_id)
    removed = storage.clear_restaurant_menus()
    return jsonify({"message": f"已清除 {removed} 家店的菜單檔案", "removed": removed})


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
    # 先擋未登入（401），再限流（429），最後才檢查身分歸屬——順序反了會讓
    # 匿名呼叫拿到 400、限流也永遠輪不到。
    require_authenticated_user()
    enforce_rate_limit(_paid_api_limiter, "menu")
    # 這條路徑會用 user_id 載入對方的疾病與過敏原來篩菜單，所以有帶 user_id
    # 就必須是本人：否則任何登入者都能填別人的 id，再從推薦／排除清單的差異
    # 反推出對方有哪些疾病。沒帶就用登入者自己，不再退回共用的 demo_user。
    if data.get("user_id"):
        require_user_access(data["user_id"])
    restaurant_id = data.get("restaurant_id", "")
    name = data.get("name", "").strip()
    address = data.get("address", "").strip()
    # 這條路徑收到的 lat/lng 是「店家」的座標，不是使用者的，算不出距離。
    # 之前寫死 0.1 km，等於對每一家店都謊報「就在附近」。呼叫端已經從
    # 推薦清單拿到真實距離，有帶就照實回傳，沒帶就不給這個欄位。
    try:
        client_distance_km = float(data["distance_km"])
    except (KeyError, TypeError, ValueError):
        client_distance_km = None
    raw_menu_image = data.get("menu_image", "")
    if raw_menu_image is None:
        menu_image = ""
    elif isinstance(raw_menu_image, str):
        menu_image = raw_menu_image.strip()
    else:
        return jsonify({"error": "menu_image 必須是 Base64 圖片字串"}), 400
    
    if not name:
        return jsonify({"error": "缺少 restaurant name"}), 400

    # 1. 先看資料庫裡建檔過的菜單，再退回內建目錄
    cached = storage.get_restaurant_menu(name)
    matched = None
    if cached and cached.get("items") and not storage.restaurant_menu_is_stale(cached):
        matched = {
            "restaurant_id": restaurant_id or cached.get("venue_key", name),
            "name": cached.get("name", name),
            "lat": cached.get("lat") or 0,
            "lng": cached.get("lng") or 0,
            "address": cached.get("address", address),
            "phone": "",
            "open_hours": [],
            "tags": ["已建檔菜單"],
            "price_level": 2,
            "items": cached["items"],
        }
    for r in [] if matched else RESTAURANT_CATALOG:
        if r.get("restaurant_id") == restaurant_id or r["name"].strip().lower() == name.lower():
            matched = r
            break

    menu_recognition = None
    if menu_image:
        print(f"[Scraper] 使用 Gemini Vision AI 辨識 {name} 的實體菜單圖片")
        enriched = parse_menu_image_with_gemini(menu_image, name)
        menu_recognition = {
            key: enriched[key]
            for key in ("recognition_status", "recognition_error", "recognition_model")
            if key in enriched
        }
        recognized_items = enriched.get("items", [])
        if matched:
            # Do not destroy a previously known menu when a transient Vision
            # failure, quota error, or unreadable photo returns zero items.
            if recognized_items:
                matched["items"] = recognized_items
        else:
            new_id = restaurant_id or f"scraped_{uuid.uuid4().hex[:6]}"
            matched = {
                "restaurant_id": new_id,
                "name": name,
                "lat": float(data.get("lat") or 25.0338),
                "lng": float(data.get("lng") or 121.5645),
                "address": address or "台灣",
                "phone": "",
                "open_hours": ["11:00-21:00"],
                "tags": ["實體菜單辨識", "AI標記"],
                "price_level": 2,
                "items": recognized_items
            }
            storage.save_restaurant_menu(name, recognized_items, venue={
                "address": address or "台灣",
                "lat": float(data.get("lat") or 25.0338),
                "lng": float(data.get("lng") or 25.0338),
            })
    elif not matched:
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
        
        # 存進資料庫的菜單快取，不要改動載入時的目錄。
        # 那個目錄是共用的模組層級 list，一邊被請求讀一邊被 append 是資料競爭
        # （伺服器現在是多執行緒的），而寫回 JSON 檔在 Render 上重啟就沒了。
        storage.save_restaurant_menu(name, matched["items"], venue={
            "address": matched["address"],
            "lat": matched["lat"],
            "lng": matched["lng"],
        })

    # 3. 對所有菜單項目進行醫學過濾與個人化偏好契合度評分
    #
    # 沒有 profile 就不能篩。先前這裡退回共用的 "demo_user"（storage 還會在
    # 正式資料庫自動建一個 0 疾病 0 過敏的帳號），等於把安全過濾靜默關掉，
    # 而畫面上看起來一切正常。寧可回錯誤，也不要回一份沒篩過的推薦。
    user_id = data.get("user_id") or get_request_user_id() or ""
    user = storage.get_user(user_id)
    if not user:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404
    conditions = user.get("health_conditions", []) or []
    allergens = user.get("allergens", []) or []
    budget = int(data.get("budget", 150))
    target_calories = (normalize_number(user.get("daily_calorie_target")) or 2100) / MEALS_PER_DAY
    
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
            "is_fried": item.get("is_fried"),
        }
        medical_risk = evaluate_medical_risk(candidate, conditions, allergens, DISEASE_RULES, ALLERGEN_TAXONOMY, user_profile=user)
        is_over_budget = item.get("price", 0) > budget

        block_reasons = []
        if is_over_budget:
            block_reasons.append(f"超出預算 {budget} 元")
        block_reasons.extend(medical_risk.get("block_reasons", []))

        # 先前這裡是 medical_risk.get("action") == "BLOCK"，但 evaluate_medical_risk
        # 從來沒有回傳過 action 這個鍵，所以整條疾病過濾在這個路徑上是死的：
        # 只有超出預算會被擋，算好的 block_reasons 接著被丟掉。
        # healthy_food_service 一直都是用 block_reasons 判斷的。
        is_blocked = bool(block_reasons)
        
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
            # 同一個不存在的鍵，這裡讓分數永遠是 78。
            base_score = 92 if medical_risk["is_safe"] and not medical_risk["has_caution"] else 78
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
                **({"distance_km": client_distance_km} if client_distance_km is not None else {}),
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
        "filtered_items": filtered_items,
        "menu_recognition": menu_recognition,
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
    if debug:
        app.run(debug=True, host="0.0.0.0", port=port)
    else:
        # Flask 內建伺服器是單執行緒的開發用伺服器，它自己也會警告
        # 「Do not use it in a production deployment」。正式環境用 waitress。
        try:
            from waitress import serve

            print(f"[OK] Serving with waitress on port {port}")
            serve(app, host="0.0.0.0", port=port, threads=8)
        except ImportError:
            print("[WARN] waitress 未安裝，退回 Flask 開發伺服器（僅適合本機）")
            app.run(debug=False, host="0.0.0.0", port=port)
