import base64
import json
import os
import numpy as np
import cv2
from flask import Flask, request, jsonify
from flask_cors import CORS
from ultralytics import YOLO

app = Flask(__name__)
CORS(app)

model = YOLO('yolov8n.pt')

# 啟動時載入營養資料庫
DB_PATH = os.path.join(os.path.dirname(__file__), 'nutrition_db.json')
with open(DB_PATH, 'r', encoding='utf-8') as f:
    NUTRITION_DB = json.load(f)

UNKNOWN_NUTRIENTS = {
    "calories": None,
    "protein": None,
    "fat": None,
    "carbs": None,
    "unit": None,
    "note": "資料庫中無此食物"
}


def get_nutrients(label: str) -> dict:
    """查詢營養資料庫，找不到時回傳 UNKNOWN_NUTRIENTS。"""
    return NUTRITION_DB.get(label.lower(), UNKNOWN_NUTRIENTS)


@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json(silent=True)
    if not data or 'image' not in data:
        return jsonify({"error": "缺少 image 欄位（Base64）"}), 400

    try:
        # Base64 解碼 → numpy array
        img_bytes = base64.b64decode(data['image'])
        img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({"error": "圖片解碼失敗"}), 400

        # YOLO 推論
        results = model.predict(source=img, verbose=False)

        detections = []
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            label = model.names[cls_id]
            confidence = round(float(box.conf[0]), 4)
            detections.append({
                "label": label,
                "confidence": confidence,
                "nutrients": get_nutrients(label),
            })

        return jsonify({"detections": detections})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
