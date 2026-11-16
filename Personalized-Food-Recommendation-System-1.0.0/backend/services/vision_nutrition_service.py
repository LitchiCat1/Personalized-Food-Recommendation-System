"""Conservative identity and preparation matching for photographed foods.

Manual search may return substring suggestions. Automatic nutrition grounding
requires a name/official alias match and compatible preparation instead.
"""

import math
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
    "泡麵(含湯)": "泡麵", "杯麵(含湯)": "杯麵", "沖泡泡麵(含湯)": "泡麵",
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
    "荷包蛋": ["荷包蛋(不加油)"],
}

# Reviewed links to individual imported records, never model translations.
AUDITED_BILINGUAL_TARGETS = {
    "全脂牛奶": ("usda_fndds:2705385", "Milk, whole"),
}
CORE_NUTRIENTS = ("calories", "protein", "carbs", "fat", "sodium")
OPTIONAL_NUTRIENTS = ("fiber", "sugar", "saturated_fat", "trans_fat")
STATES = {"raw", "dry", "prepared"}


def _valid_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def food_identity(name):
    name = str(name or "").strip().replace("（", "(").replace("）", ")")
    # Keep fillings, flavours and brands. Only these reviewed annotations are
    # metadata; removing arbitrary parentheses erases nutritional identity.
    name = re.sub(r"\((?:USDA參考|市售|熟)\)", "", name).replace("平均值", "")
    name = PREPARATION_PREFIX.sub("", name)
    return SYNONYMS.get(name, name)


def _named_state(name):
    if any(token in name for token in ("乾麵條", "未沖泡", "未煮", "乾品")):
        return "dry"
    if name.startswith("生"):
        return "raw"
    if any(token in name for token in ("白飯", "米飯", "熟", "炒", "燙", "滷", "魯", "烤", "煮", "炸", "煎", "燉", "沖泡", "荷包蛋")):
        return "prepared"
    return None


def _named_method(name):
    for method, tokens in (
        ("deep_fried", ("油炸", "酥炸", "炸")),
        ("stir_fried", ("炒",)),
        ("boiled", ("清燙", "汆燙", "川燙", "燙", "水煮", "煮水餃")),
        ("pan_fried", ("煎", "荷包蛋")),
        ("roasted", ("烤",)),
        ("braised", ("滷", "魯", "燉", "紅燒", "醬燒")),
        ("steamed", ("蒸",)),
        ("mixed", ("涼拌",)),
    ):
        if any(token in name for token in tokens):
            return method
    return None


def _profile_method(food, *, record_key=None):
    method = food.get("preparation_method")
    if method and method != "unknown":
        return method
    named = _named_method(str(food.get("name_zh") or ""))
    if named:
        return named
    if food.get("name_zh") in ("熟水餃(高麗菜水餃)", "冷凍豬肉熟水餃"):
        return "boiled"
    # Existing reviewed mapping is a generic cooked pork reference, not an
    # assertion that the US recipe equals Taiwanese braised pork.
    if food.get("fdc_id") == 2705901:
        return "braised"
    # Reviewed TFDA record A0550601 is cooked white rice prepared in an
    # electric rice cooker. The dataset omits its method enum; keep this
    # equivalence tied to the exact official record and its documented basis.
    if (record_key == "白飯" and food.get("source") == "TFDA"
            and food.get("code") == "A0550601" and food.get("name_zh") == "白飯"
            and "白米加1.1倍的去離子水,用電鍋烹煮" in str(food.get("description") or "")):
        return "steamed"
    return None


def _profile_state(food):
    state = food.get("food_state")
    if isinstance(state, str) and state in STATES:
        return state
    description = str(food.get("description") or "").lower()
    if any(token in description for token in ("乾麵條", "(dry)", "uncooked", "unprepared")):
        return "dry"
    if "樣品狀態:生" in description or "樣品狀態：生" in description:
        return "raw"
    if "樣品狀態:熟" in description or any(token in description for token in ("cooked", "prepared", "roasted", "stewed")):
        return "prepared"
    named = _named_state(str(food.get("name_zh") or ""))
    if named:
        return named
    if food.get("category") in ("蔬菜類", "豆類", "肉類", "魚貝類", "蛋類"):
        if not any(token in description for token in ("醃", "泡菜", "熟", "炒", "煮")):
            return "raw"
    return None


