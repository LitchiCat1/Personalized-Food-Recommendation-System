"""Conservative identity and preparation matching for photographed foods.

Manual search may return substring suggestions. Automatic nutrition grounding
requires a name/official alias match and compatible preparation instead.
"""

import re

from services.food_service import search_foods


SYNONYMS = {
    "白米飯": "白飯", "米飯": "白飯", "熟白飯": "白飯",
    "台式香腸": "香腸", "烤香腸": "香腸", "豬肉香腸": "香腸",
    "魯肉": "滷肉", "滷肉塊": "滷肉", "滷五花肉塊": "滷五花肉",
    "熟水餃": "水餃", "煮水餃": "水餃", "高麗菜水餃": "水餃",
    "豬肉水餃": "水餃", "豬肉高麗菜水餃": "水餃",
    "陽春麵條": "熟麵條", "白麵條": "熟麵條", "細麵條": "熟麵條",
    "熟白麵條": "熟麵條", "麵條": "熟麵條",
    "黃麵": "油麵", "熟油麵": "油麵",
    "蔥花": "青蔥", "蔥末": "青蔥",
    "滷雞蛋": "滷蛋", "魯蛋": "滷蛋",
    "蔥抓餅": "蔥油餅", "蔥油抓餅": "蔥油餅",
    "大陸妹": "福山萵苣", "小黃瓜": "花胡瓜",
    "小黃瓜片": "花胡瓜", "黃瓜片": "花胡瓜", "毛豆": "毛豆仁",
    "豆乾": "豆干", "滷豆干": "豆干", "炒豆干": "豆干",
}
PREPARATION_PREFIX = re.compile(r"^(?:蒜香|蒜炒|清炒|清燙|汆燙|涼拌|川燙|炒|燙)")
EXPLICIT_TARGETS = {
    "水餃": ["熟水餃(高麗菜水餃)", "冷凍豬肉熟水餃"],
    "油麵": ["衛生油麵"],
    "滷蛋": ["雞滷蛋(市售)", "滷蛋平均值"],
    "醃小黃瓜": ["醃漬花胡瓜"],
    "醃黃瓜": ["醃漬花胡瓜"],
    "烤雞腿": ["usda_fndds:2705984"],
    "滷雞腿": ["usda_fndds:2705988"],
    "泡麵": ["usda_fndds:2709152"],
    "杯麵": ["usda_fndds:2709152"],
    "速食麵": ["usda_fndds:2709152"],
    "豆干": ["小方豆干"],
}


def food_identity(name):
    name = re.sub(r"[（(][^）)]*[）)]", "", str(name or "").strip()).replace("平均值", "")
    name = PREPARATION_PREFIX.sub("", name)
    return SYNONYMS.get(name, name)


def _preparation_notes(food, item):
    name = str(item.get("name_zh") or "")
    description = food.get("description") or ""
    combined = " ".join(str(food.get(field) or "") for field in ("name_zh", "name_en", "description"))
    state = item.get("food_state", "prepared")
    notes = []
    if any(token in combined for token in ("醃漬", "鹽漬", "泡菜")) and not any(token in name for token in ("醃", "漬", "泡菜", "酸菜")):
        return None
    if state not in ("raw", "dry"):
        if any(token in combined for token in ("濃縮", "湯塊", "乾麵條", "(dry)", "uncooked")):
            return None
        if "麵" in name and isinstance(food.get("water"), (int, float)) and food["water"] < 45:
            return None
        vegetable_reference = (food.get("category") in ("蔬菜類", "豆類") and
                               not any(token in combined for token in ("醃", "泡菜", "熟", "炒", "煮")))
        if "樣品狀態:生" in description or vegetable_reference:
            if food.get("category") in ("肉類", "魚貝類", "蛋類"):
                return None
            notes.append("營養採原態食材參考值，未包含烹調用油、醬汁與生熟重量變化")
    if food.get("reference_only"):
        notes.append("營養採 USDA 一般食物參考值；實際配方、含水量、油鹽與品牌可能不同，請確認")
    if food_identity(name) == "水餃" and "高麗菜" not in name:
        notes.append("照片無法確認水餃內餡，暫採熟高麗菜水餃參考值，請確認內餡與總重量")
    if food_identity(name) == "豆干":
        notes.append("採 TFDA 小方豆干參考值，未包含另外拌炒的油、醬汁或其他配料")
    return notes


def find_vision_food_matches(storage, database, item, user_id, build_custom_food_search_result):
    name = str(item.get("name_zh") or "").strip()
    identity = food_identity(name)
    # Model alternatives may contain other dishes or just one ingredient. They
    # cannot redefine a recognized food (rice is not an alias of pork rice).
    identities = {name, identity}
    explicit = EXPLICIT_TARGETS.get(identity, [])
    candidates = []
    if user_id:
        for result in search_foods(storage, {}, name, 50, user_id, build_custom_food_search_result):
            if food_identity(result.get("name_zh")) == identity:
                candidates.append((result.get("key"), result, -1))
    for key, food in database.items():
        names = [food.get("name_zh", key), *food.get("aliases", [])]
        exact = any(value in identities for value in names)
        normalized = any(food_identity(value) == identity for value in names)
        if key in explicit or exact or normalized:
            priority = 0 if key in explicit or name in names else 1 if exact else 2
            candidates.append((key, food, priority))

    matches = []
    for key, food, priority in candidates:
        notes = _preparation_notes(food, item)
        if notes is None:
            continue
        unit = food.get("unit", "per 100g")
        if unit != "per 100g" and not food.get("serving_size_g"):
            continue
        if not all(isinstance(food.get(field), (int, float)) for field in ("calories", "protein", "carbs", "fat", "sodium")):
            continue
        result = dict(food, key=key, source=food.get("source", "TFDA"), match_notes=notes)
        if unit != "per 100g":
            scale = 100 / food["serving_size_g"]
            for field in ("calories", "protein", "fat", "carbs", "sodium", "fiber", "sugar", "saturated_fat", "trans_fat"):
                if isinstance(result.get(field), (int, float)):
                    result[field] *= scale
            result["unit"] = "per 100g"
        # TFDA is primary; USDA is used only when no compatible TFDA identity
        # remains after preparation and unit checks.
        ingredient_reference = any("原態食材" in note for note in notes)
        rank = (food.get("source") == "USDA FNDDS", ingredient_reference, priority,
                explicit.index(key) if key in explicit else len(explicit),
                "平均值" not in food.get("name_zh", ""), len(food.get("name_zh", "")))
        matches.append((rank, result))
    return [result for _rank, result in sorted(matches, key=lambda row: row[0])][:5]
