import json
import os
import random
import re
import requests
from bs4 import BeautifulSoup

from services.nutrition_label_service import (
    decode_image_base64,
    extract_json_block,
    extract_number,
    get_gemini_api_keys,
    get_gemini_models,
)

# Modern User-Agents to prevent anti-bot blocking
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
]

def build_robust_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive"
    })
    return session

def fetch_public_menu_text(url: str) -> str:
    if not url or not url.startswith("http"):
        return ""
    session = build_robust_session()
    try:
        response = session.get(url, timeout=12)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            for s in soup(["script", "style", "nav", "footer"]):
                s.decompose()
            text = soup.get_text(separator="\n")
            cleaned_lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(cleaned_lines[:200])
    except Exception as e:
        print(f"[!] Scraper fetch warning for {url}: {e}")
    return ""

def generate_fallback_menu(restaurant_name: str) -> list[dict]:
    """Generates a highly realistic mock menu based on the restaurant name keyword."""
    name = restaurant_name.lower()
    
    # 1. McDonald's / KFC / Burgers / Fast Food
    if any(k in name for k in ["麥當勞", "肯德基", "漢堡", "美式", "kfc", "mcdonald", "漢堡王", "摩斯"]):
        return [
            {"item_id": "f_burger_1", "name": "經典牛肉起司堡", "price": 95, "calories": 530, "protein": 28.0, "carbs": 40.0, "fat": 26.0, "sodium": 890, "gi": "high", "tags": ["高鈉注意"]},
            {"item_id": "f_burger_2", "name": "麥香魚堡", "price": 49, "calories": 330, "protein": 15.0, "carbs": 38.0, "fat": 13.0, "sodium": 560, "gi": "medium", "tags": ["海鮮類"]},
            {"item_id": "f_burger_3", "name": "去皮烤雞沙拉 (醬料另計)", "price": 99, "calories": 180, "protein": 22.0, "carbs": 8.0, "fat": 6.0, "sodium": 340, "gi": "low", "tags": ["低GI", "高蛋白", "低熱量"]},
            {"item_id": "f_burger_4", "name": "黃金脆薯 (大份)", "price": 60, "calories": 480, "protein": 5.0, "carbs": 62.0, "fat": 24.0, "sodium": 620, "gi": "high", "tags": ["高脂肪", "油炸品"]}
        ]
    
    # 2. Convenience Stores (7-11, FamilyMart)
    if any(k in name for k in ["7-11", "7-eleven", "全家", "便利商店", "超商", "萊爾富", "ok超商"]):
        return [
            {"item_id": "f_store_1", "name": "紐奧良烤雞三明治", "price": 49, "calories": 310, "protein": 14.0, "carbs": 36.0, "fat": 12.0, "sodium": 650, "gi": "medium", "tags": ["蛋白質補給"]},
            {"item_id": "f_store_2", "name": "石安牧場溫泉蛋", "price": 46, "calories": 75, "protein": 7.0, "carbs": 1.0, "fat": 5.0, "sodium": 180, "gi": "low", "tags": ["低GI", "高蛋白", "低熱量"]},
            {"item_id": "f_store_3", "name": "健身G肉餐盒", "price": 95, "calories": 480, "protein": 32.0, "carbs": 58.0, "fat": 11.0, "sodium": 780, "gi": "low", "tags": ["高蛋白", "低GI"]},
            {"item_id": "f_store_4", "name": "無糖高纖豆漿", "price": 25, "calories": 146, "protein": 13.0, "carbs": 8.0, "fat": 7.0, "sodium": 55, "gi": "low", "tags": ["低GI", "高纖", "低鈉"]}
        ]
        
    # 3. Japanese Restaurants / Yoshinoya / Sushi / Ramen
    if any(k in name for k in ["吉野家", "日式", "壽司", "拉麵", "丼", "定食", "爭鮮", "烏龍麵"]):
        return [
            {"item_id": "f_jap_1", "name": "經典牛丼 (中份)", "price": 125, "calories": 680, "protein": 24.0, "carbs": 85.0, "fat": 25.0, "sodium": 920, "gi": "high", "tags": ["高飽足"]},
            {"item_id": "f_jap_2", "name": "鹽烤鯖魚定食", "price": 180, "calories": 540, "protein": 28.0, "carbs": 55.0, "fat": 22.0, "sodium": 880, "gi": "low", "tags": ["優質脂肪", "低GI"]},
            {"item_id": "f_jap_3", "name": "綜合握壽司 (6貫)", "price": 120, "calories": 360, "protein": 18.0, "carbs": 54.0, "fat": 6.0, "sodium": 450, "gi": "medium", "tags": ["海產"]},
            {"item_id": "f_jap_4", "name": "和風海帶芽沙拉", "price": 40, "calories": 45, "protein": 1.0, "carbs": 8.0, "fat": 0.5, "sodium": 320, "gi": "low", "tags": ["高纖", "低脂"]}
        ]

    # 4. Coffee Shops / Starbucks / Louisa
    if any(k in name for k in ["星巴克", "咖啡", "cafe", "路易莎", "louisa", "cama", "甜點", "下午茶"]):
        return [
            {"item_id": "f_cafe_1", "name": "美式咖啡 (無糖去冰/大杯)", "price": 95, "calories": 15, "protein": 0.5, "carbs": 3.0, "fat": 0.0, "sodium": 15, "gi": "low", "tags": ["零卡", "低鈉", "低GI"]},
            {"item_id": "f_cafe_2", "name": "經典拿鐵 (無糖/燕麥奶)", "price": 120, "calories": 170, "protein": 5.0, "carbs": 22.0, "fat": 6.0, "sodium": 90, "gi": "medium", "tags": ["植物奶"]},
            {"item_id": "f_cafe_3", "name": "凱薩雞肉起司烤捲餅", "price": 85, "calories": 380, "protein": 18.0, "carbs": 35.0, "fat": 16.0, "sodium": 740, "gi": "medium", "tags": ["蛋白質"]},
            {"item_id": "f_cafe_4", "name": "黑森林巧克力蛋糕", "price": 90, "calories": 350, "protein": 4.5, "carbs": 48.0, "fat": 15.0, "sodium": 180, "gi": "high", "tags": ["高糖高熱量"]}
        ]

    # 5. Hotpot (火鍋)
    if any(k in name for k in ["鍋", "火鍋", "涮涮鍋", "麻辣", "石二鍋"]):
        return [
            {"item_id": "f_pot_1", "name": "精選板腱牛肉鍋盤", "price": 268, "calories": 420, "protein": 38.0, "carbs": 5.0, "fat": 26.0, "sodium": 380, "gi": "low", "tags": ["優質高蛋白"]},
            {"item_id": "f_pot_2", "name": "健康低卡時蔬盤 (無火鍋料)", "price": 120, "calories": 150, "protein": 6.0, "carbs": 24.0, "fat": 2.0, "sodium": 190, "gi": "low", "tags": ["高纖", "低鈉", "低GI"]},
            {"item_id": "f_pot_3", "name": "川味麻辣湯底", "price": 80, "calories": 350, "protein": 4.0, "carbs": 12.0, "fat": 32.0, "sodium": 2800, "gi": "medium", "tags": ["超高鈉警示", "高脂肪"]}
        ]

    # 6. Italian Restaurants / Pasta / Pizza / Saizeriya
    if any(k in name for k in ["薩莉亞", "義大利", "麵店", "pasta", "pizza", "比薩", "焗烤"]):
        return [
            {"item_id": "f_ital_1", "name": "經典蕃茄肉醬義大利麵", "price": 110, "calories": 580, "protein": 22.0, "carbs": 80.0, "fat": 18.0, "sodium": 950, "gi": "medium", "tags": ["碳水補給"]},
            {"item_id": "f_ital_2", "name": "地中海嫩煎雞肉沙拉", "price": 99, "calories": 240, "protein": 20.0, "carbs": 12.0, "fat": 12.0, "sodium": 480, "gi": "low", "tags": ["高纖", "低GI"]},
            {"item_id": "f_ital_3", "name": "瑪格麗特比薩 (個人份)", "price": 120, "calories": 620, "protein": 24.0, "carbs": 78.0, "fat": 22.0, "sodium": 1120, "gi": "high", "tags": ["高脂肪", "高鈉"]}
        ]

    # 7. Dumplings / Bafang
    if "餃" in name or "八方" in name or "鍋貼" in name:
        return [
            {"item_id": "f_1", "name": "招牌鍋貼 (10顆)", "price": 65, "calories": 640, "protein": 22.0, "carbs": 70.0, "fat": 30.0, "sodium": 580, "gi": "medium", "tags": ["經典熱銷"]},
            {"item_id": "f_2", "name": "高麗菜水餃 (10顆)", "price": 65, "calories": 520, "protein": 20.0, "carbs": 64.0, "fat": 20.0, "sodium": 480, "gi": "medium", "tags": ["均衡高飽足"]},
            {"item_id": "f_3", "name": "酸辣湯", "price": 35, "calories": 140, "protein": 6.0, "carbs": 18.0, "fat": 5.0, "sodium": 820, "gi": "medium", "tags": ["高鈉注意"]},
            {"item_id": "f_4", "name": "寒天真規豆漿 (無糖)", "price": 20, "calories": 115, "protein": 11.0, "carbs": 5.0, "fat": 6.0, "sodium": 35, "gi": "low", "tags": ["高蛋白", "低GI", "低鈉"]}
        ]
    
    # 8. Bento / Porkchop (梁社漢等)
    if "便當" in name or "排骨" in name or "梁社漢" in name or "雞腿" in name or "燒肉" in name or "自助餐" in name:
        return [
            {"item_id": "f_1", "name": "炸排骨飯便當", "price": 115, "calories": 920, "protein": 34.0, "carbs": 110.0, "fat": 38.0, "sodium": 1240, "gi": "high", "tags": ["高熱量"]},
            {"item_id": "f_2", "name": "滷雞腿飯便當", "price": 120, "calories": 780, "protein": 42.0, "carbs": 105.0, "fat": 24.0, "sodium": 980, "gi": "medium", "tags": ["高蛋白"]},
            {"item_id": "f_3", "name": "清蒸時蔬豆腐盤", "price": 75, "calories": 190, "protein": 14.0, "carbs": 12.0, "fat": 8.0, "sodium": 320, "gi": "low", "tags": ["高纖", "低GI", "低鈉"]},
            {"item_id": "f_4", "name": "單點滷排骨", "price": 80, "calories": 280, "protein": 24.0, "carbs": 12.0, "fat": 15.0, "sodium": 680, "gi": "medium", "tags": ["高蛋白"]}
        ]

    # 9. Beef Noodles
    if "牛肉麵" in name or "麵館" in name or "老張" in name or "小吃" in name:
        return [
            {"item_id": "f_1", "name": "紅燒牛肉麵 (大份)", "price": 180, "calories": 850, "protein": 48.0, "carbs": 95.0, "fat": 30.0, "sodium": 2100, "gi": "medium", "tags": ["高高鈉", "高蛋白"]},
            {"item_id": "f_2", "name": "清燉腱子肉麵", "price": 170, "calories": 620, "protein": 45.0, "carbs": 88.0, "fat": 10.0, "sodium": 1450, "gi": "medium", "tags": ["高蛋白", "低脂"]},
            {"item_id": "f_3", "name": "涼拌小黃瓜", "price": 40, "calories": 65, "protein": 1.5, "carbs": 6.0, "fat": 4.0, "sodium": 290, "gi": "low", "tags": ["低鈉", "低GI", "高纖"]},
            {"item_id": "f_4", "name": "皮蛋豆腐", "price": 50, "calories": 220, "protein": 16.0, "carbs": 8.0, "fat": 14.0, "sodium": 420, "gi": "low", "tags": ["高蛋白", "低GI"]}
        ]

    # 10. Tea / Drinks
    if "茶" in name or "飲" in name or "舖" in name or "飲料" in name or "50嵐" in name or "coCo" in name:
        return [
            {"item_id": "f_1", "name": "四季春茶 (無糖去冰)", "price": 30, "calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "sodium": 10, "gi": "low", "tags": ["零卡", "低鈉", "低GI"]},
            {"item_id": "f_2", "name": "珍珠鮮奶茶 (半糖)", "price": 65, "calories": 420, "protein": 6.0, "carbs": 68.0, "fat": 14.0, "sodium": 110, "gi": "high", "tags": ["高糖警告"]},
            {"item_id": "f_3", "name": "燕麥拿鐵 (無糖)", "price": 75, "calories": 180, "protein": 4.5, "carbs": 24.0, "fat": 7.0, "sodium": 95, "gi": "medium", "tags": ["植物奶"]}
        ]

    # Default fallback (return empty list if completely unknown)
    return []



def validate_and_balance_nutrition(item: dict) -> dict:
    """
    Validates and balances nutrient numbers so that:
    Calories roughly equals (Protein*4 + Carbs*4 + Fat*9).
    Also ensures sugar <= carbs, saturated_fat <= fat, etc.
    """
    calories = float(item.get("calories", 0) or 0)
    protein = float(item.get("protein", 0) or 0)
    carbs = float(item.get("carbs", 0) or 0)
    fat = float(item.get("fat", 0) or 0)
    
    # Check physical calorie consistency (1g P=4, 1g C=4, 1g F=9)
    calculated_calories = protein * 4.0 + carbs * 4.0 + fat * 9.0
    if calories > 0 and abs(calculated_calories - calories) > 80:
        if fat * 9.0 > calories:
            fat = max(0.0, round((calories - protein * 4.0 - carbs * 4.0) / 9.0, 1))
        else:
            calories = round(calculated_calories)
    elif calories <= 0 and calculated_calories > 0:
        calories = round(calculated_calories)
            
    sugar = float(item.get("sugar", 0) or 0)
    if sugar > carbs and carbs > 0:
        sugar = round(carbs * 0.4, 1)
        
    saturated_fat = float(item.get("saturated_fat", 0) or 0)
    if saturated_fat > fat and fat > 0:
        saturated_fat = round(fat * 0.35, 1)
        
    trans_fat = float(item.get("trans_fat", 0) or 0)
    if trans_fat > fat:
        trans_fat = 0.0
        
    name = item.get("name", "")

    fiber = float(item.get("fiber", 0) or 0)
    if fiber == 0:
        if any(k in name for k in ["蔬菜", "青菜", "沙拉", "菇", "海帶"]):
            fiber = 3.5
        elif any(k in name for k in ["飯", "麵", "吐司", "漢堡", "燕麥", "水果"]):
            fiber = 2.0
        elif any(k in name for k in ["豆漿", "豆腐", "豆乾"]):
            fiber = 1.5
        else:
            fiber = 0.5

    item["calories"] = round(calories)
    item["protein"] = round(protein, 1)
    item["carbs"] = round(carbs, 1)
    item["fat"] = round(fat, 1)
    item["sugar"] = round(sugar, 1)
    item["saturated_fat"] = round(saturated_fat, 1)
    item["trans_fat"] = round(trans_fat, 1)
    item["fiber"] = round(fiber, 1)
    item["sodium"] = round(float(item.get("sodium", 0) or 0))
    item["is_fried"] = item.get("is_fried", False) or any(k in item.get("name", "") for k in ["炸", "脆", "酥"])
    return item


def enrich_restaurant_with_gemini(restaurant_name: str, address: str, scraped_text: str = "") -> dict:
    keys = get_gemini_api_keys()
    if not keys:
        print("[!] No Gemini API key found for scraper - using realistic templates")
        fallback_items = [validate_and_balance_nutrition(item) for item in generate_fallback_menu(restaurant_name)]
        return {"items": fallback_items}
    
    prompt = f"""
    你是一位台灣經驗豐富的臨床膳食評估師與營養師。
    請根據這家台灣餐廳的名稱與描述，產生該餐廳最經典常見的 4~6 道餐點，並為每道餐點精準估算 11 項營養指標（需符合 1g蛋白質=4kcal, 1g碳水=4kcal, 1g脂肪=9kcal 熱量平衡公式）：

    餐廳名稱：{restaurant_name}
    餐廳地址：{address}
    網頁文字參考：{scraped_text[:500]}

    請輸出合法 JSON 格式（不要包含任何 markdown codeblock 或文字說明）：
    {{
      "items": [
        {{
          "item_id": "m_001",
          "name": "餐點名稱",
          "price": 120,
          "calories": 480,
          "protein": 32.0,
          "carbs": 45.0,
          "fat": 14.0,
          "sugar": 2.0,
          "saturated_fat": 3.5,
          "trans_fat": 0.0,
          "fiber": 3.0,
          "sodium": 420,
          "is_fried": false,
          "gi": "low",
          "allergens": [],
          "tags": ["高蛋白", "低GI"]
        }}
      ]
    }}
    """
    # 全 repo 其他 Gemini 呼叫都用 get_gemini_models()（可由 GEMINI_MODELS 覆寫）。
    # 這裡原本寫死 2.5-flash / 2.5-pro，金鑰沒有這兩個模型權限時整串 404，
    # 最後退回 generate_fallback_menu()，而真實店名不在樣板清單裡會回空陣列。
    candidate_models = get_gemini_models()
    unavailable_models = set()
    for gemini_key in keys:
        for model_name in candidate_models:
            # 模型不存在是帳號層級的事，換一把金鑰重試同一個模型只是浪費時間
            if model_name in unavailable_models:
                continue
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"response_mime_type": "application/json"}
                }
                res = requests.post(url, json=payload, timeout=20)
                if res.status_code == 200:
                    parsed_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    items = extract_json_block(parsed_text).get("items", [])
                    if items:
                        print(f"[Scraper] Successfully generated menu using key {gemini_key[:8]}... model: {model_name}")
                        balanced_items = [validate_and_balance_nutrition(item) for item in items]
                        return {"items": balanced_items}
                else:
                    if res.status_code == 404:
                        unavailable_models.add(model_name)
                    print(f"[!] Key {gemini_key[:8]}... model {model_name} status {res.status_code}, trying next key/model...")
            except Exception as e:
                print(f"[!] Gemini Model {model_name} error: {e}")

    if len(unavailable_models) == len(candidate_models):
        print(f"[!] 所有模型都回 404：{sorted(unavailable_models)}。請用 GEMINI_MODELS 指定金鑰有權限的模型。")
    fallback_items = [validate_and_balance_nutrition(item) for item in generate_fallback_menu(restaurant_name)]
    return {"items": fallback_items}


