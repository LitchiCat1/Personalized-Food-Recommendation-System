ENERGY_FIELD = "calories"

NUTRIENT_FIELDS = (
    "protein",
    "carbs",
    "sugar",
    "fat",
    "saturated_fat",
    "trans_fat",
    "fiber",
    "sodium",
    "calcium",
    "iron",
)

NUTRITION_FIELDS = (ENERGY_FIELD, *NUTRIENT_FIELDS)
WHOLE_NUMBER_FIELDS = {"calories", "sodium", "calcium", "iron"}

FRIED_FOOD_KEYWORDS = (
    "油炸",
    "炸雞",
    "炸排",
    "炸魚",
    "炸蝦",
    "薯條",
    "天婦羅",
    "雞塊",
    "炸物",
    "炸起司",
    "酥炸",
    "deep-fried",
    "deep fried",
    "oil-fried",
    "oil fried",
)


def nutrient_number(value, fallback: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def get_nutrient_value(source: dict | None, nutrient: str, fallback=0):
    values = source or {}
    value = values.get(nutrient)
    if nutrient == "sugar" and value is None:
        value = values.get("refined_sugar")
    return fallback if value is None else value


def is_fried_food_name(*values) -> bool:
    text = " ".join(str(value or "").strip().lower() for value in values)
    return any(keyword in text for keyword in FRIED_FOOD_KEYWORDS)


def normalize_nutrition_fields(source: dict | None) -> dict:
    return {
        nutrient: round(
            nutrient_number(get_nutrient_value(source, nutrient)),
            0 if nutrient in WHOLE_NUMBER_FIELDS else 1,
        )
        for nutrient in NUTRITION_FIELDS
    }
