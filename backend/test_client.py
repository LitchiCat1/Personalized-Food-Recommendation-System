"""
NutriLens Backend Test Client
Tests all API endpoints against the PRD requirements
"""

import base64
import json
import sys
import requests

API_URL = "http://127.0.0.1:5000"
IMAGE_PATH = "food.jpg"


def sep(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_health():
    sep("Health Check")
    resp = requests.get(f"{API_URL}/health", timeout=5)
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def test_bmr_calculator():
    sep("BMR/TDEE Calculator")
    resp = requests.post(f"{API_URL}/calculate/bmr", json={
        "gender": "male",
        "weight": 72,
        "height": 175,
        "age": 28,
        "activity_multiplier": 1.55,
    })
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def test_user_profile():
    sep("Create/Update User Profile")
    resp = requests.post(f"{API_URL}/user", json={
        "user_id": "user_001",
        "name": "王小明",
        "gender": "male",
        "weight": 72,
        "height": 175,
        "age": 28,
        "activity_level": "中等活動量",
        "activity_multiplier": 1.55,
        "daily_calorie_target": 2100,
        "health_conditions": ["高血壓"],
        "allergens": ["花生", "蝦蟹"],
        "target_weight": 70,
        "diet_type": "均衡飲食",
    })
    data = resp.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))

    sep("Get User Profile")
    resp = requests.get(f"{API_URL}/user/user_001")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def test_predict():
    sep("Image Detection (with health context)")
    try:
        with open(IMAGE_PATH, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
    except FileNotFoundError:
        print(f"[跳過] 找不到 {IMAGE_PATH}")
        return

    resp = requests.post(f"{API_URL}/predict", json={
        "image": img_b64,
        "health_conditions": ["高血壓"],
        "allergens": ["花生", "蝦蟹"],
    }, timeout=30)

    data = resp.json()
    print(f"\n偵測到 {data.get('summary', {}).get('total_items', 0)} 項食物")
    for det in data.get("detections", []):
        print(f"\n  [{det['name_zh']}] {det['label']}")
        print(f"    信心度: {det['confidence']:.2%}")
        print(f"    份量: {det['estimated_weight_g']}g")
        print(f"    GI: {det['gi']}")
        bb = det["bounding_box"]
        print(f"    Bbox: x={bb['x']:.2f} y={bb['y']:.2f} w={bb['w']:.2f} h={bb['h']:.2f}")
        n = det["nutrition"]
        print(f"    熱量={n['calories']}kcal 蛋白質={n['protein']}g 碳水={n['carbs']}g 脂肪={n['fat']}g 鈉={n['sodium']}mg 纖維={n['fiber']}g")
        if det["allergens"]:
            print(f"    ⚠ 過敏原: {', '.join(det['allergens'])}")
        if det["warnings"]:
            print(f"    🚨 警告: {'; '.join(det['warnings'])}")

    print(f"\n合計: {data['summary']['total_calories']} kcal | 鈉 {data['summary']['total_sodium']}mg")


def test_add_record():
    sep("Add Dietary Record")
    resp = requests.post(f"{API_URL}/record", json={
        "user_id": "user_001",
        "meal_type": "午餐",
        "foods": [
            {"name": "雞胸肉沙拉", "calories": 420, "protein": 38, "carbs": 28, "fat": 14, "sodium": 520},
        ],
        "total_calories": 420,
        "total_protein": 38,
        "total_carbs": 28,
        "total_fat": 14,
        "total_sodium": 520,
        "total_fiber": 5,
        "source": "camera",
    })
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def test_get_records():
    sep("Get Records")
    resp = requests.get(f"{API_URL}/records/user_001")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def test_history():
    sep("History / Trends")
    resp = requests.get(f"{API_URL}/history/user_001?days=7")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def test_recommendations():
    sep("Personalized Recommendations")
    resp = requests.get(f"{API_URL}/recommend/user_001")
    data = resp.json()
    print(f"推薦 {data.get('total_candidates', 0)} 項 | 過濾 {data.get('total_filtered', 0)} 項")
    for r in data.get("recommended", [])[:5]:
        print(f"  [{r['match_score']}] {r['name_zh']} — {r['calories']}kcal 鈉{r['sodium']}mg GI={r['gi']}")
    if data.get("filtered_out"):
        print("\n被排除:")
        for f in data["filtered_out"]:
            print(f"  ✗ {f['name_zh']} — {', '.join(f['reasons'])}")


def main():
    tests = [
        ("health", test_health),
        ("bmr", test_bmr_calculator),
        ("user", test_user_profile),
        ("predict", test_predict),
        ("record", test_add_record),
        ("records", test_get_records),
        ("history", test_history),
        ("recommend", test_recommendations),
    ]

    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    for name, fn in tests:
        if target == "all" or target == name:
            try:
                fn()
            except requests.ConnectionError:
                print(f"[錯誤] 無法連線後端，請確認 app.py 已啟動 (port 5000)")
                if target != "all":
                    sys.exit(1)
            except Exception as e:
                print(f"[錯誤] {e}")


if __name__ == "__main__":
    main()