def _normalize_menu_items(raw_items) -> list[dict]:
    """Normalize the few fields needed to safely display an OCR menu result."""
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []

    normalized = []
    ignored_names = {"品名", "品項", "價格", "金額", "數量", "合計", "總計", "外帶", "內用"}
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        name = raw_item.get("name") or raw_item.get("item_name") or raw_item.get("dish_name")
        if not isinstance(name, str):
            continue
        name = re.sub(r"\s+", " ", name).strip()
        if not name or name in ignored_names:
            continue

        price = extract_number(
            raw_item.get("price") or raw_item.get("price_twd") or raw_item.get("價格"),
            as_int=True,
        )
        if price is None or price <= 0:
            continue

        item = dict(raw_item)
        item["name"] = name
        item["item_id"] = str(item.get("item_id") or f"menu_{index + 1:03d}")
        item["price"] = price
        normalized.append(item)

    items_by_name = {}
    for item in normalized:
        items_by_name.setdefault(item["name"], []).append(item)
    for same_name_items in items_by_name.values():
        prices = {item["price"] for item in same_name_items}
        if len(same_name_items) == 2 and len(prices) == 2:
            small, large = sorted(same_name_items, key=lambda item: item["price"])
            small["name"] += " (小)"
            large["name"] += " (大)"
    return normalized


