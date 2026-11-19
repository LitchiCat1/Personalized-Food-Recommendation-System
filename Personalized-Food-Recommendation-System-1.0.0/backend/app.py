"""
NutriLens Backend — Flask API
PRD-aligned: Gemini Vision food recognition + nutrition analysis + user management
"""

import gzip
import hmac
import ipaddress
import json
import math
import os
import socket
import sqlite3
import sys
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import BadRequest, HTTPException, InternalServerError, RequestEntityTooLarge
from werkzeug.security import safe_join
from repositories.auth_repository import AuthRepository
from repositories.database import DatabaseUnavailable, SQLITE_ONLY_MESSAGE, open_database
from repositories.sqlite_backup import BackupError, auto_backup_from_env, backup_database
from repositories.sqlite_schema import SchemaVersionError, check_schema_version, upgrade_schema
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
from services.ai_relay_service import get_relay_config
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
from services.nutrition_profile_service import (
    NutritionProfileError,
    aggregate_nutrition_coverage,
    profile_from_local_food,
)
from services.record_nutrition_service import normalize_v2_record
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
from services.nutrition_database_service import load_official_nutrition_dataset, build_nutrition_dataset_context
from services.nutrition_enrichment_route_service import (
    NutritionEnrichmentRouteError,
    build_local_nutrition_item_result,
    process_enrichment_request,
)
from services.nutrition_enrichment_coordinator import NutritionEnrichmentCoordinatorError
from services.nutrition_authority_service import NutritionAuthorityService
from services.nutrition_scan_context_adapter import (
    NutritionScanContextAdapterError,
    persist_vision_scan_context,
)
from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.scan_context_repository import NutritionScanContextRepository, ScanContextRepositoryError
from repositories.nutrition_identity_confirmation_repository import (
    NutritionIdentityConfirmationError, NutritionIdentityConfirmationRepository,
)
from repositories.nutrition_enrichment_repository import NutritionEnrichmentRequestRepository
from repositories.nutrition_quota_repository import NutritionQuotaRepository
from repositories.nutrition_cache_repository import NutritionProfileCacheRepository
from repositories.fdc_candidate_snapshot_repository import (
    FdcCandidateSnapshotRepository,
    FdcCandidateSnapshotRepositoryError,
)
from repositories.fdc_candidate_confirmation_repository import (
    FdcCandidateConfirmationRepository,
    FdcCandidateConfirmationRepositoryError,
)
from repositories.fdc_profile_preview_repository import (
    FdcProfilePreviewRepository,
    FdcProfilePreviewRepositoryError,
)
from services.fdc_profile_preview_service import (
    FdcProfilePreviewService,
    FdcProfilePreviewError,
)
from services.fdc_candidate_search_service import (
    FdcCandidateSearchService,
    FdcCandidateSearchError,
)
from services.fdc_reviewed_selection_service import (
    FdcReviewedSelectionError, FdcReviewedSelectionService, PRODUCTION_REVIEWED_FDC_SOURCES,
)
from services.fdc_reviewed_source_lifecycle_service import load_installed_reviewed_fdc_sources
from services.web_nutrition_service import (
    PRODUCTION_SOURCE_REGISTRY,
    enrich_nutrition,
    make_local_nutrition_lookup,
)
from services.nutrition_extraction_model_service import select_nutrition_cells_with_relay
from services.tavily_retrieval_service import TavilyClient
from services.fooddata_central_client import FoodDataCentralClient, FoodDataCentralClientError
from services.robust_restaurant_scraper_service import enrich_restaurant_with_gemini, parse_menu_image_with_gemini
from services.medical_risk_service import (
    MEALS_PER_DAY,
    effective_meal_limits,
    evaluate_medical_risk,
    evaluate_meal_medical_risk,
    normalize_number,
    resolve_user_energy_and_weight,
    rule_threshold_conflicts,
)
from services.google_places_service import fetch_google_places_restaurants
from services.venue_index_service import VenueIndexUnavailable, index_nearby_venues


load_local_env()

BASE_DIR = os.path.dirname(__file__)

# ─── 資料庫 ──────────────────────────────────────────────────
# 專案只支援 SQLite。既有資料檔位置見 sqlite_db.py，可以用 DATABASE_PATH 改；
# 設成空字串就不用資料庫，資料只存在記憶體。
sql_db = None
if os.environ.get("DATABASE_URL", "").strip():
    print(f"[ERROR] {SQLITE_ONLY_MESSAGE}")
    sys.exit(1)
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
    print(f"[ERROR] {e}")
    sys.exit(1)
except Exception as e:
    # SQLite 開不起來也要停下。先前印一行 WARN 就退回記憶體：
    # 註冊、記錄看起來都正常，後端一重開就全部消失。真的只要記憶體就明確設 DATABASE_PATH=。
    print(f"[ERROR] 打不開 SQLite 資料庫 {resolve_database_path()}：{e}")
    print("        檔案可能損毀或沒有寫入權限。請從備份還原這個檔案（見 backend/scripts/backup_db.py），")
    print("        或用 DATABASE_PATH 指到其他位置；只想暫時存在記憶體（重開就清空）請設 DATABASE_PATH= 空字串。")
    sys.exit(1)
# 路徑裡有 Windows 使用者名稱，/health 只給這台電腦自己看
database_path = sql_db.path if sql_db is not None else None
if database_path:
    # 建資料表之前就檢查：比程式新的資料庫，連 CREATE TABLE 都不該碰
    try:
        check_schema_version(sql_db)
    except SchemaVersionError as e:
        print(f"[ERROR] {e}")
        # 先關掉，檔案才不會被鎖著，要搬走或還原都可以
        sql_db.close()
        sys.exit(1)

# Explicit temporary storage is used only when DATABASE_PATH is empty.
_mem_users = {}
_mem_records = []
_mem_custom_foods = []

storage = StorageRepository(_mem_users, _mem_records, _mem_custom_foods, sql=sql_db)
# 帳號跟著資料庫走。沒有資料庫時帳號只存在記憶體，重啟就要重新註冊。
auth_repo = AuthRepository(sql_db)
if sql_db is None:
    print("[WARN] 帳號存在記憶體裡，後端重啟後要重新註冊")
if database_path:
    def _backup_before_upgrade(label):
        if database_path != ":memory:":
            path = backup_database(database_path, os.path.join(os.path.dirname(database_path), "backups"), label=label)
            print(f"[OK] 升級資料庫結構前先備份：{path}")

    try:
        _upgraded = upgrade_schema(sql_db, backup=_backup_before_upgrade)
    except (SchemaVersionError, BackupError, sqlite3.Error) as e:
        # 每一版在自己的交易裡做，失敗的那一版已經退回；資料庫停在上一個完整的版本
        print(f"[ERROR] 資料庫結構升級失敗，後端沒有啟動：{e}")
        sql_db.close()
        sys.exit(1)
    if _upgraded:
        print(f"[OK] 資料庫結構已升級到第 {_upgraded[-1]} 版")

app = Flask(__name__)

# 一張 8 MB 的照片轉成 Base64 約 10.7 MB，再加上 JSON。先前沒有上限，
# 一個超大的請求會整個讀進記憶體才被拒絕。
MAX_REQUEST_BYTES = 12 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

# 飲食紀錄、自訂食品、健康檔案只有文字和數字，正常一筆只有幾 KB。先前它們也照收
# 給照片用的 12 MB：食物裡多塞的欄位原樣存下，一筆 8 MB 的紀錄就進了資料庫。
MAX_FORM_BYTES = 64 * 1024


class PayloadTooLarge(HTTPException):
    code = 413
    description = "這筆資料太大了，請減少食物項目或文字長度後再試。"


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


def json_body(max_bytes: int | None = None) -> dict:
    """請求內容的 JSON 物件，沒有內容就是空物件。

    先前各路由各自 request.get_json()：送陣列或字串時 data.get() 直接 500，
    沒帶 JSON 時 Flask 回 415 的 HTML 錯誤頁。
    max_bytes 給不收照片的路由用，比全站的上限小得多。
    """
    if max_bytes is not None and (request.content_length or 0) > max_bytes:
        raise PayloadTooLarge()
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    if max_bytes is not None and len(raw) > max_bytes:
        raise PayloadTooLarge()
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

    ALLOWED_ORIGINS 可填主機名或完整 origin；省略協定時，本機使用 HTTP，
    其他主機使用 HTTPS。同源的 Tailscale 網站不需要額外設定 CORS。
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
    # 跨來源預設只放行本機 Expo 開發埠；外部網站須逐一列入 ALLOWED_ORIGINS。
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


