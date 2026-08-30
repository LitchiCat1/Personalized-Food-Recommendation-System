import requests


OFF_PRODUCT_BASE = "https://world.openfoodfacts.org/api/v2/product"
OFF_SEARCH_BASE = "https://world.openfoodfacts.org/cgi/search.pl"


def _normalize_tags(values):
    return [str(value).strip().lower() for value in values or [] if str(value).strip()]


def _parse_nutrients(product: dict) -> dict:
    nutriments = product.get("nutriments") or {}
    return {
        "calories": nutriments.get("energy-kcal_100g") or nutriments.get("energy-kcal") or 0,
        "protein": nutriments.get("proteins_100g") or nutriments.get("proteins") or 0,
        "carbs": nutriments.get("carbohydrates_100g") or nutriments.get("carbohydrates") or 0,
        "sugar": nutriments.get("sugars_100g") or nutriments.get("sugars") or 0,
        "fat": nutriments.get("fat_100g") or nutriments.get("fat") or 0,
        "saturated_fat": nutriments.get("saturated-fat_100g") or nutriments.get("saturated-fat") or 0,
        "trans_fat": nutriments.get("trans-fat_100g") or nutriments.get("trans-fat") or 0,
        # Open Food Facts stores mineral/salt values in grams per 100g;
        # NutriLens exposes these fields in milligrams.
        "sodium": (nutriments.get("sodium_100g") or nutriments.get("sodium") or 0) * 1000,
        "fiber": nutriments.get("fiber_100g") or nutriments.get("fiber") or 0,
        "calcium": (nutriments.get("calcium_100g") or nutriments.get("calcium") or 0) * 1000,
        "iron": (nutriments.get("iron_100g") or nutriments.get("iron") or 0) * 1000,
    }


def _extract_allergens(product: dict) -> list[str]:
    tags = []
    for key in ("allergens_tags", "traces_tags", "allergens", "traces"):
        tags.extend(product.get(key) or [])
    return _normalize_tags(tags)


def build_open_food_facts_product(product: dict) -> dict:
    nutriments = _parse_nutrients(product)
    labels = _normalize_tags(product.get("labels_tags") or [])
    ingredients_text = product.get("ingredients_text") or ""
    return {
        "product_name": product.get("product_name_zh") or product.get("product_name") or product.get("generic_name") or "",
        "brands": product.get("brands") or "",
        "barcode": product.get("code") or "",
        "ingredients_text": ingredients_text,
        "labels": labels,
        "allergens": _extract_allergens(product),
        "nutriments": nutriments,
        "source": "Open Food Facts",
    }


def fetch_open_food_facts_product(barcode: str, timeout: int = 8) -> dict | None:
    if not barcode:
        return None
    resp = requests.get(f"{OFF_PRODUCT_BASE}/{barcode}.json", timeout=timeout)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    product = data.get("product")
    if not product:
        return None
    return build_open_food_facts_product(product)


def search_open_food_facts(query: str, page_size: int = 5, timeout: int = 8) -> list[dict]:
    if not query:
        return []
    params = {
        "search_terms": query,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": page_size,
    }
    resp = requests.get(OFF_SEARCH_BASE, params=params, timeout=timeout)
    resp.raise_for_status()
    products = (resp.json().get("products") or [])[:page_size]
    return [build_open_food_facts_product(product) for product in products]