def _extract_menu_items_from_response(body: dict) -> tuple[list[dict], str | None]:
    """Read Gemini text from all response parts and recover partial OCR when needed."""
    candidate = (body.get("candidates") or [{}])[0]
    finish_reason = candidate.get("finishReason")
    parts = (candidate.get("content") or {}).get("parts") or []
    response_text = "\n".join(
        part.get("text", "") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    if not response_text:
        return [], finish_reason

    try:
        parsed = extract_json_block(response_text)
        items = parsed.get("items") or parsed.get("menu_items") or parsed.get("dishes") or []
        return _normalize_menu_items(items), finish_reason
    except (AttributeError, TypeError, ValueError, KeyError):
        # A dense menu can hit the output limit after several complete rows.
        # Recover those rows instead of throwing away the usable prefix.
        recovered = []
        for object_text in re.findall(r"\{[^{}]+\}", response_text):
            try:
                parsed_object = json.loads(object_text)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed_object, dict) and any(
                key in parsed_object for key in ("name", "item_name", "dish_name")
            ):
                recovered.append(parsed_object)
        if recovered:
            return _normalize_menu_items(recovered), finish_reason

        pattern = re.compile(
            r"[\"'](?:name|item_name|dish_name)[\"']\s*:\s*[\"']([^\"']+)[\"']"
            r"[\s\S]{0,180}?[\"'](?:price|price_twd|價格)[\"']\s*:\s*[\"']?([0-9]+)"
        )
        for index, match in enumerate(pattern.finditer(response_text)):
            recovered.append({"item_id": f"menu_{index + 1:03d}", "name": match.group(1), "price": int(match.group(2))})
        return _normalize_menu_items(recovered), finish_reason