@app.after_request
def add_security_headers(response):
    """不讓別的網站把這裡嵌進 iframe 騙人點擊，也不讓瀏覽器自己猜檔案類型。

    登入 token 存在瀏覽器的 localStorage，頁面一旦被插進別人的程式就讀得走，
    所以這幾個不影響功能的標頭先加上。沒有設限制腳本來源的完整 CSP：
    Expo 打包的網站和 Google 地圖要用的來源還沒逐一確認，設錯整個網站會打不開。
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy", "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    )
    return response

# 會呼叫 Gemini / Google Places 的路由要限流，那些都是按次計費的
_paid_api_limiter = build_limiter("RATE_LIMIT_PAID_CALLS", 12)
_fdc_candidate_limiter = build_limiter("RATE_LIMIT_FDC_CANDIDATE_CALLS", 4)
_identity_confirmation_limiter = build_limiter("RATE_LIMIT_IDENTITY_CONFIRMATION_CALLS", 12)
# 會寫進資料庫的路由（飲食紀錄、自訂食品、健康檔案）。先前這個限流器建了卻沒有
# 任何路由用：避免重複或暴增請求耗盡外部服務額度與本機儲存空間。
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
    SIGNUP_CODE 才能註冊，避免任何拿到網址的人都能使用付費模型額度。
    主人設 OPEN_SIGNUP=true 就是明白要開放給所有人，不用邀請碼。
    """
    open_signup = os.environ.get("OPEN_SIGNUP", "").lower()
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

# Each official layer keeps its own health. An unavailable layer is not a
# successful empty lookup and must never trigger automatic paid enrichment.
_tfda_dataset = load_official_nutrition_dataset(BASE_DIR, "TFDA")
_usda_dataset = load_official_nutrition_dataset(BASE_DIR, "USDA FNDDS")
NUTRITION_DATASET_HEALTH = {"TFDA": _tfda_dataset["health"], "USDA FNDDS": _usda_dataset["health"]}
TFDA_DB = dict(_tfda_dataset["foods"])
USDA_DB = _usda_dataset["foods"]
for _source, _health in NUTRITION_DATASET_HEALTH.items():
    print(f"[{'OK' if _health['status'] == 'available' else 'WARN'}] {_source} nutrition DB: "
          f"{_health['status']} ({_health['record_count']} foods; {_health['reason'] or 'validated'})")
TFDA_DB.update(USDA_DB)

# Durable enrichment dependencies.  The route is intentionally kept behind an
# explicit feature flag until a reviewed source policy and live-provider
# acceptance are complete.  Constructing these repositories is side-effect
# free apart from creating their own tables in the already-selected SQL DB.
nutrition_scan_context_repository = NutritionScanContextRepository(sql_db)
nutrition_identity_confirmation_repository = (
    NutritionIdentityConfirmationRepository(
        sql_db, scan_context_repository=nutrition_scan_context_repository)
    if sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite" else None
)
fdc_candidate_snapshot_repository = FdcCandidateSnapshotRepository(
    sql_db, scan_context_repository=nutrition_scan_context_repository)
fdc_candidate_confirmation_repository = (
    FdcCandidateConfirmationRepository(
        sql_db, snapshot_repository=fdc_candidate_snapshot_repository)
    if sql_db is not None else None
)
nutrition_profile_repository = NutritionProfileSourceRepository(sql_db)
nutrition_enrichment_repository = NutritionEnrichmentRequestRepository(sql_db)
nutrition_quota_repository = NutritionQuotaRepository(sql_db)
nutrition_cache_repository = NutritionProfileCacheRepository(
    nutrition_profile_repository, sql_db)


def _build_nutrition_authority_service():
    """Build the scanner/enrichment signing service from a server-only secret.

    The secret is deliberately not read from the request or shipped to the
    frontend.  A missing or undersized secret keeps the paid enrichment route
    disabled instead of silently falling back to process-local replay state.
    """
    secret = os.environ.get("NUTRITION_AUTHORITY_SECRET", "").strip()
    if not secret:
        return None
    if len(secret.encode("utf-8")) < 32:
        print("[WARN] NUTRITION_AUTHORITY_SECRET is too short; nutrition enrichment remains disabled")
        return None
    try:
        return NutritionAuthorityService(
            {"active": secret.encode("utf-8")}, active_kid="active")
    except Exception as error:
        print(f"[WARN] Nutrition authority signing is unavailable: {error}")
        return None


nutrition_authority_service = _build_nutrition_authority_service()
nutrition_enrichment_route_enabled = (
    os.environ.get("NUTRITION_ENRICHMENT_ROUTE_ENABLED", "false").strip().lower() == "true"
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
    and nutrition_authority_service is not None
)
nutrition_identity_confirmation_route_enabled = (
    os.environ.get("NUTRITION_IDENTITY_CONFIRMATION_ROUTE_ENABLED", "false").strip().lower() == "true"
    and nutrition_identity_confirmation_repository is not None
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
)
fdc_confirmation_route_enabled = (
    os.environ.get("FDC_CONFIRMATION_ROUTE_ENABLED", "false").strip().lower() == "true"
    and fdc_candidate_confirmation_repository is not None
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
)
fdc_detail_route_enabled = (
    os.environ.get("FDC_DETAIL_ROUTE_ENABLED", "false").strip().lower() == "true"
    and fdc_candidate_confirmation_repository is not None
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
)
fdc_profile_preview_route_enabled = (
    os.environ.get("FDC_PROFILE_PREVIEW_ROUTE_ENABLED", "false").strip().lower() == "true"
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
)
fdc_profile_accept_route_enabled = (
    os.environ.get("FDC_PROFILE_ACCEPT_ROUTE_ENABLED", "false").strip().lower() == "true"
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
)
fdc_candidate_route_enabled = (
    os.environ.get("FDC_CANDIDATE_ROUTE_ENABLED", "false").strip().lower() == "true"
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
)
fdc_reviewed_selection_route_enabled = (
    os.environ.get("FDC_REVIEWED_SELECTION_ROUTE_ENABLED", "false").strip().lower() == "true"
    and sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite"
)
_loaded_reviewed_fdc_sources, fdc_reviewed_source_load_report = load_installed_reviewed_fdc_sources(
    reviewed_sources=PRODUCTION_REVIEWED_FDC_SOURCES,
    configuration_path=os.environ.get("FDC_REVIEWED_SOURCES_FILE", "").strip() or None,
    load_installed_policy=lambda source_id: nutrition_profile_repository.get_source_policy(
        source_id, include_withdrawn=True),
    sqlite_available=sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite",
)
if fdc_reviewed_source_load_report["decision"] != "ready":
    fdc_reviewed_selection_route_enabled = False
if fdc_reviewed_source_load_report["decision"] == "blocked":
    print("[WARN] Reviewed FDC sources are unavailable; reviewed selection remains disabled")
fdc_reviewed_selection_service = FdcReviewedSelectionService(
    scan_context_repository=nutrition_scan_context_repository,
    snapshot_repository=fdc_candidate_snapshot_repository,
    source_repository=nutrition_profile_repository,
    local_lookup_factory=lambda user_id: make_local_nutrition_lookup(
        storage, TFDA_DB, user_id, build_custom_food_search_result),
    official_health=NUTRITION_DATASET_HEALTH,
    reviewed_sources=_loaded_reviewed_fdc_sources,
)


def _build_fdc_detail_client():
    """Create the fixed-ID client only after the route and confirmation gates pass."""
    try:
        return FoodDataCentralClient.from_environment()
    except FoodDataCentralClientError as error:
        raise NutritionEnrichmentRouteError("provider_unavailable", str(error)) from error


def _build_fdc_search_client():
    """Create the bounded FDC Search client lazily behind the candidate route gate."""
    try:
        return FoodDataCentralClient.from_environment()
    except FoodDataCentralClientError as error:
        raise NutritionEnrichmentRouteError("provider_unavailable", str(error)) from error


fdc_profile_preview_repository = (
    FdcProfilePreviewRepository(
        sql_db, source_repository=nutrition_profile_repository)
    if sql_db is not None and getattr(sql_db, "dialect", None) == "sqlite" else None
)
fdc_profile_preview_service = (
    FdcProfilePreviewService(
        confirmation_repository=fdc_candidate_confirmation_repository,
        scan_context_repository=nutrition_scan_context_repository,
        source_repository=nutrition_profile_repository,
        detail_client_factory=_build_fdc_detail_client,
    )
    if fdc_candidate_confirmation_repository is not None
    and fdc_profile_preview_repository is not None else None
)
fdc_candidate_search_service = (
    FdcCandidateSearchService(
        scan_context_repository=nutrition_scan_context_repository,
        snapshot_repository=fdc_candidate_snapshot_repository,
        local_lookup_factory=lambda user_id: make_local_nutrition_lookup(
            storage, TFDA_DB, user_id, build_custom_food_search_result),
        client_factory=_build_fdc_search_client,
        official_health=NUTRITION_DATASET_HEALTH,
    )
    if fdc_candidate_route_enabled and fdc_candidate_snapshot_repository is not None else None
)


