"""
將衛福部食品營養成分資料庫 (TFDA) 原始 JSON (20_5.json) 轉為 NutriLens 格式。
原始資料: 每筆一個 (食品 × 營養素) row，需要 pivot 成 per-food dict。

結構: 整合編號 → 多筆 row (每個 分析項 一筆)
      分析項 = 營養素名稱 (熱量, 粗蛋白, 粗脂肪 ...)
      每100克含量 = 數值
"""
import json
import os
import sys

RAW_PATH = os.path.join(os.path.dirname(__file__), "..", "tfda_data", "20_5.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "nutrition_db_tw.json")

# 我們關心的營養素 (分析項名 → 輸出 key)
NUTRIENT_MAP = {
    "熱量": "calories",
    "粗蛋白": "protein",
    "粗脂肪": "fat",
    "總碳水化合物": "carbs",
    "鈉": "sodium",
    "膳食纖維": "fiber",
    "糖質總量": "sugar",
    "飽和脂肪": "saturated_fat",
    "反式脂肪": "trans_fat",
    "膽固醇": "cholesterol",
    "鉀": "potassium",
    "鈣": "calcium",
    "鐵": "iron",
    "鎂": "magnesium",
    "磷": "phosphorus",
    "鋅": "zinc",
    "維生素A總量(IU)": "vitamin_a_iu",
    "維生素C": "vitamin_c",
    "維生素B1": "vitamin_b1",
    "維生素B2": "vitamin_b2",
    "維生素B6": "vitamin_b6",
    "維生素B12": "vitamin_b12",
    "維生素D總量(ug)": "vitamin_d",
    "維生素E總量": "vitamin_e",
    "葉酸": "folate",
    "水分": "water",
    "灰分": "ash",
    "修正熱量": "adjusted_calories",
}


def safe_float(v):
    """安全轉換數值，處理 '--', 'Tr', '微量', 'NA', 等"""
    if v is None:
        return None
    v = str(v).strip()
    if v in ("", "--", "NA", "…"):
        return None
    if v in ("Tr", "微量"):
        return 0.0  # trace amount
    try:
        return float(v)
    except ValueError:
        return None


def main():
    print(f"📂 Reading {RAW_PATH} ...")

    with open(RAW_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    print(f"  Total rows: {len(raw):,}")

    # ── Pass 1: 按整合編號分組，收集基本資料 + 營養素 ──
    foods = {}  # 整合編號 → dict

    for row in raw:
        code = str(row.get("整合編號", "")).strip()
        if not code:
            continue

        # 初次看到這個 code → 建骨架
        if code not in foods:
            foods[code] = {
                "code": code,
                "name_zh": str(row.get("樣品名稱", "")).strip(),
                "name_en": str(row.get("樣品英文名稱", "") or "").strip(),
                "category": str(row.get("食品分類", "")).strip(),
                "description": str(row.get("內容物描述", "") or "").strip(),
                "waste_rate": str(row.get("廢棄率", "") or "").strip(),
                "nutrients": {},
            }

        # 取營養素
        nutrient_name = str(row.get("分析項", "")).strip()
        our_key = NUTRIENT_MAP.get(nutrient_name)
        if not our_key:
            continue

        raw_value = row.get("每100克含量")
        value = safe_float(raw_value)
        if value is not None:
            foods[code]["nutrients"][our_key] = value

    print(f"  Unique foods (codes): {len(foods):,}")

    # ── Pass 2: 扁平化為最終格式 ──
    result = {}
    skipped = 0

    for code, food in foods.items():
        n = food["nutrients"]
        name = food["name_zh"]

        if not name:
            skipped += 1
            continue

        # 以中文名稱為 key (去全形空白)
        key = name.replace("　", "").strip()

        result[key] = {
            "code": code,
            "name_zh": name,
            "name_en": food["name_en"],
            "category": food["category"],
            # 核心六大營養素 (app.py 必用)
            "calories": n.get("calories", 0),
            "protein": n.get("protein", 0),
            "fat": n.get("fat", 0),
            "carbs": n.get("carbs", 0),
            "sodium": n.get("sodium", 0),
            "fiber": n.get("fiber", 0),
            # 額外營養素
            "sugar": n.get("sugar"),
            "saturated_fat": n.get("saturated_fat"),
            "trans_fat": n.get("trans_fat"),
            "cholesterol": n.get("cholesterol"),
            "potassium": n.get("potassium"),
            "calcium": n.get("calcium"),
            "iron": n.get("iron"),
            "magnesium": n.get("magnesium"),
            "phosphorus": n.get("phosphorus"),
            "zinc": n.get("zinc"),
            "vitamin_a_iu": n.get("vitamin_a_iu"),
            "vitamin_c": n.get("vitamin_c"),
            "vitamin_b1": n.get("vitamin_b1"),
            "vitamin_b2": n.get("vitamin_b2"),
            "vitamin_b6": n.get("vitamin_b6"),
            "vitamin_b12": n.get("vitamin_b12"),
            "vitamin_d": n.get("vitamin_d"),
            "vitamin_e": n.get("vitamin_e"),
            "folate": n.get("folate"),
            "water": n.get("water"),
            # metadataz
            "unit": "per 100g",
            "source": "TFDA",
        }

    print(f"  Final foods in output: {len(result):,}")
    print(f"  Skipped (no name): {skipped}")

    # ── Save ──
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"\n✅ Saved to {OUT_PATH}")
    print(f"   File size: {size_kb:.0f} KB ({size_kb/1024:.1f} MB)")

    # ── 統計各分類數量 ──
    from collections import Counter
    cats = Counter(v["category"] for v in result.values())
    print("\n📊 Foods per category:")
    for cat, cnt in cats.most_common():
        print(f"   {cat}: {cnt}")

    # ── 印 5 筆範例 ──
    items = list(result.items())[:5]
    print("\n📋 Sample entries:")
    for k, v in items:
        print(f"\n   [{k}] ({v['category']})")
        print(f"     cal={v['calories']}, pro={v['protein']}, fat={v['fat']}, carbs={v['carbs']}, Na={v['sodium']}")


if __name__ == "__main__":
    main()
