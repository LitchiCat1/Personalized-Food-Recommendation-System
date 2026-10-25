"""
NutriLens Backend — Flask API
PRD-aligned: Gemini Vision food recognition + nutrition analysis + user management
"""

import hmac
import ipaddress
import json
import math
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import BadRequest, HTTPException, InternalServerError, RequestEntityTooLarge
from werkzeug.security import safe_join
from repositories.auth_repository import AuthRepository
from repositories.database import DatabaseUnavailable, open_database
from repositories.sqlite_db import resolve_database_path, virtualized_appdata_problem
from repositories.storage import StorageRepository
from services.app_time_service import app_now
from services.auth_service import AuthError, is_auth_required, normalize_email, sign_in, sign_out, sign_up, verify_access_token
from services.rate_limit_service import RateLimitExceeded, build_limiter
from services.disease_rule_service import (
    build_disease_rules_response,
    build_medical_metadata_response,
    load_allergen_taxonomy,
    load_disease_rules,
    normalize_condition_ids,
)
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
from services.profile_service import (
    ACTIVITY_LEVELS,
    DIET_TYPES,
    PROFILE_LIMITS,
    build_bmr_response,
    build_user_profile,
    normalize_stored_user,
)
from services.restaurant_ai_service import build_restaurant_ai_summary
from services.vision_food_service import (
    build_vision_food_response,
    call_gemini_food_recognition_with_rotation,
)
from services.robust_restaurant_scraper_service import enrich_restaurant_with_gemini, parse_menu_image_with_gemini
from services.medical_risk_service import (
    MEALS_PER_DAY,
    effective_meal_limits,
    evaluate_medical_risk,
    normalize_number,
    resolve_user_energy_and_weight,
    rule_threshold_conflicts,
)
from services.google_places_service import fetch_google_places_restaurants
from services.venue_index_service import VenueIndexUnavailable, index_nearby_venues


load_local_env()

BASE_DIR = os.path.dirname(__file__)

# ─── 資料庫 ──────────────────────────────────────────────────
# Render 設了 DATABASE_URL：用 Supabase 的 Postgres，部署和休眠都不會清空資料。
# 本機沒設：帳號、健康檔案、飲食紀錄、店家菜單都存在一個 SQLite 檔。位置見
# sqlite_db.py，可以用 DATABASE_PATH 改；設成空字串就不用資料庫，資料只存在記憶體。
sql_db = None
if not os.environ.get("DATABASE_URL", "").strip():
    # 開檔之前就檢查：開了就會在錯的那一邊先建出一個空資料庫
    _appdata_problem = virtualized_appdata_problem(resolve_database_path())
    if _appdata_problem:
        print(f"[ERROR] {_appdata_problem}")
        sys.exit(1)
try:
    sql_db, database_label = open_database()
    if sql_db is not None:
        print(f"[OK] Database: {database_label}")
except DatabaseUnavailable as e:
    # 設了雲端資料庫卻連不上：不能退回記憶體，不然看起來正常、資料其實沒存。
    # Render 的部署會失敗，繼續跑上一版。
    print(f"[ERROR] {e}")
    sys.exit(1)
except Exception as e:
    # SQLite 開不起來也要停下，跟 Postgres 連不上一樣。先前印一行 WARN 就退回記憶體：
    # 註冊、記錄看起來都正常，後端一重開就全部消失。真的只要記憶體就明確設 DATABASE_PATH=。
    print(f"[ERROR] 打不開 SQLite 資料庫 {resolve_database_path()}：{e}")
    print("        檔案可能損毀或沒有寫入權限。請從備份還原這個檔案（見 backend/scripts/backup_db.py），")
    print("        或用 DATABASE_PATH 指到其他位置；只想暫時存在記憶體（重開就清空）請設 DATABASE_PATH= 空字串。")
    sys.exit(1)
# 路徑裡有 Windows 使用者名稱，/health 只給這台電腦自己看
database_path = sql_db.path if sql_db is not None and sql_db.dialect == "sqlite" else None