def _nutrition_scan_context_ttl_seconds():
    raw = os.environ.get("NUTRITION_SCAN_CONTEXT_TTL_SECONDS", "120").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise NutritionScanContextAdapterError(
            "invalid_expiry", "NUTRITION_SCAN_CONTEXT_TTL_SECONDS is invalid") from error
    if not math.isfinite(value) or value <= 0 or value > 15 * 60:
        raise NutritionScanContextAdapterError(
            "invalid_expiry", "NUTRITION_SCAN_CONTEXT_TTL_SECONDS is outside its permitted range")
    return value


def nutrition_enrichment_provider_factory(missing_items, known_items):
    """Build the third-layer provider using server configuration only.

    The factory is deliberately lazy: no Tavily client or model relay is
    created for a TFDA/USDA/cache hit, and missing credentials never reach the
    request payload or the frontend.
    """
    if not os.environ.get("TAVILY_API_KEY", "").strip():
        raise NutritionEnrichmentRouteError("provider_unavailable", "The web nutrition provider is not configured")
    try:
        tavily = TavilyClient.from_environment()
    except Exception as error:
        raise NutritionEnrichmentRouteError("provider_unavailable", "The web nutrition provider is not configured") from error
    local_lookup = make_local_nutrition_lookup(
        storage, TFDA_DB, None, build_custom_food_search_result)
    missing_ids = {item["item_id"] for item in missing_items}

    def provider(payload):
        started = time.monotonic()
        web_items = [item for item in payload.get("items", []) if item.get("item_id") in missing_ids]
        try:
            result = enrich_nutrition(
                web_items,
                official_health=NUTRITION_DATASET_HEALTH,
                lookup_local=local_lookup,
                registry=PRODUCTION_SOURCE_REGISTRY,
                tavily=tavily,
                select_cells=select_nutrition_cells_with_relay,
                deadline=started + 25,
            )
        finally:
            tavily.close()
        # Keep the coordinator response complete even when earlier items came
        # from a positive cache.  The coordinator still fingerprints the full
        # server-owned scan set, so retries remain idempotent.
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            return {"status": "invalid_output", "result": result if isinstance(result, dict) else None,
                    "production_enabled": False}
        by_id = {item["item_id"]: deepcopy(item) for item in known_items}
        for item in result.get("items", []):
            if not isinstance(item, dict) or not isinstance(item.get("item_id"), str):
                return {"status": "invalid_output", "result": result,
                        "production_enabled": False}
            # Official TFDA/USDA/cache data is authoritative for this request;
            # a web response cannot replace a known item with a weaker source.
            if item["item_id"] not in by_id:
                by_id[item["item_id"]] = item
        merged = [by_id[item["item_id"]] for item in payload.get("items", [])
                  if item["item_id"] in by_id]
        if {item["item_id"] for item in merged} != {item["item_id"] for item in payload.get("items", [])}:
            return {"status": "invalid_output", "result": result,
                    "production_enabled": False}
        try:
            coverage_items = []
            for item in merged:
                context = item.get("recognition_context")
                weight_g = context.get("estimated_weight_g") if isinstance(context, dict) else None
                coverage_items.append({
                    "item_id": item["item_id"],
                    "profile": item.get("nutrition_profile"),
                    "weight_g": weight_g,
                    "portion_source": "vision_estimate",
                })
            coverage = aggregate_nutrition_coverage([
                *coverage_items,
            ])
        except (KeyError, TypeError, AttributeError, NutritionProfileError):
            return {"status": "invalid_output", "result": result,
                    "production_enabled": False}
        return dict(result, items=merged, nutrition_coverage=coverage,
                    production_enabled=False)

    return provider

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


