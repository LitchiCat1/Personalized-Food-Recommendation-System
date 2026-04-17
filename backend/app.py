"""
NutriLens Backend — Flask API
PRD-aligned: YOLO detection + nutrition analysis + user management + recommendations
"""

import base64
import json
import math
import os
from datetime import datetime, timedelta

import cv2
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
from ultralytics import YOLO

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

app = Flask(__name__)
CORS(app)

# ─── Load YOLO model ─────────────────────────────────────────
MODEL_PATH = os.path.join(os.path.dirname(__file__), "yolov8n.pt")
model = YOLO(MODEL_PATH)

# ─── Load nutrition database ─────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "nutrition_db.json")
with open(DB_PATH, "r", encoding="utf-8") as f:
    NUTRITION_DB = json.load(f)

UNKNOWN_NUTRIENTS = {
    "name_zh": "未知食物",
    "calories": None,
    "protein": None,
    "fat": None,
    "carbs": None,
    "sodium": None,
    "fiber": None,
    "gi": None,
    "allergens": [],
    "unit": None,
    "density": 0.80,
    "note": "資料庫中無此食物",
}

# ─── Disease filter rules (PRD: 硬性排除規則) ────────────────
DISEASE_RULES = {
    "糖尿病": {
        "blocked_gi": ["high"],
        "max_carbs_per_meal": 60,  # grams
        "description": "限制高 GI、控醣",
    },
    "高血壓": {
        "max_sodium_per_meal": 600,  # mg
        "description": "限制鈉攝取 < 2000mg/日",
    },
    "慢性腎臟病": {
        "max_protein_per_meal": 40,  # grams
        "description": "限制蛋白質、磷、鉀",
    },
    "痛風": {
        "blocked_labels": ["hot dog"],
        "description": "限制高普林食物",
    },
    "高血脂": {
        "max_fat_per_meal": 20,  # grams
        "description": "限制飽和脂肪、膽固醇",
    },
}


def get_nutrients(label: str) -> dict:
    """查詢營養資料庫"""
    return NUTRITION_DB.get(label.lower(), UNKNOWN_NUTRIENTS)


def estimate_weight(bbox_w: float, bbox_h: float, img_w: int, img_h: int, density: float) -> float:
    """
    PRD: 邊界框份量估算
    Rough volume estimation based on bounding box area and reference density.
    Returns estimated weight in grams.
    """
    pixel_area = (bbox_w * img_w) * (bbox_h * img_h)
    # Reference: 640x640 image, 100g food ≈ 15000 px² at 0.8 density
    ref_area = 15000
    estimated_volume = (pixel_area / ref_area) * 100  # cm³
    return round(estimated_volume * density, 1)


def compute_bmr(gender: str, weight: float, height: float, age: int) -> float:
    """PRD: Mifflin-St Jeor BMR 計算"""
    if gender == "male":
        return round(10 * weight + 6.25 * height - 5 * age + 5)
    else:
        return round(10 * weight + 6.25 * height - 5 * age - 161)


def compute_tdee(bmr: float, activity_multiplier: float) -> float:
    """PRD: TDEE = BMR × 活動量係數"""
    return round(bmr * activity_multiplier)