# ─── Optional MongoDB (only when SQLite is off) ──────────────
mongo = None
USE_MONGO = False
db = None
if sql_db is None:
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

storage = StorageRepository(db, USE_MONGO, _mem_users, _mem_records, _mem_custom_foods, sql=sql_db)
# 帳號跟著資料庫走。沒有資料庫時帳號只存在記憶體，重啟就要重新註冊。
auth_repo = AuthRepository(sql_db)
if sql_db is None:
    print("[WARN] 帳號存在記憶體裡，後端重啟後要重新註冊")

app = Flask(__name__)

# 一張 8 MB 的照片轉成 Base64 約 10.7 MB，再加上 JSON。先前沒有上限，
# 一個超大的請求會整個讀進記憶體才被拒絕。
MAX_REQUEST_BYTES = 12 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_error):
    return jsonify({"error": "上傳的資料太大了，照片請小於 8 MB。"}), 413


@app.errorhandler(InternalServerError)
def handle_internal_error(_error):
    # 沒接住的例外。先前回的是 Flask 的 HTML 錯誤頁，前端解析不了；
    # 完整的 traceback 照樣會印在後端視窗，這裡不把細節回給前端。
    return jsonify({"error": "伺服器發生錯誤，請稍後再試。"}), 500


@app.errorhandler(HTTPException)
def handle_http_error(error):
    # 405、415、壞掉的 JSON 這類 Flask 自己丟的錯誤，原本也是 HTML 錯誤頁
    response = jsonify({"error": error.description})
    response.status_code = error.code or 500
    for name, value in error.get_headers():
        if name.lower() != "content-type":
            response.headers[name] = value  # 例如 405 的 Allow
    return response


def json_body() -> dict:
    """請求內容的 JSON 物件，沒有內容就是空物件。

    先前各路由各自 request.get_json()：送陣列或字串時 data.get() 直接 500，
    沒帶 JSON 時 Flask 回 415 的 HTML 錯誤頁。
    """
    if not request.get_data(cache=True):
        return {}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("請求內容必須是 JSON 物件。")
    return data


def _is_loopback(address: str | None) -> bool:
    try:
        ip = ipaddress.ip_address((address or "").strip())
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


# cloudflared 跑在這台電腦上，轉送進來的請求 remote_addr 也是 127.0.0.1，
# 但一定帶著這些標頭。有它們就是從外面經 tunnel 進來的。
_PROXY_HEADERS = ("Cf-Connecting-Ip", "X-Forwarded-For", "Forwarded")
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def is_local_request() -> bool:
    """請求是不是從執行後端的這台電腦本身發出的。

    只看來源位址和轉送標頭還不夠：Tailscale Funnel 也跑在這台電腦上，轉進來的
    請求來源一樣是 127.0.0.1，卻不保證會加轉送標頭。外面的人打的一定是 tunnel
    的網域（例如 *.ts.net），所以 Host 也要是這台電腦自己的名字才算。
    """
    host = (urlparse(f"//{request.host}").hostname or "").lower()
    return (
        _is_loopback(request.remote_addr)
        and not any(request.headers.get(h) for h in _PROXY_HEADERS)
        and host in _LOCAL_HOSTNAMES
    )


def client_ip() -> str:
    """真正的來源 IP。

    先前直接採信 X-Forwarded-For，那是請求方自己可以填的：每次換一個值，
    以 IP 計的限流就形同虛設。現在只有在請求是本機的 cloudflared 轉送時，
    才採用 Cloudflare 填的 Cf-Connecting-Ip（Cloudflare 會覆寫請求方送的同名標頭）。
    """
    remote = request.remote_addr or "unknown"
    if _is_loopback(remote):
        forwarded = (request.headers.get("Cf-Connecting-Ip") or "").strip()
        if forwarded:
            return forwarded
        # Tailscale Funnel：tailscaled（1.104 的 ipn/ipnlocal/serve.go）先刪掉請求方帶的
        # Tailscale-Funnel-Request 再設成 ?1，並用 Header.Set 把 X-Forwarded-For 覆寫成
        # 連線的來源位址，請求方填的值傳不進來。不採用的話，所有 Funnel 訪客共用
        # 127.0.0.1 的額度，一個人連打就讓全部人登入不了。
        if request.headers.get("Tailscale-Funnel-Request") == "?1":
            forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
            if forwarded and "," not in forwarded:
                return forwarded
        # 其他情況的 X-Forwarded-For 不採用：要是 tunnel 只是把請求方自己填的值原樣
        # 轉過來，每次換一個值就能繞過以 IP 計的限流。
    return remote