APP_VERSION = "v1.0.3"
STARTED_AT = app_now().isoformat()
print("[INFO] FDC preview startup: " + json.dumps({
    "app_version": APP_VERSION, "started_at": STARTED_AT,
    "source_load": fdc_reviewed_source_load_report,
    "reviewed_selection": fdc_reviewed_selection_route_enabled,
    "confirmation": fdc_confirmation_route_enabled,
    "preview": fdc_profile_preview_route_enabled,
    "candidate_search": fdc_candidate_route_enabled,
    "raw_detail": fdc_detail_route_enabled,
    "profile_accept": fdc_profile_accept_route_enabled,
    "enrichment": nutrition_enrichment_route_enabled,
    "fdc_key_available": bool(os.environ.get("USDA_FDC_API_KEY", "").strip()),
}, ensure_ascii=True))


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
        "nutrition_contract_versions": [1, 2],
        "nutrition_v2_flows": ["record_preview", "record_save", "record_edit", "records", "history"],
        "nutrition_v2_scanner_enabled": False,
        "database": sql_db.dialect if sql_db is not None else "memory",
        # 路徑裡有 Windows 使用者名稱，只給這台電腦自己看
        "database_path": database_path if database_path and is_local_request() else None,
        "cached_restaurant_menus": storage.count_restaurant_menus(),
        "mongo": False,  # Compatibility health field; MongoDB is unsupported.
        "recognition_engine": "ai-relay-vision-db-lookup" if get_relay_config() else "gemini-vision-db-lookup",
        "foods_in_db": len(NUTRITION_DB),
        "foods_in_tfda": len(TFDA_DB) - len(USDA_DB),
        "foods_in_usda": len(USDA_DB),
        **build_nutrition_dataset_context(NUTRITION_DATASET_HEALTH),
        "disease_rules": len(DISEASE_RULES),
        "disease_rule_review_status": build_disease_rules_response(DISEASE_RULES)["review_status_counts"],
        "restaurants": len(RESTAURANT_CATALOG),
        "places_enabled": bool(os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY")),
        # 有中轉設定時共用中轉；無中轉時才檢查舊版 OpenAI provider 設定。
        "openai_enabled": bool(get_relay_config() or (os.environ.get("OPENAI_API_KEY") or "").strip()),
        "ai_relay_enabled": bool(get_relay_config()),
        "auth_required": is_auth_required(),
        "auth_provider": f"local-{sql_db.dialect}" if auth_repo.use_sql else "local-memory",
        "custom_foods": storage.count_custom_foods(),
        # 部署後可以直接從 /health 看出線上跑的是哪一版，不用靠路由存不存在來猜。
        # 可由本機部署流程明確提供；未設定時不猜測工作樹或 commit。
        "deployed_branch": os.environ.get("NUTRILENS_DEPLOYED_BRANCH") or "local",
        "deployed_commit": (os.environ.get("NUTRILENS_DEPLOYED_COMMIT") or "local")[:7],
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
    data = json_body(MAX_FORM_BYTES)
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))
    enforce_rate_limit(_general_limiter, "write")
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
    data = json_body()
    require_legacy_nutrition_flow(data)
    enforce_rate_limit(_paid_api_limiter, "ocr")
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
    require_legacy_nutrition_flow(data)
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
        response = build_vision_food_response(
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
        response.update(build_nutrition_dataset_context(NUTRITION_DATASET_HEALTH))
        # The response's scan_id and recognition_context are server-generated.
        # Persist the narrowed authority snapshot before returning it so a
        # later enrichment request cannot submit a client-invented item set.
        if user_id and response.get("recognition_context", {}).get("items"):
            try:
                ttl_seconds = _nutrition_scan_context_ttl_seconds()
                scan_context = persist_vision_scan_context(
                    response,
                    user_id=user_id,
                    repository=nutrition_scan_context_repository,
                    ttl_seconds=ttl_seconds,
                )
                response["scan_context"] = {
                    "status": "persisted",
                    "scan_id": response["scan_id"],
                    "scan_revision": response.get("scan_revision", 0),
                    "expires_at": scan_context.get("expires_at") if scan_context else None,
                    "items": deepcopy(scan_context["items"]) if scan_context else [],
                }
                if scan_context and nutrition_enrichment_route_enabled:
                    response["scan_context"]["authority_token"] = (
                        nutrition_authority_service.issue_scan_context(
                            user_id=user_id,
                            scan_id=response["scan_id"],
                            scan_revision=response.get("scan_revision", 0),
                            items=scan_context["items"],
                            ttl_seconds=max(1, min(900, int(ttl_seconds))),
                        )
                    )
            except (NutritionScanContextAdapterError, ValueError) as error:
                # Keep the legacy scanner response compatible while the new
                # enrichment flag is off.  Once enabled, fail closed: an
                # unpersisted scan must never be eligible for web enrichment.
                error_code = getattr(error, "code", "invalid_context")
                if nutrition_enrichment_route_enabled:
                    return jsonify({"error": "掃描內容無法安全保存", "error_code": error_code}), 503
                response["scan_context"] = {"status": "unavailable"}
        return jsonify(response)
    except requests.HTTPError as e:
        return gemini_http_error_response("食物辨識", e)
    except requests.RequestException as e:
        return gemini_unreachable_response("食物辨識", e)
    except Exception as e:
        return gemini_failure_response("食物辨識", e)


def _enrichment_error_response(error):
    """Map internal enrichment states to a stable, non-secret HTTP envelope."""
    code = getattr(error, "code", "upstream_error")
    status = {
        "invalid_request": 400, "invalid_expiry": 400, "invalid_local_result": 400, "invalid_output": 422,
        "numeric_range": 422, "wrong_user": 403,
        "scan_unavailable": 409, "scan_not_found": 404, "item_set_mismatch": 409,
        "expired": 409, "revoked": 409, "stale_revision": 409, "superseded": 409,
        "profile_conflict": 409, "source_conflict": 409, "source_unavailable": 409,
        "rights_not_allowed": 409, "reuse_not_allowed": 409,
        "idempotency_conflict": 409, "ownership_conflict": 403,
        "authority_invalid": 403, "authority_conflict": 409, "replayed": 409,
        "not_yet_valid": 409,
        "user_quota_exceeded": 429, "global_quota_exceeded": 429,
        "quota_unavailable": 503, "busy": 429, "rate_limited": 429,
        "timeout": 504, "upstream_error": 502, "provider_unavailable": 503,
        "feature_disabled": 503, "single_flight_timeout": 202,
        "reservation_lost": 409,
        "confirmation_required": 409,
        "official_nutrition_pending": 409,
        "identity_confirmation_not_required": 409, "identity_context_incomplete": 409,
        "invalid_identity": 422, "item_not_found": 404,
        "wrong_actor": 403, "snapshot_mismatch": 409, "snapshot_unavailable": 409,
        "snapshot_conflict": 409, "confirmation_conflict": 409,
        "wrong_confirmation": 409, "revision_conflict": 409,
        "detail_not_found": 404, "detail_invalid": 422,
        "search_budget_exceeded": 422, "invalid_local_result": 503,
        "invalid_response": 502, "snapshot_unavailable": 409,
        "local_lookup_unavailable": 503,
        "local_unavailable": 503,
        "authentication_failed": 503, "transport_error": 502,
        "upstream_http_error": 502, "not_found": 502,
        "invalid_confirmation": 400, "oversized_request": 413,
        "storage_unavailable": 503, "invalid_clock": 503,
        "invalid_preview": 422, "invalid_provenance": 422, "invalid_portion": 422,
        "identity_mismatch": 409, "detail_unavailable": 503,
        "invalid_policy": 422, "authorization_changed": 409,
        "preview_not_found": 404, "preview_unavailable": 409,
        "preview_conflict": 409, "oversized_preview": 413, "oversized_result": 413,
    }.get(code, 500)
    message = str(error)
    if isinstance(error, (FdcCandidateSearchError, FdcCandidateSnapshotRepositoryError)):
        message = "無法取得 FDC 候選參考，請重新掃描或稍後再試。"
    if status >= 500 and code not in {"feature_disabled", "provider_unavailable"}:
        message = "營養補全服務暫時不可用，請稍後再試。"
    response = jsonify({"status": "error", "error": {"code": code, "message": message}})
    if status == 429:
        response.headers["Retry-After"] = "60"
    return response, status


def _fdc_candidate_reference_response(document):
    """Project the stored identity-only snapshot without nutrition or private fields."""
    snapshot = document["snapshot"]
    projected_items = [{
        "item_id": item["item_id"],
        "item_revision": item["item_revision"],
        "identity_digest": item["identity_digest"],
        "recognition_identity": deepcopy(item["recognition_identity"]),
        "candidates": [{
            "fdcId": candidate["fdcId"],
            "description": candidate["description"],
            "dataType": candidate["dataType"],
            "brandOwner": candidate["brandOwner"],
            "foodCategory": candidate["foodCategory"],
        } for candidate in item["candidates"]],
    } for item in snapshot["items"]]
    projected_snapshot = {
        "schema_version": snapshot["schema_version"],
        "scan_revision": snapshot["scan_revision"],
        "item_set_digest": snapshot["item_set_digest"],
        "snapshot_digest": snapshot["snapshot_digest"],
        "items": projected_items,
    }
    return {
        "status": "available" if any(item["candidates"] for item in projected_items) else "empty",
        "snapshot": {
            "scan_id": document["scan_id"],
            "scan_revision": document["scan_revision"],
            "snapshot_digest": document["snapshot_digest"],
            "expires_at": document["expires_at"],
            "snapshot": projected_snapshot,
        },
    }


@app.route("/nutrition/identity/confirmation", methods=["POST"])
def confirm_scan_food_identity():
    """Record an authenticated food-name decision and issue a new scan revision."""
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("食材名稱確認需要登入。", 401)
    if (not nutrition_identity_confirmation_route_enabled
            or nutrition_identity_confirmation_repository is None):
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("feature_disabled", "Food identity confirmation is not enabled"))

    try:
        _identity_confirmation_limiter.check(f"identity-confirmation:{authenticated_user_id}")
        data = json_body(MAX_FORM_BYTES)
        allowed = {"scan_id", "scan_revision", "item_id", "item_revision",
                   "name_zh", "idempotency_key"}
        if not isinstance(data, dict) or set(data) != allowed:
            raise NutritionIdentityConfirmationError(
                "invalid_request", "Only scan, item, name and idempotency references are accepted")
        result = nutrition_identity_confirmation_repository.confirm_item_name(
            authenticated_user_id=authenticated_user_id,
            actor_id=authenticated_user_id,
            scan_id=data["scan_id"], scan_revision=data["scan_revision"],
            item_id=data["item_id"], item_revision=data["item_revision"],
            confirmed_name=data["name_zh"], idempotency_key=data["idempotency_key"],
        )
    except RateLimitExceeded:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("rate_limited", "Identity confirmation is rate limited"))
    except NutritionIdentityConfirmationError as error:
        return _enrichment_error_response(error)
    payload = deepcopy(result["result"])
    payload["confirmation_id"] = result["confirmation_id"]
    payload["replayed"] = result["replayed"]
    try:
        context = nutrition_scan_context_repository.get_scan_context(
            user_id=authenticated_user_id, scan_id=result["scan_id"],
            scan_revision=result["issued_scan_revision"], include_inactive=False)
        item = next((value for value in context["items"]
                     if value["item_id"] == result["item_id"]), None) if context else None
        if item is None:
            raise NutritionEnrichmentRouteError("stale_revision", "The confirmed scan revision is unavailable")
        local_lookup = make_local_nutrition_lookup(
            storage, TFDA_DB, authenticated_user_id, build_custom_food_search_result)
        local = local_lookup(item)
        payload["local_lookup"] = {
            "status": local.get("status"),
            "item": build_local_nutrition_item_result(item, local),
        }
    except (NutritionEnrichmentRouteError, ScanContextRepositoryError) as error:
        return _enrichment_error_response(error)
    except Exception:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("local_lookup_unavailable", "Local nutrition lookup is unavailable"))
    return jsonify(payload), 202


@app.route("/nutrition/fdc/candidates", methods=["POST", "GET"])
def fdc_candidate_references():
    """Search USDA from persisted scan identity or read its owner-bound snapshot."""
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("FDC 候選資料需要登入。", 401)
    if not fdc_candidate_route_enabled or fdc_candidate_search_service is None:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("feature_disabled", "FDC candidate search is not enabled"))

    try:
        if request.method == "POST":
            data = json_body(MAX_FORM_BYTES)
            if set(data) != {"scan_id", "scan_revision"}:
                raise NutritionEnrichmentRouteError(
                    "invalid_request", "Only scan_id and scan_revision are accepted")
            scan_id, scan_revision = data["scan_id"], data["scan_revision"]
        else:
            if set(request.args.keys()) != {"scan_id", "scan_revision"}:
                raise NutritionEnrichmentRouteError(
                    "invalid_request", "Only scan_id and scan_revision are accepted")
            scan_ids = request.args.getlist("scan_id")
            revisions = request.args.getlist("scan_revision")
            if len(scan_ids) != 1 or len(revisions) != 1:
                raise NutritionEnrichmentRouteError(
                    "invalid_request", "Scan references must be supplied once")
            scan_id = scan_ids[0]
            try:
                scan_revision = int(revisions[0])
            except (TypeError, ValueError) as error:
                raise NutritionEnrichmentRouteError("invalid_request", "scan_revision is invalid") from error

        if (not isinstance(scan_id, str) or not scan_id or scan_id.strip() != scan_id
                or type(scan_revision) is not int or scan_revision < 0):
            raise NutritionEnrichmentRouteError("invalid_request", "Server scan references are invalid")

        if request.method == "POST":
            _fdc_candidate_limiter.check(f"fdc-candidates:{authenticated_user_id}")
            document = fdc_candidate_search_service.create_snapshot(
                authenticated_user_id=authenticated_user_id,
                scan_id=scan_id,
                scan_revision=scan_revision,
            )
        else:
            document = fdc_candidate_search_service.get_snapshot(
                authenticated_user_id=authenticated_user_id,
                scan_id=scan_id,
                scan_revision=scan_revision,
            )
    except RateLimitExceeded:
        error = NutritionEnrichmentRouteError("rate_limited", "FDC candidate search is rate limited")
        return _enrichment_error_response(error)
    except (FdcCandidateSearchError, FdcCandidateSnapshotRepositoryError,
            NutritionEnrichmentRouteError) as error:
        return _enrichment_error_response(error)

    return jsonify(_fdc_candidate_reference_response(document))