def _preparation_notes(food, item, *, record_key=None):
    name = str(item.get("name_zh") or "")
    combined = " ".join(str(food.get(field) or "") for field in ("name_zh", "name_en", "description"))
    state = item.get("food_state")
    if state not in (None, "unknown", "raw", "dry", "prepared"):
        return None
    if state == "unknown":
        state = None
    named_state = _named_state(name)
    if state and named_state and state != named_state:
        return None
    state = state or named_state
    profile_state = _profile_state(food)
    notes = []
    if state and profile_state and state != profile_state:
        return None
    if profile_state in ("raw", "dry") and state is None:
        return None
    if food.get("food_state") is not None and (not isinstance(food["food_state"], str) or food["food_state"] not in STATES):
        return None
    method = item.get("preparation_method")
    named_method = _named_method(name)
    if method in (None, "unknown"):
        method = named_method
    elif named_method and named_method != method:
        return None
    source_method = _profile_method(food, record_key=record_key)
    if method and method != source_method:
        return None
    if source_method and not method and food_identity(name) not in EXPLICIT_TARGETS:
        source_names = [food.get("name_zh"), *food.get("aliases", [])]
        if name not in source_names:
            return None
    source_scope = food.get("components_scope")
    if not source_scope and "含湯" in str(food.get("name_zh") or ""):
        source_scope = "whole_dish_with_broth"
    target_scope = item.get("components_scope")
    if (not target_scope or target_scope == "unknown") and "含湯" in name:
        target_scope = "whole_dish_with_broth"
    if source_scope == "whole_dish_with_broth" and target_scope != source_scope:
        return None
    if source_scope and target_scope and target_scope != "unknown" and source_scope != "unknown" and source_scope != target_scope:
        return None
    if "水餃" in name:
        fillings = ("韭菜", "高麗菜", "玉米", "鮮蝦", "泡菜")
        target_fillings = {value for value in fillings if value in name}
        source_fillings = {value for value in fillings if value in str(food.get("name_zh") or "")}
        if target_fillings and target_fillings != source_fillings:
            return None
    if any(token in combined for token in ("醃漬", "鹽漬", "泡菜")) and not any(token in name for token in ("醃", "漬", "泡菜", "酸菜")):
        return None
    if state == "prepared":
        if any(token in combined for token in ("濃縮", "湯塊", "乾麵條", "(dry)", "uncooked")):
            return None
        if "麵" in name and _valid_number(food.get("water")) and food["water"] < 45:
            return None
    if food.get("reference_only"):
        notes.append("營養採 USDA 一般食物參考值；實際配方、含水量、油鹽與品牌可能不同，請確認")
    if food_identity(name) == "水餃" and "高麗菜" not in name:
        notes.append("照片無法確認水餃內餡，暫採熟高麗菜水餃參考值，請確認內餡與總重量")
    if food_identity(name) == "豆干":
        notes.append("採 TFDA 小方豆干參考值，未包含另外拌炒的油、醬汁或其他配料")
    if name == "荷包蛋" and food.get("name_zh") == "荷包蛋(不加油)":
        notes.append("採不加油荷包蛋參考值，不含額外煎蛋用油")
    return notes


def find_vision_food_matches(storage, database, item, user_id, build_custom_food_search_result, *, diagnostics=None):
    name = str(item.get("name_zh") or "").strip()
    identity = food_identity(name)
    # Model alternatives may contain other dishes or just one ingredient. They
    # cannot redefine a recognized food (rice is not an alias of pork rice).
    identities = {name, identity}
    explicit = EXPLICIT_TARGETS.get(identity, [])
    bilingual = AUDITED_BILINGUAL_TARGETS.get(name)
    candidates = []
    if user_id:
        for result in search_foods(storage, {}, name, 50, user_id, build_custom_food_search_result):
            if food_identity(result.get("name_zh")) == identity:
                candidates.append((result.get("key"), result, -1, True))
    for key, food in database.items():
        names = [food.get("name_zh", key), *food.get("aliases", [])]
        exact = any(value in identities for value in names)
        normalized = any(food_identity(value) == identity for value in names)
        reviewed = bool(bilingual and key == bilingual[0] and food.get("name_en") == bilingual[1])
        if key in explicit or exact or normalized or reviewed:
            priority = 0 if key in explicit or name in names else 1 if exact else 2
            candidates.append((key, food, priority, False))

    matches = []
    rejected = {"incompatible": 0, "incomplete_profile": 0, "source_conflict": 0}
    for key, food, priority, custom in candidates:
        if food.get("nutrition_basis_status") == "conflicting":
            rejected["source_conflict"] += 1
            continue
        notes = _preparation_notes(food, item, record_key=key)
        if notes is None:
            rejected["incompatible"] += 1
            continue
        unit = food.get("unit", "per 100g")
        if unit not in ("per 100g", "per serving"):
            rejected["incomplete_profile"] += 1
            continue
        if unit == "per serving" and (not _valid_number(food.get("serving_size_g")) or food["serving_size_g"] <= 0):
            rejected["incomplete_profile"] += 1
            continue
        if not all(_valid_number(food.get(field)) for field in CORE_NUTRIENTS):
            rejected["incomplete_profile"] += 1
            continue
        if any(food.get(field) is not None and not _valid_number(food[field]) for field in OPTIONAL_NUTRIENTS):
            rejected["incomplete_profile"] += 1
            continue
        result = dict(food, key=key, source=food.get("source", "TFDA"), match_notes=notes)
        if unit == "per serving":
            scale = 100 / food["serving_size_g"]
            for field in CORE_NUTRIENTS + OPTIONAL_NUTRIENTS:
                if result.get(field) is not None:
                    result[field] *= scale
            result["unit"] = "per 100g"
            if any(result.get(field) is not None and not _valid_number(result[field]) for field in CORE_NUTRIENTS + OPTIONAL_NUTRIENTS):
                rejected["incomplete_profile"] += 1
                continue
        # TFDA is primary; USDA is used only when no compatible TFDA identity
        # remains after preparation and unit checks.
        rank = (0 if custom else 2 if food.get("source") == "USDA FNDDS" else 1, priority,
                explicit.index(key) if key in explicit else len(explicit),
                "平均值" not in food.get("name_zh", ""), len(food.get("name_zh", "")))
        matches.append((rank, result))
    if diagnostics is not None:
        status = ("matched" if matches else "source_conflict" if rejected["source_conflict"]
                  else "incomplete_profile" if rejected["incomplete_profile"]
                  else "incompatible" if candidates else "no_local_mapping")
        diagnostics.update(status=status, candidate_count=len(candidates), compatible_count=len(matches),
                           rejected_counts=rejected)
    return [result for _rank, result in sorted(matches, key=lambda row: row[0])][:5]