def require_local_request(action: str) -> None:
    if not is_local_request():
        raise AuthError(f"{action}只能在執行後端的那台電腦上操作。", 403)

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
        "http://localhost:8083",
        "http://localhost:19006",
        "http://127.0.0.1:8081",
        "http://127.0.0.1:8083",
    ])
    print("[OK] CORS 放行本機的開發伺服器；其他網址請設 ALLOWED_ORIGINS")


@app.after_request
def allow_other_ports_on_this_machine(response):
    """用區網 IP 或 VPN 位址開 8081 的開發伺服器時，網頁跟後端是同一台電腦、不同埠。

    內建清單只有 localhost，換成 192.168.x.x 開網站就會被 CORS 擋掉。主機名稱
    跟後端被連的那個一樣，就代表是同一台電腦上的網站，放行。
    """
    origin = request.headers.get("Origin")
    if not origin or response.headers.get("Access-Control-Allow-Origin"):
        return response
    if urlparse(origin).hostname != urlparse(f"//{request.host}").hostname:
        return response
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers.add("Vary", "Origin")
    if request.method == "OPTIONS":
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = (
            request.headers.get("Access-Control-Request-Headers") or "Authorization, Content-Type"
        )
    return response

# 會呼叫 Gemini / Google Places 的路由要限流，那些都是按次計費的
_paid_api_limiter = build_limiter("RATE_LIMIT_PAID_CALLS", 12)
_general_limiter = build_limiter("RATE_LIMIT_GENERAL_CALLS", 120)


def _client_key() -> str:
    # 登入過就以帳號計。學校 Wi-Fi 或 tunnel 後面整班共用同一個對外 IP，
    # 以 IP 計的話一個人用完額度，全班都被擋。各路由都是先驗證身分再限流。
    user = getattr(request, "_cached_auth_user", None)
    if user and user.get("id"):
        return f"user:{user['id']}"
    return client_ip()


def enforce_rate_limit(limiter, bucket: str) -> None:
    limiter.check(f"{bucket}:{_client_key()}")


# Gemini 呼叫失敗時，錯誤原文不回給前端：掃描頁會把它直接顯示在畫面上，
# 先前 requests 連線錯誤的原文帶著整串網址，連金鑰一起回去了。細節只留在後端 log。
def _redact_gemini_keys(text: str) -> str:
    for key in get_gemini_api_keys():
        text = text.replace(key, "***")
    return text


def gemini_unreachable_response(feature: str, error: Exception):
    print(f"[WARN] {feature}連不上 Gemini：{type(error).__name__}: {_redact_gemini_keys(str(error))}")
    return jsonify({"error": f"{feature}服務暫時連不上，請稍後再試。"}), 502


def gemini_http_error_response(feature: str, error: requests.HTTPError):
    # Google 的錯誤原文可能帶著專案編號、模型名稱這類內部資訊，只寫進後端 log
    status = error.response.status_code if error.response is not None else None
    detail = error.response.text[:300] if error.response is not None else ""
    print(f"[WARN] {feature}：Gemini 回 HTTP {status}：{_redact_gemini_keys(detail)}")
    if status == 429:
        message = f"{feature}的 AI 額度暫時用完了，請稍後再試。"
    elif status in (401, 403):
        message = f"{feature}服務的金鑰無效或沒有權限，請通知網站管理者。"
    elif status == 400:
        message = f"AI 服務無法處理這次的{feature}，請換一張照片或稍後再試。"
    else:
        message = f"{feature}服務暫時不可用（HTTP {status}），請稍後再試。"
    return jsonify({"error": message}), 502