@app.route("/nutrition/fdc/reviewed-selection", methods=["POST"])
def fdc_reviewed_selection():
    """Select reviewed references without Search or an implicit user decision."""
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("營養來源配對需要登入。", 401)
    if not fdc_reviewed_selection_route_enabled:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("feature_disabled", "Reviewed source selection is not enabled"))
    try:
        data = json_body(MAX_FORM_BYTES)
        if set(data) != {"scan_id", "scan_revision"}:
            raise NutritionEnrichmentRouteError(
                "invalid_request", "Only server scan references are accepted")
        _fdc_candidate_limiter.check(f"fdc-reviewed-selection:{authenticated_user_id}")
        document, selection = fdc_reviewed_selection_service.select(
            authenticated_user_id=authenticated_user_id, **data)
    except RateLimitExceeded:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("rate_limited", "Reviewed source selection is rate limited"))
    except (FdcReviewedSelectionError, FdcCandidateSnapshotRepositoryError,
            ScanContextRepositoryError, NutritionEnrichmentRouteError) as error:
        return _enrichment_error_response(error)
    response = _fdc_candidate_reference_response(document)
    response["selection"] = selection
    return jsonify(response)


def _require_official_nutrition_miss(*, user_id, scan_id, scan_revision, item):
    if any(NUTRITION_DATASET_HEALTH.get(source, {}).get("status") != "available"
           for source in ("TFDA", "USDA FNDDS")):
        raise NutritionEnrichmentRouteError(
            "local_unavailable", "Official nutrition databases are not available")
    # A configured reviewed source takes priority even if Search returned zero.
    if (fdc_reviewed_source_load_report["decision"] == "blocked"
            or fdc_reviewed_selection_service.registry.compatible(item)):
        raise NutritionEnrichmentRouteError(
            "official_nutrition_pending", "Reviewed USDA source selection is required")
    try:
        confirmed_miss = fdc_candidate_snapshot_repository.has_confirmed_search_miss(
            user_id=user_id, scan_id=scan_id, scan_revision=scan_revision, item_id=item["item_id"])
    except Exception as error:
        raise NutritionEnrichmentRouteError(
            "storage_unavailable", "Official lookup evidence could not be read") from error
    if not confirmed_miss:
        raise NutritionEnrichmentRouteError(
            "official_nutrition_pending", "A completed USDA FDC search is required")


@app.route("/nutrition/enrichment", methods=["POST"])
def nutrition_enrichment():
    # This route is intentionally independent from /predict/vision-food.  It
    # must authenticate before reading any server-owned scan or quota state.
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("營養補全需要登入。", 401)
    try:
        data = json_body(MAX_FORM_BYTES)
        result = process_enrichment_request(
            data,
            authenticated_user_id=authenticated_user_id,
            scan_context_repository=nutrition_scan_context_repository,
            profile_repository=nutrition_profile_repository,
            request_repository=nutrition_enrichment_repository,
            quota_repository=nutrition_quota_repository,
            cache_repository=nutrition_cache_repository,
            local_lookup=make_local_nutrition_lookup(
                storage, TFDA_DB, authenticated_user_id, build_custom_food_search_result),
            provider_factory=nutrition_enrichment_provider_factory,
            feature_enabled=nutrition_enrichment_route_enabled,
            authority_service=nutrition_authority_service,
            require_official_miss=_require_official_nutrition_miss,
        )
    except NutritionEnrichmentRouteError as error:
        return _enrichment_error_response(error)
    except NutritionEnrichmentCoordinatorError as error:
        return _enrichment_error_response(error)
    status = result.get("status")
    http_status = 202 if status == "pending" else 409 if status == "source_conflict" else 200
    response = jsonify({
        "status": status,
        "request_id": result.get("request_id"),
        "replayed": bool(result.get("replayed")),
        "result": result.get("result"),
        "error": result.get("error"),
    })
    if status in {"busy", "rate_limited"}:
        response.headers["Retry-After"] = "60"
        http_status = 429
    return response, http_status


@app.route("/nutrition/fdc/confirmation", methods=["POST"])
def fdc_candidate_confirmation():
    """Persist a user decision against a server-owned FDC snapshot.

    The request may contain a confirmation envelope and its digest, but never
    a candidate snapshot. The repository reloads the authenticated scan-bound
    snapshot and keeps a confirmed choice pending a new scan revision.
    """
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("FDC 候選確認需要登入。", 401)
    if not fdc_confirmation_route_enabled:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("feature_disabled", "FDC candidate confirmation is not enabled"))
    try:
        data = json_body(MAX_FORM_BYTES)
        allowed = {"user_id", "scan_id", "scan_revision", "idempotency_key", "confirmation"}
        if set(data) - allowed:
            raise NutritionEnrichmentRouteError("invalid_request", "Unsupported confirmation request fields")
        supplied_user_id = data.get("user_id")
        if supplied_user_id is not None and supplied_user_id != authenticated_user_id:
            raise NutritionEnrichmentRouteError("wrong_user", "Confirmation user does not match the authenticated user")
        required = ("scan_id", "scan_revision", "idempotency_key", "confirmation")
        if any(field not in data for field in required):
            raise NutritionEnrichmentRouteError("invalid_request", "Confirmation request fields are required")
        result = fdc_candidate_confirmation_repository.record_confirmation(
            authenticated_user_id=authenticated_user_id,
            actor_id=authenticated_user_id,
            scan_id=data["scan_id"],
            scan_revision=data["scan_revision"],
            idempotency_key=data["idempotency_key"],
            confirmation=data["confirmation"],
        )
    except FdcCandidateConfirmationRepositoryError as error:
        return _enrichment_error_response(error)
    except NutritionEnrichmentRouteError as error:
        return _enrichment_error_response(error)
    status = 202 if result.get("requires_detail_replay") else 200
    return jsonify({
        "status": result.get("status"),
        "confirmation_id": result.get("confirmation_id"),
        "scan_id": result.get("scan_id"),
        "scan_revision": result.get("scan_revision"),
        "issued_scan_revision": result.get("issued_scan_revision"),
        "requires_detail_replay": bool(result.get("requires_detail_replay")),
        "snapshot_digest": result.get("snapshot_digest"),
        "items": result.get("items"),
        "requires_new_scan_revision": bool(result.get("requires_new_scan_revision")),
        "photo_confidence_changed": bool(result.get("photo_confidence_changed")),
        "replayed": bool(result.get("replayed")),
    }), status


