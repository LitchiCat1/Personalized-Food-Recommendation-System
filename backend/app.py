"""
NutriLens Backend — Flask API
PRD-aligned: YOLO detection + nutrition analysis + user management + recommendations
"""

import base64
import json
import math
import os
import uuid
from datetime import datetime

import cv2
import numpy as np
import psycopg2
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from ultralytics import YOLO
from repositories.storage import StorageRepository
from services.disease_rule_service import load_disease_rules
from services.env_service import load_local_env
from services.history_service import build_history_response
from services.healthy_food_service import build_healthy_food_recommendations
from services.food_service import build_custom_food_doc, search_foods
from services.nutrition_label_service import (
    build_custom_food_search_result,
    call_gemini_nutrition_ocr,
    detect_image_mime,
    extract_number,
    normalize_nutrition_payload,
    normalize_ocr_result,
    scale_nutrition_per_100g,
)
from services.predict_service import predict_from_image
from services.profile_service import build_bmr_response, build_user_profile
from services.recommend_service import build_recommendation_response
from yolo_tfda_mapping import YOLO_MANUAL_SEARCH_HINTS, YOLO_TO_TFDA


load_local_env()
BASE_DIR = os.path.dirname(__file__)

pg_conn = None
database_url = os.environ.get("DATABASE_URL")
if database_url:
    try:
        pg_conn = psycopg2.connect(database_url, sslmode="require")
        pg_conn.autocommit = True
        print("[✓] PostgreSQL connected")
    except Exception as e:
        pg_conn = None
        print(f"[!] PostgreSQL unavailable — {e}")

# ─── Optional MongoDB (graceful fallback to in-memory) ────────
try:
    from pymongo import MongoClient
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    mongo.server_info()  # trigger connection check
    db = mongo["nutrilens"]
    USE_MONGO = True
    print("[✓] MongoDB connected")
except Exception:
    USE_MONGO = False
    db = None
    print("[!] MongoDB unavailable — using in-memory storage")

# ─── In-memory fallback storage ──────────────────────────────
_mem_users = {}
_mem_records = []
_mem_custom_foods = []
storage = StorageRepository(db, USE_MONGO, _mem_users, _mem_records, _mem_custom_foods, pg_conn=pg_conn)

app = Flask(__name__)
CORS(app)

# ─── Load YOLO model ─────────────────────────────────────────
MODEL_PATH = os.path.join(BASE_DIR, "yolov8n.pt")
model = None


def get_model():
    global model
    if model is None:
        print("[ ] Loading YOLO model...")
        model = YOLO(MODEL_PATH)
        print("[✓] YOLO model loaded")
    return model

# ─── Load nutrition databases ────────────────────────────────
# 1. Original hand-crafted DB (YOLO label → nutrients)
DB_PATH = os.path.join(BASE_DIR, "nutrition_db.json")
with open(DB_PATH, "r", encoding="utf-8") as f:
    NUTRITION_DB = json.load(f)

# 2. TFDA 衛福部食品營養成分資料庫 (2,181 筆台灣食品)
TFDA_PATH = os.path.join(BASE_DIR, "nutrition_db_tw.json")
try:
    with open(TFDA_PATH, "r", encoding="utf-8") as f:
        TFDA_DB = json.load(f)
    print(f"[✓] TFDA nutrition DB loaded: {len(TFDA_DB)} foods")
except FileNotFoundError:
    TFDA_DB = {}
    print("[!] TFDA nutrition_db_tw.json not found — using fallback only")

# ─── Disease filter rules (PRD: 硬性排除規則) ────────────────
DISEASE_RULES = load_disease_rules(BASE_DIR)
print(f"[✓] Disease rules loaded: {len(DISEASE_RULES)} conditions")


# ═══════════════════════════════════════════════════════════════
#  API Routes
# ═══════════════════════════════════════════════════════════════


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "postgres": pg_conn is not None,
        "mongo": USE_MONGO,
        "model": "yolov8n",
        "model_loaded": model is not None,
        "foods_in_db": len(NUTRITION_DB),
        "foods_in_tfda": len(TFDA_DB),
        "disease_rules": len(DISEASE_RULES),
        "custom_foods": len(storage.get_custom_foods()),
    })


@app.route("/warmup", methods=["POST"])
def warmup():
    get_model()
    return jsonify({"status": "ok", "model_loaded": True})


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
    results = search_foods(storage, TFDA_DB, q, limit, user_id, build_custom_food_search_result)
    return jsonify({"query": q, "results": results, "count": len(results)})