def gemini_failure_response(feature: str, error: Exception):
    print(f"[ERROR] {feature}失敗：{type(error).__name__}: {_redact_gemini_keys(str(error))}")
    return jsonify({"error": f"{feature}失敗，請稍後再試。"}), 500


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
        request._cached_auth_user = verify_access_token(auth_repo, request.headers.get("Authorization"))
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


# 登入與註冊要限流，不然一個迴圈就能一直猜密碼。同一個帳號限得緊；
# 同一個 IP 放寬一點——全班在同一個 Wi-Fi 下同時註冊時，對外是同一個 IP。
_auth_limiter = build_limiter("RATE_LIMIT_AUTH_CALLS", 10)
_auth_ip_limiter = build_limiter("RATE_LIMIT_AUTH_IP_CALLS", 60)


def enforce_auth_rate_limit(email) -> None:
    enforce_rate_limit(_auth_ip_limiter, "auth-ip")
    # 同一個帳號不論從哪裡來都一起算，換來源 IP 也繞不過去
    _auth_limiter.check(f"auth:{normalize_email(email)}")


def signup_mode() -> str:
    """open：直接註冊；code：要邀請碼；closed：不開放。

    在這台電腦上永遠可以註冊。從其他裝置或 tunnel 來的，要有主人設定的
    SIGNUP_CODE 才能註冊——不然任何拿到網址的人都能註冊、花你的 Gemini 額度。
    主人設 OPEN_SIGNUP=true 就是明白要開放給所有人，不用邀請碼。
    Render 上（會自動設 RENDER）沒設 OPEN_SIGNUP 就當作開放；設 OPEN_SIGNUP=false 才關。
    """
    open_signup = os.environ.get("OPEN_SIGNUP", "true" if os.environ.get("RENDER") else "").lower()
    if is_local_request() or open_signup == "true":
        return "open"
    return "code" if (os.environ.get("SIGNUP_CODE") or "").strip() else "closed"


@app.route("/auth/config", methods=["GET"])
def auth_config():
    return jsonify({"signup": signup_mode()})


@app.route("/auth/signup", methods=["POST"])
def auth_signup():
    data = json_body()
    enforce_auth_rate_limit(data.get("email"))
    mode = signup_mode()
    if mode == "closed":
        raise AuthError("這個網址目前不開放註冊，請向網站主人索取邀請碼。", 403)
    if mode == "code":
        expected = (os.environ.get("SIGNUP_CODE") or "").strip()
        given = str(data.get("invite_code") or "").strip()
        if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
            raise AuthError("邀請碼不對，請再確認一次。", 403)
    return jsonify(sign_up(auth_repo, data.get("email"), data.get("password"))), 201


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = json_body()
    enforce_auth_rate_limit(data.get("email"))
    return jsonify(sign_in(auth_repo, data.get("email"), data.get("password")))


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    sign_out(auth_repo, request.headers.get("Authorization"))
    return jsonify({"ok": True})