@app.route("/nutrition/fdc/detail", methods=["POST"])
def fdc_fixed_detail_replay():
    """Replay one confirmed FDC ID through the fixed USDA detail endpoint.

    The request identifies a durable confirmation and item only.  The FDC ID
    is loaded from the server-owned confirmation record, so clients cannot use
    this route as an arbitrary USDA proxy.  The route is disabled by default
    and intentionally stops at the bounded provider document; profile and
    portion writes belong to a later, separately gated stage.
    """
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("FDC Detail replay 需要登入。", 401)
    if not fdc_detail_route_enabled:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("feature_disabled", "FDC Detail replay is not enabled"))
    try:
        data = json_body(MAX_FORM_BYTES)
        allowed = {"confirmation_id", "scan_id", "issued_scan_revision", "item_id"}
        if set(data) != allowed:
            raise NutritionEnrichmentRouteError(
                "invalid_request", "confirmation_id, scan_id, issued_scan_revision and item_id are required")
        for field in ("confirmation_id", "scan_id", "item_id"):
            if not isinstance(data[field], str) or not data[field].strip() or len(data[field]) > 256:
                raise NutritionEnrichmentRouteError("invalid_request", f"{field} is invalid")
        if (isinstance(data["issued_scan_revision"], bool)
                or not isinstance(data["issued_scan_revision"], int)
                or data["issued_scan_revision"] < 0):
            raise NutritionEnrichmentRouteError("invalid_request", "issued_scan_revision is invalid")
        confirmation = fdc_candidate_confirmation_repository.get_confirmation(
            authenticated_user_id=authenticated_user_id,
            confirmation_id=data["confirmation_id"], scan_id=data["scan_id"],
            issued_scan_revision=data["issued_scan_revision"],
        )
        if confirmation is None:
            raise NutritionEnrichmentRouteError("detail_not_found", "The confirmation is unavailable")
        confirmed = next((item for item in confirmation["confirmed_items"]
                          if item.get("item_id") == data["item_id"]), None)
        if confirmed is None or not confirmed.get("confirmed_fdc_id"):
            raise NutritionEnrichmentRouteError(
                "confirmation_required", "The requested item has no confirmed FDC candidate")
        client = _build_fdc_detail_client()
        try:
            document = client.get_food(
                confirmed["confirmed_fdc_id"], deadline=time.monotonic() + 15)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        return jsonify({
            "status": "detail_retrieved",
            "confirmation_id": confirmation["confirmation_id"],
            "scan_id": confirmation["scan_id"],
            "issued_scan_revision": confirmation["issued_scan_revision"],
            "item_id": data["item_id"],
            "fdc_id": confirmed["confirmed_fdc_id"],
            "document": document,
            "photo_confidence_changed": False,
            "profile_written": False,
        }), 200
    except FdcCandidateConfirmationRepositoryError as error:
        return _enrichment_error_response(error)
    except FoodDataCentralClientError as error:
        code = "detail_not_found" if error.code == "not_found" else (
            "detail_invalid" if error.code in {"invalid_response", "response_mismatch"} else error.code)
        return _enrichment_error_response(NutritionEnrichmentRouteError(code, str(error)))
    except NutritionEnrichmentRouteError as error:
        return _enrichment_error_response(error)


@app.route("/nutrition/fdc/profile-preview", methods=["POST"])
def fdc_profile_preview():
    """Build and persist a server-owned FDC nutrition preview.

    The request contains only references to an authenticated confirmation and
    scan revision.  The provider document, policy, FDC ID, identity and
    weight are resolved on the server; client-supplied nutrition/profile
    payloads are never accepted at this boundary.
    """
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("FDC 營養預覽需要登入。", 401)
    if not fdc_profile_preview_route_enabled:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("feature_disabled", "FDC profile preview is not enabled"))
    try:
        data = json_body(MAX_FORM_BYTES)
        allowed = {"confirmation_id", "scan_id", "issued_scan_revision", "item_id"}
        if set(data) != allowed:
            raise NutritionEnrichmentRouteError(
                "invalid_request", "confirmation_id, scan_id, issued_scan_revision and item_id are required")
        for field in ("confirmation_id", "scan_id", "item_id"):
            value = data.get(field)
            if (not isinstance(value, str) or not value.strip() or len(value) > 256
                    or value.strip() != value):
                raise NutritionEnrichmentRouteError("invalid_request", f"{field} is invalid")
        revision = data.get("issued_scan_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise NutritionEnrichmentRouteError("invalid_request", "issued_scan_revision is invalid")
        if fdc_profile_preview_service is None or fdc_profile_preview_repository is None:
            raise NutritionEnrichmentRouteError("storage_unavailable", "FDC profile preview storage is unavailable")
        preview = fdc_profile_preview_service.preview(
            authenticated_user_id=authenticated_user_id,
            confirmation_id=data["confirmation_id"], scan_id=data["scan_id"],
            issued_scan_revision=revision, item_id=data["item_id"])
        saved = fdc_profile_preview_repository.save_preview(
            preview)
    except (FdcProfilePreviewError, FdcProfilePreviewRepositoryError) as error:
        return _enrichment_error_response(error)
    except NutritionEnrichmentRouteError as error:
        return _enrichment_error_response(error)
    result = {
        "nutrition_profile": saved.get("profile"),
        "portion": saved.get("portion"),
        "source_block": saved.get("source_block"),
        "recognition_identity": saved.get("recognition_identity"),
        "source_identity": saved.get("food_identity"),
    }
    return jsonify({
        "status": "preview_ready",
        "preview_id": saved["preview_id"],
        "confirmation_id": saved["confirmation_id"],
        "scan_id": saved["scan_id"],
        "issued_scan_revision": saved["issued_scan_revision"],
        "item_id": saved["item_id"],
        "item_revision": saved["item_revision"],
        "snapshot_digest": saved["snapshot_digest"],
        "source_id": saved["source_id"],
        "source_policy_revision": saved["source_policy_revision"],
        "fdc_id": saved["fdc_id"],
        "weight_g": saved["weight_g"],
        "preview": {
            "nutrition_profile": result["nutrition_profile"],
            "portion": result["portion"],
            "source_block": result["source_block"],
            "recognition_identity": result["recognition_identity"],
            "source_identity": result["source_identity"],
        },
        "photo_confidence_changed": False,
        "profile_written": False,
    }), 200


@app.route("/nutrition/fdc/profile-accept", methods=["POST"])
def fdc_profile_accept():
    """Accept a previously persisted preview using an idempotency key."""
    authenticated_user_id = require_authenticated_user()
    if authenticated_user_id is None:
        raise AuthError("FDC 營養資料寫入需要登入。", 401)
    if not fdc_profile_accept_route_enabled:
        return _enrichment_error_response(
            NutritionEnrichmentRouteError("feature_disabled", "FDC profile acceptance is not enabled"))
    try:
        data = json_body(MAX_FORM_BYTES)
        allowed = {"preview_id", "idempotency_key"}
        if set(data) != allowed:
            raise NutritionEnrichmentRouteError(
                "invalid_request", "preview_id and idempotency_key are required")
        for field in allowed:
            value = data.get(field)
            if not isinstance(value, str) or not value.strip() or value.strip() != value or len(value) > 256:
                raise NutritionEnrichmentRouteError("invalid_request", f"{field} is invalid")
        if fdc_profile_preview_repository is None:
            raise NutritionEnrichmentRouteError("storage_unavailable", "FDC profile preview storage is unavailable")
        result = fdc_profile_preview_repository.accept_preview(
            authenticated_user_id=authenticated_user_id,
            preview_id=data["preview_id"], idempotency_key=data["idempotency_key"])
    except FdcProfilePreviewRepositoryError as error:
        return _enrichment_error_response(error)
    except NutritionEnrichmentRouteError as error:
        return _enrichment_error_response(error)
    return jsonify({
        "status": result.get("status"),
        "preview_id": result.get("preview_id"),
        "profile": result.get("profile"),
        "portion": result.get("portion"),
        "profile_hash": result.get("profile_hash"),
        "replayed": bool(result.get("replayed")),
        "photo_confidence_changed": False,
        "profile_written": True,
    }), 200


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
    data = json_body(MAX_FORM_BYTES)
    if not data or "user_id" not in data:
        return jsonify({"error": "缺少 user_id"}), 400
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))
    enforce_rate_limit(_general_limiter, "write")

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


@app.errorhandler(NutritionProfileError)
def nutrition_contract_error(error):
    conflict = error.code in ("upgrade_required", "nutrition_flow_unavailable", "stale_revision", "legacy_conversion_required")
    messages = {
        "upgrade_required": "此紀錄使用新版營養資料格式，請更新應用程式後再讀取或修改",
        "nutrition_flow_unavailable": "此流程尚未支援新版營養缺值合約，請稍後再試",
        "stale_revision": "紀錄已更新，請重新讀取後再修改",
    }
    return jsonify({"error": messages.get(error.code, str(error)), "error_code": error.code,
                    "required_nutrition_contract_version": 2}), 409 if conflict else 400


def nutrition_contract_version(data=None):
    values = []
    if isinstance(data, dict) and "nutrition_contract_version" in data:
        value = data["nutrition_contract_version"]
        if type(value) is not int:
            raise NutritionProfileError("invalid_contract", "nutrition_contract_version must be an integer")
        values.append(value)
    for value in (request.args.get("nutrition_contract_version"), request.headers.get("X-Nutrition-Contract-Version")):
        if value is not None:
            if value not in ("1", "2"):
                raise NutritionProfileError("invalid_contract", "Unsupported nutrition contract version")
            values.append(int(value))
    if any(value not in (1, 2) for value in values) or len(set(values)) > 1:
        raise NutritionProfileError("invalid_contract", "Conflicting or unsupported nutrition contract versions")
    return values[0] if values else 1