# ─── 0.5 Food Detail (TFDA 單筆食品完整資料) ─────────────────
@app.route("/food/<path:food_key>", methods=["GET"])
def get_food_detail(food_key):
    """取得 TFDA 單筆食品完整營養資訊"""
    custom_food = storage.get_custom_food(food_key)
    if custom_food:
        return jsonify(custom_food)

    food = TFDA_DB.get(food_key)
    if not food:
        return jsonify({"error": f"找不到食品: {food_key}"}), 404
    return jsonify(food)


@app.route("/custom-food", methods=["POST"])
def create_custom_food():
    data = request.get_json(silent=True) or {}
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
    foods = storage.get_custom_foods(user_id)
    return jsonify({"foods": foods, "count": len(foods)})


@app.route("/ocr/nutrition-label", methods=["POST"])
def ocr_nutrition_label():
    data = request.get_json(silent=True) or {}
    if "image" not in data:
        return jsonify({"error": "缺少 image 欄位（Base64）"}), 400

    api_key = data.get("api_key") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({"error": "缺少 Gemini API key，請設定 GEMINI_API_KEY 環境變數"}), 400

    try:
        img_bytes = base64.b64decode(data["image"])
        mime_type = detect_image_mime(img_bytes)
        parsed = call_gemini_nutrition_ocr(data["image"], mime_type, api_key)
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


# ─── 1. Image Detection (PRD: 即時影像辨識) ──────────────────
@app.route("/predict", methods=["POST"])
def predict():
    data = request.get_json(silent=True)
    if not data or "image" not in data:
        return jsonify({"error": "缺少 image 欄位（Base64）"}), 400

    user_conditions = data.get("health_conditions", [])
    user_allergens = data.get("allergens", [])

    try:
        img_bytes = base64.b64decode(data["image"])
        img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({"error": "圖片解碼失敗"}), 400

        return jsonify(
            predict_from_image(
                get_model(),
                img,
                user_conditions,
                user_allergens,
                YOLO_TO_TFDA,
                TFDA_DB,
                NUTRITION_DB,
                DISEASE_RULES,
                YOLO_MANUAL_SEARCH_HINTS,
            )
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 2. User Profile CRUD (PRD: 健康檔案與疾病管理) ──────────
@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    user = storage.get_user(user_id)

    if not user:
        return jsonify({"error": "使用者不存在"}), 404
    return jsonify(user)


@app.route("/user", methods=["POST"])
def create_or_update_user():
    data = request.get_json()
    if not data or "user_id" not in data:
        return jsonify({"error": "缺少 user_id"}), 400

    user_doc = build_user_profile(data)

    storage.upsert_user(user_doc)

    return jsonify({"message": "使用者資料已更新", "user": user_doc})


# ─── 3. Dietary Records (PRD: 飲食紀錄) ──────────────────────
@app.route("/record", methods=["POST"])
def add_record():
    data = request.get_json()
    if not data:
        return jsonify({"error": "缺少資料"}), 400

    record = {
        "user_id": data.get("user_id"),
        "timestamp": data.get("timestamp", datetime.utcnow().isoformat()),
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

    storage.insert_record(record)

    return jsonify({"message": "飲食紀錄已儲存", "record": record}), 201


@app.route("/records/<user_id>", methods=["GET"])
def get_records(user_id):
    date_str = request.args.get("date")  # YYYY-MM-DD
    records = storage.get_records(user_id, date_str, limit=50)
    return jsonify({"records": records, "count": len(records)})


# ─── 4. History & Trends (PRD: 飲食趨勢回顧) ─────────────────
@app.route("/history/<user_id>", methods=["GET"])
def get_history(user_id):
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
    result = build_recommendation_response(storage, NUTRITION_DB, TFDA_DB, DISEASE_RULES, user_id)
    if not result:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404
    return jsonify(result)


@app.route("/healthy-food-recommend/<user_id>", methods=["GET"])
def healthy_food_recommend(user_id):
    params = {
        "budget": request.args.get("budget", 150),
        "lat": request.args.get("lat", 25.0338),
        "lng": request.args.get("lng", 121.5645),
    }
    result = build_healthy_food_recommendations(storage, DISEASE_RULES, user_id, params)
    if not result:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404
    return jsonify(result)


# ─── 6. BMR/TDEE Calculator (PRD: 動態計算) ─────────────────
@app.route("/calculate/bmr", methods=["POST"])
def calc_bmr():
    data = request.get_json()
    return jsonify(build_bmr_response(data))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
