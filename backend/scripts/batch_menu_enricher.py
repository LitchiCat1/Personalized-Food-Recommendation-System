"""
NutriLens Automated Menu Scraper & AI Nutrition Enricher
Automates fetching raw restaurant menus, enriching items with nutrition/disease/allergen tags,
and writing directly to backend/data/restaurant_catalog.json.
"""

import json
import os
import sys
import time
import uuid

# Base directory for resolution
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(BASE_DIR, "data", "restaurant_catalog.json")

# Sample Raw Scraped Restaurant Data Pool
SAMPLE_RAW_RESTAURANTS = [
    {
        "name": "池上木片便當",
        "category": "便當",
        "address": "台北市信義區忠孝東路五段200號",
        "lat": 25.0405,
        "lng": 121.5680,
        "raw_menu": [
            {"name": "招牌木片正宗便當", "price": 110, "description": "香烤里肌肉配香腸、滷蛋與高麗菜"},
            {"name": "蒲燒鯛魚便當", "price": 130, "description": "醬燒蒲燒鯛魚排搭紫米飯與時蔬"},
            {"name": "清蒸去皮雞腿便當", "price": 120, "description": "清蒸鮮嫩大雞腿搭配高纖水煮時蔬"}
        ]
    },
    {
        "name": "台南府城水餃麵館",
        "category": "小菜",
        "address": "台北市大安區和平東路二段80號",
        "lat": 25.0260,
        "lng": 121.5430,
        "raw_menu": [
            {"name": "高麗菜鮮肉水餃 (10顆)", "price": 80, "description": "嚴選溫體豬肉搭配清甜高麗菜"},
            {"name": "鮮蝦大餛飩湯麵", "price": 105, "description": "完整大鮮蝦包入薄皮餛飩配清高湯"},
            {"name": "涼拌小黃瓜 (低鹽)", "price": 40, "description": "新鮮小黃瓜拍碎佐蒜香麻油拌勻"}
        ]
    }
]

# Rule-based fallback nutrition estimator for fast AI enrichment
NUTRITION_ESTIMATOR_RULES = {
    "雞腿": {"calories": 520, "protein": 36, "carbs": 45, "fat": 15, "sodium": 480, "gi": "low", "tags": ["高蛋白", "低GI"]},
    "鯛魚": {"calories": 480, "protein": 32, "carbs": 42, "fat": 12, "sodium": 420, "gi": "low", "tags": ["優質脂肪", "低GI"]},
    "招牌": {"calories": 680, "protein": 28, "carbs": 78, "fat": 24, "sodium": 880, "gi": "medium", "tags": ["高鈉"]},
    "水餃": {"calories": 550, "protein": 22, "carbs": 65, "fat": 20, "sodium": 750, "gi": "medium", "tags": ["中蛋白質"]},
    "餛飩": {"calories": 580, "protein": 24, "carbs": 68, "fat": 22, "sodium": 920, "gi": "high", "tags": ["高鈉"]},
    "黃瓜": {"calories": 75, "protein": 2, "carbs": 8, "fat": 3, "sodium": 180, "gi": "low", "tags": ["低GI", "低鈉", "高纖"]}
}


def estimate_item_nutrition(item: dict) -> dict:
    """Estimates nutrition and health tags based on food keywords."""
    name = item["name"]
    price = item["price"]
    desc = item.get("description", "")

    # Default estimation
    matched = {
        "calories": 500, "protein": 25, "carbs": 50, "fat": 15,
        "sodium": 500, "gi": "medium", "tags": ["便當"]
    }

    # Match rules
    for kw, rule in NUTRITION_ESTIMATOR_RULES.items():
        if kw in name or kw in desc:
            matched = rule
            break

    allergens = []
    if "蝦" in name or "鮮蝦" in desc:
        allergens.append("shrimp")
    if "蛋" in desc or "蛋" in name:
        allergens.append("egg")
    if "麵" in name or "水餃" in name:
        allergens.append("gluten")

    customization_tips = []
    if matched["sodium"] > 600:
        customization_tips.append("湯頭少喝以控鈉")
    if matched["gi"] == "low":
        customization_tips.append("低 GI 食物穩血糖")
    if matched["carbs"] > 60:
        customization_tips.append("建議飯量改半飯")

    return {
        "item_id": f"item_{uuid.uuid4().hex[:6]}",
        "name": name,
        "price": price,
        "calories": matched["calories"],
        "protein": matched["protein"],
        "carbs": matched["carbs"],
        "fat": matched["fat"],
        "sodium": matched["sodium"],
        "gi": matched["gi"],
        "allergens": allergens,
        "tags": matched["tags"],
        "can_customize": True,
        "customization_tips": customization_tips
    }


def enrich_and_append_restaurant(raw_restaurant: dict) -> dict:
    """Enriches a single raw restaurant dictionary and saves to restaurant_catalog.json."""
    enriched_items = [estimate_item_nutrition(item) for item in raw_restaurant.get("raw_menu", [])]
    
    restaurant_doc = {
        "restaurant_id": f"rest_auto_{uuid.uuid4().hex[:6]}",
        "name": raw_restaurant["name"],
        "lat": raw_restaurant.get("lat", 25.0338),
        "lng": raw_restaurant.get("lng", 121.5645),
        "address": raw_restaurant.get("address", ""),
        "phone": raw_restaurant.get("phone", "02-0000-0000"),
        "google_place_id": "",
        "open_hours": ["11:00-20:30"],
        "tags": [raw_restaurant.get("category", "小吃")],
        "price_level": 2,
        "items": enriched_items
    }

    # Append to JSON database
    if os.path.exists(CATALOG_PATH):
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            catalog = json.load(f)
    else:
        catalog = []

    catalog.append(restaurant_doc)

    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    return restaurant_doc


def run_batch_enrichment():
    print("=" * 60)
    print("  NutriLens 菜單自動化爬蟲 & AI 營養標註腳本啟動")
    print("=" * 60)
    
    for raw in SAMPLE_RAW_RESTAURANTS:
        print(f"\n[+] 正在處理爬取餐廳: {raw['name']} ({len(raw['raw_menu'])} 道菜單)...")
        doc = enrich_and_append_restaurant(raw)
        print(f"    [OK] 已完成營養推論並寫入 Catalog! ID: {doc['restaurant_id']}")
        for item in doc["items"]:
            print(f"      - [{item['name']}] {item['calories']}kcal 鈉{item['sodium']}mg GI={item['gi']}")

    print("\n" + "=" * 60)
    print("  [完成] 已成功自動批量寫入餐廳資料庫！")
    print("=" * 60)


if __name__ == "__main__":
    run_batch_enrichment()