@app.route("/auth/user", methods=["GET"])
def auth_user():
    return jsonify({"user": verify_access_token(auth_repo, request.headers.get("Authorization"))})

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
    if frontend_available():
        return serve_frontend("index.html")
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
        "database": sql_db.dialect if sql_db is not None else ("mongo" if USE_MONGO else "memory"),
        # 路徑裡有 Windows 使用者名稱，只給這台電腦自己看；Postgres 不回傳主機
        "database_path": database_path if database_path and is_local_request() else None,
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
        "auth_provider": f"local-{sql_db.dialect}" if auth_repo.use_sql else "local-memory",
        "custom_foods": storage.count_custom_foods(),
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
        # 表單的選項與合理範圍只能有一份定義，前端不再自己抄。
        "diet_types": list(DIET_TYPES),
        "profile_limits": PROFILE_LIMITS,
        "threshold_conflicts": conflicts,
        # 兩種讀者，兩句話。
        #
        # threshold_conflict_note 是要放進 App 畫面的：使用者需要知道的是
        # 「門檻取比較嚴的那一組」，不是每一項營養素的兩個候選數字，更不是
        # 「需要臨床人員確認要採用哪一邊」——那句話對使用者的意思是這個 App
        # 自己也不知道該用哪個數字。
        #
        # review_note 與上面的 threshold_conflicts 給審閱流程用，資料照樣完整。
        "threshold_conflict_note": (
            "疾病門檻採用規則檔與臨床公式中較嚴格的一組。" if conflicts else None
        ),
        "threshold_conflict_review_note": (
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
    try:
        limit = min(max(int(request.args.get("limit", 20)), 1), 100)
    except (TypeError, ValueError):
        return jsonify({"error": "limit 必須是有效數字"}), 400

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
    data = json_body()
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
    data = json_body()
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
        return gemini_http_error_response("營養標示辨識", e)
    except requests.RequestException as e:
        return gemini_unreachable_response("營養標示辨識", e)
    except Exception as e:
        return gemini_failure_response("營養標示辨識", e)


@app.route("/predict/vision-food", methods=["POST"])
def predict_vision_food():
    data = json_body()
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
    # 每掃一次就打一次 Gemini Vision，跟其他付費路由一樣要限流
    enforce_rate_limit(_paid_api_limiter, "vision")

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
        return gemini_http_error_response("食物辨識", e)
    except requests.RequestException as e:
        return gemini_unreachable_response("食物辨識", e)
    except Exception as e:
        return gemini_failure_response("食物辨識", e)


# ─── 2. User Profile CRUD (PRD: 健康檔案與疾病管理) ──────────
@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    require_user_access(user_id)
    user = storage.get_user(user_id)

    if not user:
        return jsonify({"error": "使用者不存在"}), 404

    # 舊帳號存的欄位可能已經不在目前的選單裡（例如 diet_type 的「均衡飲食」）。
    # 只修寫入路徑救不到他們——那些帳號會被鎖在一個存不了檔的表單裡，
    # 所以讀到就地補正並寫回去，一次就好。
    user, changed = normalize_stored_user(user)
    if changed:
        storage.upsert_user(user)
    return jsonify(user)


@app.route("/user", methods=["POST"])
def create_or_update_user():
    data = json_body()
    if not data or "user_id" not in data:
        return jsonify({"error": "缺少 user_id"}), 400
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))

    # profile_complete 沒送的話，不能當成 False。
    #
    # 部署是分開的：後端會先上，而那時候線上的前端還是舊版，它根本不知道有
    # 這個欄位。若沒有這一段，舊前端每存一次檔（連「勾一個疾病」都會送整份
    # 檔案）就會把使用者標成「沒填過基本資料」，等新前端上線，這些人就會被
    # 那張「還沒填寫你的基本資料」的卡片攔下來——而他們早就填完了。
    #
    # 規則：沒送就沿用已存的值；連資料列都沒有的才算新帳號。會建空白檔案的
    # 只有前端那條 404 路徑，而它一定會明確送 profile_complete: false。
    if "profile_complete" not in data:
        existing = storage.get_user(data["user_id"])
        data["profile_complete"] = bool(existing.get("profile_complete", True)) if existing else True

    try:
        user_doc = build_user_profile(data, DISEASE_RULES, ALLERGEN_TAXONOMY)
    except ValueError as e:
        # 身高 1cm、體重 1kg 這種值會一路變成每日目標與單餐上限，
        # 不能只靠前端的表單擋。
        return jsonify({"error": str(e)}), 400

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
    data = json_body()
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
        # 單餐上限。先前這組數字只在推薦與掃描時擋得住候選餐點，使用者自己
        # 記下的餐點從來沒被檢查過——一位高血壓使用者記了 620mg 的一餐
        # （單餐上限 600mg），首頁照樣寫「目前沒有需要優先處理的飲食警示」。
        # 數字從後端出去，前端只負責比大小，不再自己抄一份會漂移的門檻。
        "meal_nutrient_limits": effective_meal_limits(
            DISEASE_RULES,
            normalize_condition_ids(user.get("health_conditions") or [], DISEASE_RULES),
            user,
        ),
    })


