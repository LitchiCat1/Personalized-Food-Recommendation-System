"""
YOLO COCO Label → TFDA 台灣食品 映射表
COCO 80 類中的食物相關:
  46: banana, 47: apple, 48: sandwich, 49: orange, 50: broccoli,
  51: carrot, 52: hot dog, 53: pizza, 54: donut, 55: cake,
  41: cup, 45: bowl, 39: bottle, 40: wine glass, 42: fork,
  43: knife, 44: spoon
"""

# YOLO label (lowercase) → TFDA 資料 + 補充 metadata
# tfda_key 必須是 nutrition_db_tw.json 裡存在的 key
YOLO_TO_TFDA = {
    "banana": {
        "name_zh": "香蕉",
        "tfda_key": "北蕉平均值",       # TFDA 用品種名
        "gi": "medium",
        "allergens": [],
        "density": 0.95,
    },
    "apple": {
        "name_zh": "蘋果",
        "tfda_key": "富士蘋果",
        "gi": "low",
        "allergens": [],
        "density": 0.85,
    },
    "sandwich": {
        "name_zh": "三明治",
        "tfda_key": "火腿蛋三明治",
        "gi": "medium",
        "allergens": ["麩質", "蛋"],
        "density": 0.68,
    },
    "orange": {
        "name_zh": "柳橙",
        "tfda_key": "柳橙",
        "gi": "low",
        "allergens": [],
        "density": 0.92,
    },
    "broccoli": {
        "name_zh": "花椰菜",
        "tfda_key": "花椰菜",
        "gi": "low",
        "allergens": [],
        "density": 0.60,
    },
    "carrot": {
        "name_zh": "胡蘿蔔",
        "tfda_key": "胡蘿蔔平均值",
        "gi": "low",
        "allergens": [],
        "density": 0.82,
    },
    "hot dog": {
        "name_zh": "熱狗",
        "tfda_key": "熱狗",
        "gi": "low",
        "allergens": ["麩質"],
        "density": 0.80,
    },
    "pizza": {
        "name_zh": "披薩",
        "tfda_key": "披薩(夏威夷)",
        "gi": "high",
        "allergens": ["麩質", "牛奶"],
        "density": 0.75,
    },
    "donut": {
        "name_zh": "甜甜圈",
        "tfda_key": "糖粒甜甜圈(油炸)",
        "gi": "high",
        "allergens": ["麩質", "蛋", "牛奶"],
        "density": 0.50,
    },
    "cake": {
        "name_zh": "蛋糕",
        "tfda_key": "海綿蛋糕(圓形)",
        "gi": "high",
        "allergens": ["麩質", "蛋", "牛奶"],
        "density": 0.45,
    },
    "bowl": {
        "name_zh": "碗公飯",
        "tfda_key": "白飯",
        "gi": "high",
        "allergens": [],
        "density": 1.10,
    },
    "cup": {
        "name_zh": "飲品",
        "tfda_key": None,               # 太泛，無法映射
        "gi": "medium",
        "allergens": [],
        "density": 1.00,
    },
}


# COCO 容器/餐具類別不能直接推算營養，僅提供手動搜尋建議。
YOLO_MANUAL_SEARCH_HINTS = {
    "cup": ["咖啡", "牛奶", "豆漿", "果汁", "可樂", "茶"],
    "bottle": ["可樂", "果汁", "茶", "牛奶", "優酪乳"],
    "wine glass": ["紅酒", "白酒", "果汁"],
    "bowl": ["白飯", "粥", "湯", "麵", "沙拉"],
    "fork": ["義大利麵", "沙拉", "蛋糕"],
    "knife": ["牛排", "豬排", "雞排"],
    "spoon": ["湯", "粥", "咖哩飯", "優格"],
}