def require_legacy_nutrition_flow(data=None):
    if nutrition_contract_version(data) == 2:
        raise NutritionProfileError("nutrition_flow_unavailable", "This flow has not completed v2 acceptance")


def require_record_reader(records, version):
    if version != 2 and any(record.get("nutrition_contract_version") == 2 for record in records):
        raise NutritionProfileError("upgrade_required", "A newer nutrition client is required")


def require_recommendation_nutrition(user_id, data=None):
    version = nutrition_contract_version(data)
    today = storage.get_today_records(user_id)
    require_record_reader(today, version)
    if any(record.get("nutrition_contract_version") == 2 for record in today):
        raise NutritionProfileError("nutrition_flow_unavailable", "Recommendations do not yet support v2 coverage")


def prepare_v2_record(data, existing=None):
    user_id = data["user_id"]

    def resolve_food(key):
        custom = storage.get_custom_food(key, user_id)
        source = build_custom_food_search_result(custom) if custom else TFDA_DB.get(key)
        if source is None:
            return None
        name = source.get("name_zh") or source.get("name") or key
        return {"name": name, "nutrition_profile": profile_from_local_food(source, source_details={
                    "source_type": "user_custom" if custom else source.get("source", "official_local"),
                    "food_key": key, "food_name": name,
                    "source_url": source.get("source_url"), "snapshot_scope": "local_database"}),
                "source": "user_custom" if custom else source.get("source", "official_local"),
                "is_fried": source.get("is_fried") is True,
                "allergens": source.get("allergens") or [], "gi": source.get("gi")}

    prepared = normalize_v2_record({**data, "nutrition_contract_version": 2}, existing=existing, resolve_food=resolve_food)
    user = storage.get_user(user_id) or {}
    items = [{"nutrients": {**food, "label": food["name"], "nutrition_contract_version": 2},
              "portion_g": food["weight_g"]} for food in prepared["foods"] if food.get("included", True)]
    risk = evaluate_meal_medical_risk(
        items, user.get("health_conditions") or [], user.get("allergens") or [], DISEASE_RULES,
        ALLERGEN_TAXONOMY, user_profile=user, nutrition_contract_version=2,
        nutrition_coverage=prepared["nutrition_context"]["coverage"])
    prepared["nutrition_context"]["medical_risk"] = risk
    return prepared


@app.route("/record/preview", methods=["POST"])
def preview_record():
    data = json_body(MAX_FORM_BYTES)
    if not isinstance(data, dict) or not data.get("user_id"):
        return jsonify({"error": "缺少 user_id"}), 400
    require_user_access(data["user_id"])
    enforce_rate_limit(_general_limiter, "write")
    if nutrition_contract_version(data) != 2:
        raise NutritionProfileError("upgrade_required", "Preview requires v2")
    existing = None
    if data.get("client_record_id"):
        existing = storage.get_record_by_client_record_id(data["user_id"], data["client_record_id"])
        if existing and existing.get("nutrition_contract_version") != 2:
            raise NutritionProfileError("legacy_conversion_required", "Legacy records require explicit conversion")
    return jsonify({"record": prepare_v2_record(data, existing=existing)})


def normalize_record_foods(foods):
    if not isinstance(foods, list) or not foods:
        raise ValueError("飲食紀錄至少需要一項食物")

    normalized_foods = []
    for food in foods:
        if not isinstance(food, dict):
            raise ValueError("食物資料格式錯誤")
        if "nutrition_profile" in food or "user_entered_nutrients" in food:
            raise NutritionProfileError("upgrade_required", "Canonical nutrition requires v2")
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
    data = json_body(MAX_FORM_BYTES)
    if not isinstance(data, dict):
        return jsonify({"error": "缺少資料"}), 400
    if not data.get("user_id"):
        return jsonify({"error": "缺少 user_id"}), 400
    if is_auth_required():
        data["user_id"] = require_user_access(data.get("user_id"))
    enforce_rate_limit(_general_limiter, "write")
    if not data.get("client_record_id"):
        data["client_record_id"] = f"server_record_{uuid.uuid4().hex}"

    version = nutrition_contract_version(data)
    existing = storage.get_record_by_client_record_id(data["user_id"], data["client_record_id"])
    if existing:
        require_record_reader([existing], version)
        return jsonify({"message": "飲食紀錄已存在", "record": existing, "deduplicated": True}), 200

    try:
        canonical = prepare_v2_record(data) if version == 2 else None
        if version == 1 and "nutrition_context" in data:
            raise NutritionProfileError("upgrade_required", "nutrition_context requires v2")
        foods = canonical["foods"] if canonical else normalize_record_foods(data.get("foods"))
        timestamp = normalize_record_timestamp(data.get("timestamp"))
    except NutritionProfileError:
        raise
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    totals = {
        nutrient: canonical[f"total_{nutrient}"] if canonical else round(sum(food[nutrient] for food in foods), 2)
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
    if canonical:
        record.update(canonical)

    saved_record = storage.insert_record(record)
    require_record_reader([saved_record], version)

    if saved_record.get("_deduplicated"):
        saved_record = {key: value for key, value in saved_record.items() if key != "_deduplicated"}
        return jsonify({"message": "飲食紀錄已存在", "record": saved_record, "deduplicated": True}), 200

    return jsonify({"message": "飲食紀錄已儲存", "record": saved_record, "deduplicated": False}), 201


@app.route("/records/<user_id>", methods=["GET"])
def get_records(user_id):
    require_user_access(user_id)
    version = nutrition_contract_version()
    date_str = request.args.get("date")  # YYYY-MM-DD
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "limit 與 offset 必須是有效數字"}), 400
    records = storage.get_records(user_id, date_str, limit=limit, offset=offset)
    require_record_reader(storage.get_all_records(user_id, date_str) if version == 1 else records, version)
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
    enforce_rate_limit(_general_limiter, "write")
    existing = storage.get_record_by_client_record_id(user_id, client_record_id)
    if not existing:
        return jsonify({"error": "找不到飲食紀錄"}), 404

    data = json_body(MAX_FORM_BYTES)
    if not isinstance(data, dict):
        return jsonify({"error": "缺少資料"}), 400
    version = nutrition_contract_version(data)
    require_record_reader([existing], version)
    if version == 2:
        if existing.get("nutrition_contract_version") != 2:
            raise NutritionProfileError("legacy_conversion_required", "Legacy records require explicit conversion")
        canonical = prepare_v2_record({**data, "user_id": user_id}, existing=existing)
        saved = storage.update_record({**existing, **canonical}, expected_revision=data["base_revision"])
        if not saved:
            raise NutritionProfileError("stale_revision", "Record changed; reload before editing")
        return jsonify({"message": "飲食紀錄已更新", "record": saved})
    try:
        foods = normalize_record_foods(data.get("foods"))
    except NutritionProfileError:
        raise
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
    saved = storage.update_record(updated, nutrition_contract_version=1)
    if not saved:
        return jsonify({"error": "找不到飲食紀錄"}), 404
    return jsonify({"message": "飲食紀錄已更新", "record": saved})


@app.route("/records/<user_id>/<client_record_id>", methods=["DELETE"])
def delete_record(user_id, client_record_id):
    require_user_access(user_id)
    enforce_rate_limit(_general_limiter, "write")
    existing = storage.get_record_by_client_record_id(user_id, client_record_id)
    require_record_reader([existing] if existing else [], nutrition_contract_version())
    deleted = storage.delete_record(user_id, client_record_id, nutrition_contract_version=nutrition_contract_version())
    if not deleted:
        return jsonify({"error": "找不到飲食紀錄"}), 404
    return jsonify({"message": "飲食紀錄已刪除", "record": deleted})