def parse_menu_image_with_gemini(image_base64: str, restaurant_name: str = "餐廳") -> dict:
    """Use Gemini Vision to OCR a menu photo, returning status details for the UI."""
    if not image_base64:
        return {"items": [], "recognition_status": "error", "recognition_error": "缺少菜單圖片"}

    try:
        _img_bytes, image_base64, image_mime_type = decode_image_base64(image_base64)
    except ValueError as e:
        print(f"[!] Menu photo decode failed: {e}")
        return {"items": [], "recognition_status": "error", "recognition_error": str(e)}

    keys = get_gemini_api_keys()
    if not keys:
        print("[!] No Gemini API key found for menu image parsing")
        return {
            "items": [],
            "recognition_status": "error",
            "recognition_error": "後端未設定 Gemini API key，請在 Render 設定 GEMINI_API_KEYS 後重新部署。",
        }
    
    prompt = f"""
    你是一位台灣經驗豐富的臨床膳食評估師與營養師。
    請識別這張「{restaurant_name}」實體菜單照片中的餐點名稱與價格。這張照片可能是密集的價目表或菜單看板，
    上面可能有非常多品項（十幾到數十項都有可能）；請務必逐一列出照片中「每一項」看得到的餐點，不要只挑幾項
    或只列出範例，也不要因為品項太多而省略。即使照片邊緣模糊、部分文字不清楚，仍請根據可辨識的部分盡量列出
    合理的品項名稱與價格，不要整個放棄辨識。沒有標示價格的分類標題（例如飲料、啤酒）不要當作品項；同一道餐點
    若有小碗／大碗兩個價格，請分成兩筆，並在名稱中明確加上「(小)」與「(大)」。

    為每道餐點估算 11 項營養指標即可，數值不需要非常精確，合理概略估計即可（後端會另外做物理一致性校正，
    1g蛋白質=4kcal, 1g碳水=4kcal, 1g脂肪=9kcal，你不需要自己保證完全吻合）：

    請輸出合法 JSON 格式（不要包含任何 markdown codeblock 或文字說明）：
    {{
      "items": [
        {{
          "item_id": "m_001",
          "name": "餐點名稱",
          "price": 120,
          "calories": 480,
          "protein": 32.0,
          "carbs": 45.0,
          "fat": 14.0,
          "sugar": 2.0,
          "saturated_fat": 3.5,
          "trans_fat": 0.0,
          "fiber": 3.0,
          "sodium": 420,
          "is_fried": false,
          "gi": "low",
          "allergens": [],
          "tags": ["高蛋白", "低GI"]
        }}
      ]
    }}
    """
    candidate_models = get_gemini_models()
    last_error = "Gemini 未回傳可用的菜單品項"
    for gemini_key in keys:
        for model_name in candidate_models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inline_data": {
                                        "mime_type": image_mime_type,
                                        "data": image_base64
                                    }
                                }
                            ]
                        }
                    ],
                    "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 8192}
                }
                res = requests.post(url, json=payload, timeout=25)
                if res.status_code == 200:
                    body = res.json()
                    items, finish_reason = _extract_menu_items_from_response(body)
                    if items:
                        print(f"[Scraper] Successfully parsed menu photo using key {gemini_key[:8]}... model: {model_name}, {len(items)} items")
                        balanced_items = [validate_and_balance_nutrition(item) for item in items]
                        return {
                            "items": balanced_items,
                            "recognition_status": "recognized",
                            "recognition_model": model_name,
                        }
                    last_error = f"Gemini 回傳 0 個品項（finishReason={finish_reason or 'unknown'}）"
                    print(f"[!] Key {gemini_key[:8]}... Vision model {model_name} returned zero items (finishReason={finish_reason}), trying next key/model...")
                else:
                    try:
                        api_message = (res.json().get("error") or {}).get("message", "")
                    except (TypeError, ValueError):
                        api_message = ""
                    if res.status_code == 429:
                        last_error = "Gemini 使用額度已達上限，請稍後再試，或在 Render 更新 GEMINI_API_KEYS。"
                    elif res.status_code in (401, 403):
                        last_error = "Gemini API key 無效或沒有模型存取權限，請檢查 Render 的 GEMINI_API_KEYS。"
                    elif res.status_code == 503:
                        last_error = "Gemini 目前服務繁忙，請稍後再試。"
                    else:
                        last_error = f"Gemini 暫時無法辨識菜單（HTTP {res.status_code}）。"
                    print(f"[!] Key {gemini_key[:8]}... Vision model {model_name} status {res.status_code}: {api_message[:180]}")
            except Exception as e:
                last_error = "Gemini Vision 連線失敗，請稍後再試。"
                print(f"[!] Gemini Vision error with model {model_name}: {type(e).__name__}")

    return {"items": [], "recognition_status": "error", "recognition_error": last_error}