@app.route("/records/<user_id>/<client_record_id>", methods=["PATCH"])
def update_record(user_id, client_record_id):
    require_user_access(user_id)
    existing = storage.get_record_by_client_record_id(user_id, client_record_id)
    if not existing:
        return jsonify({"error": "找不到飲食紀錄"}), 404

    data = json_body()
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
    # 一次會打 Google Places 和好幾家店的 Gemini 分析，都是按次計費的
    enforce_rate_limit(_paid_api_limiter, "venue-index")
    data = json_body()
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
    # 會列出每把金鑰的開頭與權限，是給主人除錯用的，不開放給一般使用者
    require_local_request("金鑰診斷")
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
    # 菜單快取是所有人共用的；先前任何登入者都能一鍵清掉全部人的
    require_local_request("清除菜單檔案")
    removed = storage.clear_restaurant_menus()
    # 重建就是要照新規則重來，先前問不出菜單的店也要再問一次
    storage.clear_restaurant_menu_failures()
    return jsonify({"message": f"已清除 {removed} 家店的菜單檔案", "removed": removed})


@app.route("/history/<user_id>", methods=["GET"])
def get_history(user_id):
    require_user_access(user_id)
    try:
        days = min(max(int(request.args.get("days", 7)), 1), 365)
    except (TypeError, ValueError):
        return jsonify({"error": "days 必須是有效數字"}), 400
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
    # 每次都會打 Google Places
    enforce_rate_limit(_paid_api_limiter, "places")
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


def _coordinate(value, default: float, low: float, high: float) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(value) from error
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(value)
    return number


