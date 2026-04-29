import os


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

DETECTION_MIN_CONFIDENCE = float(os.environ.get("DETECTION_MIN_CONFIDENCE", "0.45"))
DETECTION_CONFIRMATION_CONFIDENCE = float(
    os.environ.get("DETECTION_CONFIRMATION_CONFIDENCE", "0.75")
)
GENERIC_LABELS_REQUIRING_CONFIRMATION = {"bowl"}
GENERIC_LABELS_REQUIRING_MANUAL_SEARCH = {"cup", "bottle", "wine glass", "fork", "knife", "spoon"}


def get_nutrients(label: str, yolo_to_tfda: dict, tfda_db: dict, nutrition_db: dict) -> dict:
    """
    查詢營養資料庫 — 三層 fallback:
    1. YOLO label → TFDA 映射 → TFDA DB
    2. YOLO label → 原始 NUTRITION_DB
    3. UNKNOWN_NUTRIENTS
    """
    label_lower = label.lower()

    mapping = yolo_to_tfda.get(label_lower)
    if mapping and mapping.get("tfda_key") and mapping["tfda_key"] in tfda_db:
        tfda = tfda_db[mapping["tfda_key"]]
        return {
            "name_zh": mapping.get("name_zh", tfda.get("name_zh", label)),
            "calories": tfda.get("calories", 0),
            "protein": tfda.get("protein", 0),
            "fat": tfda.get("fat", 0),
            "carbs": tfda.get("carbs", 0),
            "sodium": tfda.get("sodium", 0),
            "fiber": tfda.get("fiber", 0),
            "sugar": tfda.get("sugar"),
            "saturated_fat": tfda.get("saturated_fat"),
            "cholesterol": tfda.get("cholesterol"),
            "gi": mapping.get("gi"),
            "allergens": mapping.get("allergens", []),
            "unit": "per 100g",
            "density": mapping.get("density", 0.80),
            "source": "TFDA",
            "tfda_code": tfda.get("code"),
        }

    if label_lower in nutrition_db:
        return nutrition_db[label_lower]

    return UNKNOWN_NUTRIENTS


def estimate_weight(bbox_w: float, bbox_h: float, img_w: int, img_h: int, density: float) -> float:
    pixel_area = (bbox_w * img_w) * (bbox_h * img_h)
    ref_area = 15000
    estimated_volume = (pixel_area / ref_area) * 100
    return round(estimated_volume * density, 1)


def check_food_safety(nutrients: dict, weight_g: float, user_conditions: list, user_allergens: list, disease_rules: dict) -> list:
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

    for allergen in food_allergens:
        if allergen in user_allergens:
            warnings.append(f"含過敏原: {allergen}")

    for condition in user_conditions:
        rules = disease_rules.get(condition, {})
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


def assess_detection(label: str, confidence: float, nutrients: dict, yolo_to_tfda: dict, nutrition_db: dict, manual_search_hints: dict | None = None) -> dict:
    label_lower = label.lower()
    is_mapped_food = label_lower in yolo_to_tfda or label_lower in nutrition_db
    warnings = []
    search_hints = (manual_search_hints or {}).get(label_lower, [])

    if confidence < DETECTION_MIN_CONFIDENCE:
        return {
            "accepted": False,
            "needs_confirmation": False,
            "warnings": [],
            "reason": f"辨識信心過低 ({confidence:.0%})",
            "search_hints": search_hints,
        }

    if label_lower in GENERIC_LABELS_REQUIRING_MANUAL_SEARCH:
        return {
            "accepted": False,
            "needs_confirmation": False,
            "warnings": [],
            "reason": "辨識結果過泛，請改用手動搜尋食品",
            "search_hints": search_hints,
        }

    if not is_mapped_food:
        return {
            "accepted": False,
            "needs_confirmation": False,
            "warnings": [],
            "reason": "目前無可用的食品營養對應，請改用手動搜尋食品",
            "search_hints": search_hints,
        }

    needs_confirmation = False
    if confidence < DETECTION_CONFIRMATION_CONFIDENCE:
        needs_confirmation = True
        warnings.append(f"辨識信心偏低 ({confidence:.0%})，建議人工確認")

    if label_lower in GENERIC_LABELS_REQUIRING_CONFIRMATION:
        needs_confirmation = True
        warnings.append("此類別可能是容器或泛稱，建議人工確認食品內容")

    if nutrients.get("name_zh") == UNKNOWN_NUTRIENTS["name_zh"] or not nutrients.get("calories"):
        needs_confirmation = True
        warnings.append("缺少可靠營養對應，建議改用手動搜尋食品")

    return {
        "accepted": True,
        "needs_confirmation": needs_confirmation,
        "warnings": warnings,
        "reason": None,
        "search_hints": search_hints,
    }


def predict_from_image(model, img, user_conditions, user_allergens, yolo_to_tfda, tfda_db, nutrition_db, disease_rules, manual_search_hints=None):
    img_h, img_w = img.shape[:2]
    results = model.predict(source=img, verbose=False)

    detections = []
    rejected_detections = []
    total_calories = 0
    total_sodium = 0

    for box in results[0].boxes:
        cls_id = int(box.cls[0])
        label = model.names[cls_id]
        confidence = round(float(box.conf[0]), 4)

        xyxy = box.xyxy[0].tolist()
        x1, y1, x2, y2 = xyxy
        bbox = {
            "x": round(x1 / img_w, 4),
            "y": round(y1 / img_h, 4),
            "w": round((x2 - x1) / img_w, 4),
            "h": round((y2 - y1) / img_h, 4),
        }

        nutrients = get_nutrients(label, yolo_to_tfda, tfda_db, nutrition_db)
        detection_assessment = assess_detection(label, confidence, nutrients, yolo_to_tfda, nutrition_db, manual_search_hints)
        if not detection_assessment["accepted"]:
            rejected_detections.append(
                {
                    "label": label,
                    "confidence": confidence,
                    "reason": detection_assessment["reason"],
                    "search_hints": detection_assessment["search_hints"],
                }
            )
            continue

        density = nutrients.get("density", 0.80)
        estimated_weight = estimate_weight(bbox["w"], bbox["h"], img_w, img_h, density)
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

        safety_warnings = check_food_safety(
            nutrients, estimated_weight, user_conditions, user_allergens, disease_rules
        )
        warnings = detection_assessment["warnings"] + safety_warnings

        detections.append(
            {
                "label": label,
                "name_zh": nutrients.get("name_zh", label),
                "confidence": confidence,
                "needs_confirmation": detection_assessment["needs_confirmation"],
                "source": nutrients.get("source", "fallback"),
                "bounding_box": bbox,
                "estimated_weight_g": estimated_weight,
                "nutrition": scaled_nutrition,
                "gi": nutrients.get("gi"),
                "allergens": nutrients.get("allergens", []),
                "warnings": warnings,
            }
        )

    return {
        "detections": detections,
        "rejected_detections": rejected_detections,
        "summary": {
            "total_items": len(detections),
            "rejected_items": len(rejected_detections),
            "total_calories": total_calories,
            "total_sodium": total_sodium,
        },
    }
