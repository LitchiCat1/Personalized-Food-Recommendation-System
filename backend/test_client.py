import base64
import json
import sys
import requests

API_URL = "http://127.0.0.1:5000/predict"
IMAGE_PATH = "food.jpg"


def main():
    # 讀取圖片 → Base64
    try:
        with open(IMAGE_PATH, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
    except FileNotFoundError:
        print(f"[錯誤] 找不到 {IMAGE_PATH}，請把食物圖片放在同目錄下")
        sys.exit(1)

    # POST 到後端
    print(f"正在傳送 {IMAGE_PATH} 到 {API_URL} ...\n")
    try:
        resp = requests.post(API_URL, json={"image": img_b64}, timeout=30)
    except requests.ConnectionError:
        print("[錯誤] 無法連線後端，請確認 app.py 已啟動")
        sys.exit(1)

    data = resp.json()
    print("=== 原始 JSON 回傳 ===")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print()

    # 畫表格
    detections = data.get("detections", [])
    if not detections:
        print("未偵測到任何物體。")
        return

    header = f"{'#':<4} {'Label':<20} {'Confidence':<12} {'Cal':<8} {'Protein':<8} {'Fat':<8} {'Carbs':<8}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for i, det in enumerate(detections, 1):
        n = det.get("nutrients", {})
        print(
            f"{i:<4} "
            f"{det['label']:<20} "
            f"{det['confidence']:<12.4f} "
            f"{n.get('calories', '-'):<8} "
            f"{n.get('protein', '-'):<8} "
            f"{n.get('fat', '-'):<8} "
            f"{n.get('carbs', '-'):<8}"
        )
    print(sep)
    print(f"共偵測到 {len(detections)} 個物體")


if __name__ == "__main__":
    main()