def check_food_safety(nutrients: dict, weight_g: float, user_conditions: list, user_allergens: list) -> list:
    """
    PRD: 安全過濾層 — 檢查食物是否符合使用者健康限制
    Returns list of warning strings
    """
    warnings = []
    if not nutrients.get("calories"):
        return warnings

    scale = weight_g / 100.0
    actual_sodium = (nutrients.get("sodium") or 0) * scale
    actual_carbs = (nutrients.get("carbs") or 0) * scale
    actual_protein = (nutrients.get("protein") or 0) * scale
    actual_fat = (nutrients.get("fat") or 0) * scale
    gi = nutrients.get("gi")
    food_allergens = nutrients.get("allergens", [])

    # Check allergens
    for a in food_allergens:
        if a in user_allergens:
            warnings.append(f"含過敏原: {a}")

    # Check disease rules
    for condition in user_conditions:
        rules = DISEASE_RULES.get(condition, {})

        if "blocked_gi" in rules and gi in rules["blocked_gi"]:
            warnings.append(f"高 GI 食物 — {condition}患者請注意")

        if "max_sodium_per_meal" in rules and actual_sodium > rules["max_sodium_per_meal"]:
            warnings.append(f"高鈉 ({actual_sodium:.0f}mg) — {condition}患者請注意")

        if "max_carbs_per_meal" in rules and actual_carbs > rules["max_carbs_per_meal"]:
            warnings.append(f"碳水過高 ({actual_carbs:.0f}g) — {condition}患者請注意")

        if "max_protein_per_meal" in rules and actual_protein > rules["max_protein_per_meal"]:
            warnings.append(f"蛋白質過高 ({actual_protein:.0f}g) — {condition}患者請注意")

        if "max_fat_per_meal" in rules and actual_fat > rules["max_fat_per_meal"]:
            warnings.append(f"脂肪過高 ({actual_fat:.0f}g) — {condition}患者請注意")

    return warnings