# ─── 3.5 附近店家菜單建檔（我的 → 附近店家菜單） ──────────────
def _venue_search_params(data: dict) -> dict:
    return {
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
    version = nutrition_contract_version()
    return jsonify(build_history_response(storage, user_id, days, nutrition_contract_version=version))


@app.route("/healthy-food-recommend/<user_id>", methods=["GET"])
def healthy_food_recommend(user_id):
    require_user_access(user_id)
    require_recommendation_nutrition(user_id)
    params = {
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
    require_recommendation_nutrition(user_id)
    # 每次都會打 Google Places
    enforce_rate_limit(_paid_api_limiter, "places")
    params = {
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


def check_menu_items(items: list, user: dict, context: dict) -> tuple[list, list]:
    """逐道菜判斷能不能吃：回傳（可以吃的，依契合度排序；不建議的，附原因）。

    可以吃的裡面 medical_risk.has_caution 為真的是「可以吃但要注意」。
    context 是每一筆都要帶的店家欄位（restaurant_id、restaurant_name…）。
    """
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
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        candidate = {
            "label": item.get("item_id", name),
            "name_zh": name,
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
        # evaluate_medical_risk 沒有 action 這個鍵，要看 block_reasons
        block_reasons = list(medical_risk.get("block_reasons", []))

        if block_reasons:
            filtered_items.append({
                "restaurant_id": context.get("restaurant_id"),
                "restaurant_name": context.get("restaurant_name"),
                "item_name": name,
                "reasons": block_reasons,
                "price": item.get("price", 0),
                "medical_risk": medical_risk,
            })
            continue

        base_score = 92 if medical_risk["is_safe"] and not medical_risk["has_caution"] else 78
        item_cal = float(item.get("calories", 0) or 0)
        cal_score = max(0, 10 - int(abs(target_calories - item_cal) / 40))
        prot = float(item.get("protein", 0) or 0)
        prot_bonus = 5 if prot >= 18 else 0
        sod = float(item.get("sodium", 0) or 0)
        sod_bonus = 3 if sod <= 600 else -5 if sod >= 1000 else 0
        match_score = min(99, max(1, base_score + cal_score + prot_bonus + sod_bonus))

        reasons = []
        if medical_risk.get("caution_reasons"):
            reasons.extend(medical_risk["caution_reasons"])
        else:
            reasons.append(f"熱量契合個人單餐目標 ({int(target_calories)} kcal)")
        if prot >= 18:
            reasons.append("高蛋白質補給")
        if sod <= 600:
            reasons.append("低鈉好選擇")

        recommended_items.append({
            **context,
            "item_id": item.get("item_id", name),
            "item_name": name,
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

    recommended_items.sort(key=lambda x: x["match_score"], reverse=True)
    return recommended_items, filtered_items


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
    require_recommendation_nutrition(data.get("user_id") or get_request_user_id() or "", data)
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
        print(f"[Scraper] 使用 AI（ChatGPT／Gemini）辨識 {name} 的實體菜單圖片")
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

    # 3. 逐道菜比對疾病禁忌與過敏原，並依個人單餐目標評分（user 在上面已經確認存在）
    recommended_items, filtered_items = check_menu_items(
        matched.get("items", []),
        user,
        {
            "restaurant_id": matched["restaurant_id"],
            "restaurant_name": matched["name"],
            "restaurant_lat": matched["lat"],
            "restaurant_lng": matched["lng"],
            "address": matched.get("address", ""),
            **({"distance_km": client_distance_km} if client_distance_km is not None else {}),
            "tags": matched["tags"],
        },
    )

    return jsonify({
        "restaurant_id": matched["restaurant_id"],
        "name": matched["name"],
        # 店家頁只放分數最高的 5 道
        "recommended_items": recommended_items[:5],
        "filtered_items": filtered_items,
        "menu_recognition": menu_recognition,
    })


@app.route("/menu/photo-check", methods=["POST"])
def menu_photo_check():
    """拍任何一張菜單，不用先選店家：列出上面每道菜能不能吃。

    跟 /restaurant/menu 用同一套逐道菜判斷，但回傳全部品項（不只前 5 名），
    結果只給這次的回應用，不寫進共用的菜單快取。
    """
    data = json_body()
    require_authenticated_user()
    enforce_rate_limit(_paid_api_limiter, "menu")
    if data.get("user_id"):
        require_user_access(data["user_id"])
    require_recommendation_nutrition(data.get("user_id") or get_request_user_id() or "", data)
    raw_image = data.get("menu_image")
    if not isinstance(raw_image, str) or not raw_image.strip():
        return jsonify({"error": "缺少菜單照片（menu_image，Base64）"}), 400

    user_id = data.get("user_id") or get_request_user_id() or ""
    user = storage.get_user(user_id)
    if not user:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404

    print("[MenuCheck] 使用 AI（ChatGPT／Gemini）辨識拍攝的菜單")
    enriched = parse_menu_image_with_gemini(raw_image.strip(), "菜單照片")
    recognition = {
        key: enriched[key]
        for key in ("recognition_status", "recognition_error", "recognition_model")
        if key in enriched
    }
    if enriched.get("recognition_status") == "error":
        return jsonify({
            "error": enriched.get("recognition_error") or "菜單辨識失敗，請稍後再試",
            "menu_recognition": recognition,
        }), 502

    edible, not_recommended = check_menu_items(
        enriched.get("items", []) or [],
        user,
        {"restaurant_id": "menu_photo", "restaurant_name": "拍攝的菜單", "tags": ["實體菜單辨識", "AI標記"]},
    )
    safe = [item for item in edible if not item["medical_risk"].get("has_caution")]
    caution = [item for item in edible if item["medical_risk"].get("has_caution")]
    return jsonify({
        "safe_items": safe,
        "caution_items": caution,
        "not_recommended_items": not_recommended,
        "total_items": len(edible) + len(not_recommended),
        "menu_recognition": recognition,
        "disclaimer": "營養數字是 AI 依菜名估算的，僅供參考，不能取代醫師或營養師的建議。",
    })


@app.route("/map-food-recommend/<user_id>/restaurant-summary", methods=["POST"])
def map_food_restaurant_summary(user_id):
    require_user_access(user_id)
    require_recommendation_nutrition(user_id, request.get_json(silent=True))
    # 每點一家店就打一次 Gemini
    enforce_rate_limit(_paid_api_limiter, "summary")
    user = storage.get_user(user_id)
    if not user:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404

    data = json_body()
    restaurant = data.get("restaurant") or {}
    if not restaurant.get("name"):
        return jsonify({"error": "缺少 restaurant.name"}), 400
    category = data.get("category") or "all"
    try:
        nutrition_progress = build_daily_nutrition_progress(storage, user_id, user)
        summary = build_restaurant_ai_summary(
            restaurant,
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


# 透過 Tailscale Funnel 從外面連只有約 200 KB/s，2 MB 的 JS 不壓縮要十幾秒，手機常常逾時。
# 文字檔 gzip 後大約剩四分之一；壓好的結果依檔案修改時間快取在記憶體，不用每次重壓。
GZIP_EXTENSIONS = {".js", ".css", ".html", ".json", ".svg", ".map", ".txt", ".ttf", ".otf"}
GZIP_MIN_BYTES = 1024
_gzip_cache: dict[str, tuple[int, bytes]] = {}


def gzipped_file(full_path: str) -> bytes:
    stamp = os.stat(full_path).st_mtime_ns
    cached = _gzip_cache.get(full_path)
    if cached and cached[0] == stamp:
        return cached[1]
    with open(full_path, "rb") as f:
        data = gzip.compress(f.read(), compresslevel=6)
    _gzip_cache[full_path] = (stamp, data)
    return data


def compress_frontend_response(response, name: str):
    full = safe_join(FRONTEND_DIST, name)
    if (
        response.status_code != 200
        or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
        or os.path.splitext(name)[1].lower() not in GZIP_EXTENSIONS
        or not full
        or os.path.getsize(full) < GZIP_MIN_BYTES
    ):
        return response
    data = gzipped_file(full)
    etag, _ = response.get_etag()
    response.close()  # 放掉 send_from_directory 開著的原始檔
    response.direct_passthrough = False
    response.set_data(data)
    response.headers["Content-Encoding"] = "gzip"
    response.headers.pop("Accept-Ranges", None)
    response.vary.add("Accept-Encoding")
    if etag:
        # 壓縮後位元組不同，標成 weak；瀏覽器帶回來比對仍會得到 304
        response.set_etag(etag, weak=True)
    return response


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
    response = compress_frontend_response(send_from_directory(FRONTEND_DIST, found), found)
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
    Tailscale Funnel 與 cloudflared 從本機轉入，不需要 --lan。
    """
    if wants_lan(argv, environ):
        return "0.0.0.0"
    return "127.0.0.1"


def start_auto_backup():
    """後端開著時定時備份本機的 SQLite 檔。

    只用記憶體時沒有檔案可以備份。
    """
    if not database_path or database_path == ":memory:":
        return None
    backup = auto_backup_from_env(database_path)
    if backup is None:
        print("[INFO] 自動備份已關閉（AUTO_BACKUP_HOURS=0），要備份請手動執行 backend/scripts/backup_db.py")
        return None
    hours = backup.interval.total_seconds() / 3600
    print(f"[OK] 自動備份：每 {hours:g} 小時一次，留最近 {backup.keep} 份，放在 {backup.backup_dir}")
    if backup.copy_dir:
        print(f"     另外複製一份到 {backup.copy_dir}")
    backup.start()
    return backup


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
    # 除錯模式會另開一個子程序來自動重新載入，只在那個子程序裡備份，不然每次都備兩份
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_auto_backup()
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