@app.route("/restaurant/menu", methods=["POST"])
def get_restaurant_menu():
    """
    動態獲取餐廳詳細菜單。如果本地資料庫不存在，則調用爬蟲與 Gemini 動態分析。
    """
    data = json_body()
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
    name = data.get("name") or ""
    address = data.get("address") or ""
    if not isinstance(name, str) or not isinstance(address, str):
        return jsonify({"error": "name 與 address 必須是文字"}), 400
    name, address = name.strip(), address.strip()
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

    # 先前 lng 沒帶時預設成緯度 25.0338（抄錯欄位），座標不是數字時 float() 直接 500
    try:
        venue_lat = _coordinate(data.get("lat"), 25.0338, -90, 90)
        venue_lng = _coordinate(data.get("lng"), 121.5645, -180, 180)
    except ValueError:
        return jsonify({"error": "lat / lng 必須是有效的座標"}), 400
    # 在呼叫 Gemini 之前就檢查：先前放在後面，菜單都分析完了才 500
    try:
        budget = int(data.get("budget", 150))
    except (TypeError, ValueError):
        return jsonify({"error": "budget 必須是有效數字"}), 400

    # 沒有 profile 就不能篩。先前這裡退回共用的 "demo_user"（storage 還會在
    # 正式資料庫自動建一個 0 疾病 0 過敏的帳號），等於把安全過濾靜默關掉，
    # 而畫面上看起來一切正常。寧可回錯誤，也不要回一份沒篩過的推薦。
    # 也要在分析菜單之前檢查：先前放在後面，先花一次 Gemini、寫進共用快取才回 404。
    user_id = data.get("user_id") or get_request_user_id() or ""
    user = storage.get_user(user_id)
    if not user:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404

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
                "lat": venue_lat,
                "lng": venue_lng,
                "address": address or "台灣",
                "phone": "",
                "open_hours": ["11:00-21:00"],
                "tags": ["實體菜單辨識", "AI標記"],
                "price_level": 2,
                "items": recognized_items
            }
            # 照片是使用者自己上傳的，辨識結果只給這次的回應用，不寫進所有人共用的
            # 菜單快取：先前任何人都能拿一張假菜單，替任何店家名稱「建檔」，
            # 其他人的推薦就會照那份假資料篩選。
    elif not matched:
        # 2. 本地不存在 ➔ 呼叫爬蟲與 Gemini 即時分析
        print(f"[Scraper] 即時線上擷取並生成 {name} 的菜單")
        enriched = enrich_restaurant_with_gemini(name, address or "台灣", "")
        
        # 建立新餐廳物件
        new_id = restaurant_id or f"scraped_{uuid.uuid4().hex[:6]}"
        matched = {
            "restaurant_id": new_id,
            "name": name,
            "lat": venue_lat,
            "lng": venue_lng,
            "address": address or "台灣",
            "phone": "",
            "open_hours": ["11:00-21:00"],
            "tags": ["動態擷取", "AI標記"],
            "price_level": 2,
            "items": enriched.get("items", [])
        }
        # 跟上面的菜單照片一樣，結果只給這次的回應用，不寫進所有人共用的菜單快取：
        # 店名和地址是請求方自己填的，會原樣進 Gemini 的提示。先前在地址裡寫一段話，
        # 就能讓模型回一份假的低鈉菜單、用真實店名存進快取，其他人的推薦照它篩選，
        # 建檔也會把它當成新的而跳過這家店。共用快取只由建檔寫入，店名和地址來自 Google。

    # 3. 對所有菜單項目進行醫學過濾與個人化偏好契合度評分（user 在上面已經確認存在）
    conditions = user.get("health_conditions", []) or []
    allergens = user.get("allergens", []) or []
    # 先前這裡直接讀 profile 存的 daily_calorie_target，沒有就退回寫死的 2100。
    # 但「我的」頁面顯示的每日目標是依疾病與活動量重算過的，兩個數字對不起來：
    # 畫面說每天 1900 kcal，這條路徑卻拿 2100÷3=700 kcal 當單餐目標。
    # 改成跟單餐上限同源，整個後端只有一個每日熱量。
    daily_energy, _ideal_weight = resolve_user_energy_and_weight(conditions, user)
    target_calories = daily_energy / MEALS_PER_DAY
    
    recommended_items = []
    filtered_items = []
    
    for item in matched.get("items", []):
        candidate = {
            "label": item.get("item_id", item["name"]),
            "name_zh": item["name"],
            "gi": item.get("gi"),
            "allergens": item.get("allergens", []),
            # 少了 calories 這個鍵，scale_nutrients 就把熱量讀成 0，
            # 於是每個疾病宣告的單餐熱量上限（每日 E ÷ 3）永遠不會觸發。
            "calories": item.get("calories"),
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
    # 每點一家店就打一次 Gemini
    enforce_rate_limit(_paid_api_limiter, "summary")
    user = storage.get_user(user_id)
    if not user:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404

    data = json_body()
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
        return gemini_http_error_response("店家摘要", e)
    except requests.RequestException as e:
        # 逾時、連不上：先前沒接住，變成 500
        return gemini_unreachable_response("店家摘要", e)
    return jsonify({"summary": summary}), 200


# ─── 6. BMR/TDEE Calculator (PRD: 動態計算) ─────────────────
@app.route("/calculate/bmr", methods=["POST"])
def calc_bmr():
    try:
        return jsonify(build_bmr_response(json_body()))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


# ─── 網站本身（frontend/dist）─────────────────────────────────
# 先執行 `npm --prefix frontend run build:local`，後端就把網站跟 API 放在同一個埠：
# 手機、同一個 Wi-Fi 或 VPN 的電腦、透過 tunnel 從外面連，都只要開一個網址，
# 也不會有跨網域（CORS）的問題。沒打包過就只提供 API。
FRONTEND_DIST = os.path.abspath(
    os.environ.get("FRONTEND_DIST") or os.path.join(BASE_DIR, "..", "frontend", "dist")
)


def frontend_available() -> bool:
    return os.path.isfile(os.path.join(FRONTEND_DIST, "index.html"))


def serve_frontend(path: str):
    candidates = [path, f"{path}.html"] if path else ["index.html"]
    found = next(
        (name for name in candidates if (full := safe_join(FRONTEND_DIST, name)) and os.path.isfile(full)),
        None,
    )
    if found is None:
        # JS、圖片找不到就是找不到；頁面路徑交給 index.html，由前端路由處理
        if path.startswith(("_expo/", "assets/")) or os.path.splitext(path)[1]:
            return jsonify({"error": "找不到這個檔案"}), 404
        found = "index.html"
    response = send_from_directory(FRONTEND_DIST, found)
    # 打包出來的 JS 檔名帶內容雜湊，可以放心長期快取；頁面本身每次都要重新確認
    if found.startswith(("_expo/static/", "assets/")):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/<path:path>", methods=["GET"])
def frontend_files(path):
    if not frontend_available():
        return jsonify({"error": "找不到這個 API"}), 404
    return serve_frontend(path)


def share_addresses() -> tuple[str | None, list[str]]:
    """（主要網路的 IP, 其他網卡的 IP）。

    電腦上常有 WSL、虛擬機、VPN 的虛擬網卡，全部列出來分不出該用哪一個。
    主要網路 = 對外連線會走的那張網卡；用 UDP 「連」一個外部位址只是問作業系統
    會走哪張網卡，不會真的送出封包。
    """
    primary = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            primary = probe.getsockname()[0]
    except OSError:
        pass
    others = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            others.add(info[4][0])
    except OSError:
        pass
    others = sorted(ip for ip in others if ip != primary and not ip.startswith("127."))
    return (primary if primary and not primary.startswith("127.") else None), others


def wants_lan(argv, environ) -> bool:
    return "--lan" in argv or environ.get("SHARE_ON_LAN", "").lower() == "true"


def bind_host(argv, environ) -> str:
    """預設只有這台電腦連得到。

    先前一律開在 0.0.0.0，加上防火牆對「公用網路」也放行 python，在咖啡店的 Wi-Fi 上
    同一個網路的人都連得進來。要給同一個 Wi-Fi 或 VPN 的裝置用，才加 --lan。
    cloudflared 是從本機連進來的，不需要 --lan。
    Render 會自動設 RENDER，而且只認 0.0.0.0 上的埠；綁 127.0.0.1 部署會失敗。
    """
    if wants_lan(argv, environ) or environ.get("RENDER"):
        return "0.0.0.0"
    return "127.0.0.1"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    share_on_lan = wants_lan(sys.argv[1:], os.environ)
    host = bind_host(sys.argv[1:], os.environ)
    if frontend_available():
        print(f"[OK] 網站：http://localhost:{port}")
        if share_on_lan:
            primary, others = share_addresses()
            if primary:
                print(f"     同一個網路的手機或電腦：http://{primary}:{port}")
            if others:
                print("     其他網卡（VPN、虛擬機）：" + "、".join(f"http://{ip}:{port}" for ip in others))
            if os.environ.get("OPEN_SIGNUP", "").lower() == "true":
                print("     所有人都可以直接註冊（OPEN_SIGNUP=true）")
            elif not (os.environ.get("SIGNUP_CODE") or "").strip():
                print("     其他裝置只能登入、不能註冊；要開放註冊請在 backend/.env.local 設 SIGNUP_CODE 或 OPEN_SIGNUP=true")
        else:
            print("     只有這台電腦連得到；要給同一個 Wi-Fi 的裝置用，改用 python backend/app.py --lan")
    else:
        print("[INFO] 還沒打包網站，只提供 API。要讓其他裝置連，先執行 npm --prefix frontend run build:local")
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    if debug:
        # 除錯模式的錯誤頁可以執行程式碼，絕對不能讓別台電腦連到
        print("[WARN] FLASK_DEBUG 開啟中，只綁定 127.0.0.1")
        app.run(debug=True, host="127.0.0.1", port=port)
    else:
        # Flask 內建伺服器是單執行緒的開發用伺服器，它自己也會警告
        # 「Do not use it in a production deployment」。正式環境用 waitress。
        try:
            from waitress import serve

            print(f"[OK] Serving with waitress on {host}:{port}")
            serve(app, host=host, port=port, threads=8, max_request_body_size=MAX_REQUEST_BYTES)
        except ImportError:
            print("[WARN] waitress 未安裝，退回 Flask 開發伺服器（僅適合本機）")
            app.run(debug=False, host=host, port=port)