# ═══════════════════════════════════════════════════════════════
#  API Routes
# ═══════════════════════════════════════════════════════════════


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "mongo": USE_MONGO,
        "model": "yolov8n",
        "foods_in_db": len(NUTRITION_DB),
    })


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

        img_h, img_w = img.shape[:2]
        results = model.predict(source=img, verbose=False)

        detections = []
        total_calories = 0
        total_sodium = 0

        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            label = model.names[cls_id]
            confidence = round(float(box.conf[0]), 4)

            # PRD: Bounding Box 座標
            xyxy = box.xyxy[0].tolist()
            x1, y1, x2, y2 = xyxy
            bbox = {
                "x": round(x1 / img_w, 4),
                "y": round(y1 / img_h, 4),
                "w": round((x2 - x1) / img_w, 4),
                "h": round((y2 - y1) / img_h, 4),
            }

            nutrients = get_nutrients(label)
            density = nutrients.get("density", 0.80)

            # PRD: 份量估算
            estimated_weight = estimate_weight(
                bbox["w"], bbox["h"], img_w, img_h, density
            )

            # Scale nutrients by estimated weight
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

            # PRD: 安全檢查
            safety_warnings = check_food_safety(
                nutrients, estimated_weight, user_conditions, user_allergens
            )

            detections.append({
                "label": label,
                "name_zh": nutrients.get("name_zh", label),
                "confidence": confidence,
                "bounding_box": bbox,
                "estimated_weight_g": estimated_weight,
                "nutrition": scaled_nutrition,
                "gi": nutrients.get("gi"),
                "allergens": nutrients.get("allergens", []),
                "warnings": safety_warnings,
            })

        return jsonify({
            "detections": detections,
            "summary": {
                "total_items": len(detections),
                "total_calories": total_calories,
                "total_sodium": total_sodium,
            },
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 2. User Profile CRUD (PRD: 健康檔案與疾病管理) ──────────
@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    if USE_MONGO:
        user = db.users.find_one({"user_id": user_id}, {"_id": 0})
    else:
        user = _mem_users.get(user_id)

    if not user:
        return jsonify({"error": "使用者不存在"}), 404
    return jsonify(user)


@app.route("/user", methods=["POST"])
def create_or_update_user():
    data = request.get_json()
    if not data or "user_id" not in data:
        return jsonify({"error": "缺少 user_id"}), 400

    user_id = data["user_id"]

    # PRD: 動態計算 BMR/TDEE
    gender = data.get("gender", "male")
    weight = data.get("weight", 70)
    height = data.get("height", 170)
    age = data.get("age", 25)
    activity_multiplier = data.get("activity_multiplier", 1.55)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity_multiplier)

    user_doc = {
        "user_id": user_id,
        "name": data.get("name", ""),
        "gender": gender,
        "height": height,
        "weight": weight,
        "age": age,
        "activity_level": data.get("activity_level", "中等活動量"),
        "activity_multiplier": activity_multiplier,
        "bmi": round(weight / ((height / 100) ** 2), 1),
        # PRD computed values
        "bmr": bmr,
        "tdee": tdee,
        "daily_calorie_target": data.get("daily_calorie_target", tdee),
        # PRD: 疾病標籤
        "health_conditions": data.get("health_conditions", []),
        # PRD: 過敏原
        "allergens": data.get("allergens", []),
        # Diet goals
        "target_weight": data.get("target_weight"),
        "diet_type": data.get("diet_type", "均衡飲食"),
        "updated_at": datetime.utcnow().isoformat(),
    }

    if USE_MONGO:
        db.users.update_one(
            {"user_id": user_id}, {"$set": user_doc}, upsert=True
        )
    else:
        _mem_users[user_id] = user_doc

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

    if USE_MONGO:
        db.records.insert_one(record)
        record.pop("_id", None)
    else:
        _mem_records.append(record)

    return jsonify({"message": "飲食紀錄已儲存", "record": record}), 201


@app.route("/records/<user_id>", methods=["GET"])
def get_records(user_id):
    date_str = request.args.get("date")  # YYYY-MM-DD

    if USE_MONGO:
        query = {"user_id": user_id}
        if date_str:
            query["timestamp"] = {"$regex": f"^{date_str}"}
        records = list(db.records.find(query, {"_id": 0}).sort("timestamp", -1).limit(50))
    else:
        records = [r for r in _mem_records if r["user_id"] == user_id]
        if date_str:
            records = [r for r in records if r["timestamp"].startswith(date_str)]

    return jsonify({"records": records, "count": len(records)})


# ─── 4. History & Trends (PRD: 飲食趨勢回顧) ─────────────────
@app.route("/history/<user_id>", methods=["GET"])
def get_history(user_id):
    days = int(request.args.get("days", 7))
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    if USE_MONGO:
        pipeline = [
            {
                "$match": {
                    "user_id": user_id,
                    "timestamp": {
                        "$gte": start_date.strftime("%Y-%m-%d"),
                        "$lte": end_date.strftime("%Y-%m-%d") + "T23:59:59",
                    },
                }
            },
            {
                "$group": {
                    "_id": {"$substr": ["$timestamp", 0, 10]},
                    "calories": {"$sum": "$total_calories"},
                    "protein": {"$sum": "$total_protein"},
                    "carbs": {"$sum": "$total_carbs"},
                    "fat": {"$sum": "$total_fat"},
                    "sodium": {"$sum": "$total_sodium"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        daily = list(db.records.aggregate(pipeline))
        daily_data = [
            {
                "date": d["_id"],
                "calories": d["calories"],
                "protein": d["protein"],
                "carbs": d["carbs"],
                "fat": d["fat"],
                "sodium": d["sodium"],
            }
            for d in daily
        ]
    else:
        # In-memory aggregation
        from collections import defaultdict
        agg = defaultdict(lambda: {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "sodium": 0})
        for r in _mem_records:
            if r["user_id"] != user_id:
                continue
            day = r["timestamp"][:10]
            agg[day]["calories"] += r.get("total_calories", 0)
            agg[day]["protein"] += r.get("total_protein", 0)
            agg[day]["carbs"] += r.get("total_carbs", 0)
            agg[day]["fat"] += r.get("total_fat", 0)
            agg[day]["sodium"] += r.get("total_sodium", 0)
        daily_data = [{"date": k, **v} for k, v in sorted(agg.items())]

    # Compute averages
    if daily_data:
        n = len(daily_data)
        avg = {
            "avg_calories": round(sum(d["calories"] for d in daily_data) / n),
            "avg_protein": round(sum(d["protein"] for d in daily_data) / n),
            "avg_carbs": round(sum(d["carbs"] for d in daily_data) / n),
            "avg_fat": round(sum(d["fat"] for d in daily_data) / n),
            "avg_sodium": round(sum(d["sodium"] for d in daily_data) / n),
        }
    else:
        avg = {}

    return jsonify({
        "user_id": user_id,
        "days": days,
        "daily": daily_data,
        "summary": avg,
    })


# ─── 5. Recommendations (PRD: 個人化雙軌推薦引擎) ────────────
@app.route("/recommend/<user_id>", methods=["GET"])
def recommend(user_id):
    """
    雙軌推薦:
    1. 安全過濾層: 根據疾病禁忌排除不安全食物
    2. 口味排序層: 餘弦相似度 (placeholder, 目前用隨機分數)
    """
    # Get user profile
    if USE_MONGO:
        user = db.users.find_one({"user_id": user_id}, {"_id": 0})
    else:
        user = _mem_users.get(user_id)

    if not user:
        return jsonify({"error": "使用者不存在，請先建立 profile"}), 404

    conditions = user.get("health_conditions", [])
    allergens = user.get("allergens", [])
    daily_target = user.get("daily_calorie_target", 2100)

    # TODO: 從今日已攝取紀錄計算剩餘配額
    remaining_calories = daily_target  # placeholder

    # Build candidate pool from nutrition DB
    safe_candidates = []
    filtered_out = []

    for label, nutrients in NUTRITION_DB.items():
        food_allergens = nutrients.get("allergens", [])
        gi = nutrients.get("gi")
        is_safe = True
        block_reasons = []

        # Check allergens
        for a in food_allergens:
            if a in allergens:
                is_safe = False
                block_reasons.append(f"含過敏原: {a}")

        # Check disease rules
        for condition in conditions:
            rules = DISEASE_RULES.get(condition, {})
            if "blocked_gi" in rules and gi in rules["blocked_gi"]:
                is_safe = False
                block_reasons.append(f"高 GI — 不適合{condition}患者")
            if "max_sodium_per_meal" in rules and (nutrients.get("sodium") or 0) > rules["max_sodium_per_meal"]:
                is_safe = False
                block_reasons.append(f"高鈉 — 不適合{condition}患者")
            if "blocked_labels" in rules and label in rules["blocked_labels"]:
                is_safe = False
                block_reasons.append(f"不適合{condition}患者")

        if is_safe:
            safe_candidates.append({
                "label": label,
                "name_zh": nutrients.get("name_zh", label),
                "calories": nutrients["calories"],
                "protein": nutrients.get("protein", 0),
                "carbs": nutrients.get("carbs", 0),
                "fat": nutrients.get("fat", 0),
                "sodium": nutrients.get("sodium", 0),
                "gi": gi,
                "match_score": 0,  # placeholder for cosine similarity
            })
        else:
            filtered_out.append({
                "label": label,
                "name_zh": nutrients.get("name_zh", label),
                "reasons": block_reasons,
            })

    # PRD: 口味排序層 (placeholder — 實際需要偏好向量)
    import random
    for c in safe_candidates:
        c["match_score"] = random.randint(60, 98)
    safe_candidates.sort(key=lambda x: x["match_score"], reverse=True)

    return jsonify({
        "user_id": user_id,
        "remaining_calories": remaining_calories,
        "health_conditions": conditions,
        "recommended": safe_candidates[:10],
        "filtered_out": filtered_out,
        "total_candidates": len(safe_candidates),
        "total_filtered": len(filtered_out),
    })


# ─── 6. BMR/TDEE Calculator (PRD: 動態計算) ─────────────────
@app.route("/calculate/bmr", methods=["POST"])
def calc_bmr():
    data = request.get_json()
    gender = data.get("gender", "male")
    weight = data.get("weight", 70)
    height = data.get("height", 170)
    age = data.get("age", 25)
    activity = data.get("activity_multiplier", 1.55)

    bmr = compute_bmr(gender, weight, height, age)
    tdee = compute_tdee(bmr, activity)

    return jsonify({
        "bmr": bmr,
        "tdee": tdee,
        "formula": "Mifflin-St Jeor",
        "gender": gender,
        "bmi": round(weight / ((height / 100) ** 2), 1),
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
