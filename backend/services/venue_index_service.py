"""把附近店家的菜單建檔進資料庫。

Google Places 只給店名與位置，沒有菜色營養，所以推薦要逐道菜比對疾病禁忌，
就得先有菜單。分析一家店要 20~30 秒，不可能塞在使用者等待的請求裡完成，
因此獨立成一個可以重複執行、逐次累積的動作。

（原本這段程式住在 week_seed_service.py，隨「灌入七天」的測試資料功能一起
移除時抽出來——推薦功能依賴它，它不屬於測試工具。）
"""

import time

# 一次請求最多花在 Gemini 菜單分析上的秒數。超過就留給下一次按。
MENU_ANALYSIS_BUDGET_SECONDS = 75


class VenueIndexUnavailable(Exception):
    """建檔拿不到店家或菜單。對應 HTTP 409，並說明原因。"""


def index_nearby_venues(
    storage,
    params: dict,
    fetch_places,
    enrich_restaurant,
    budget_seconds: float = MENU_ANALYSIS_BUDGET_SECONDS,
) -> dict:
    """把附近店家的菜單建檔進資料庫。

    分析一家店要 20~30 秒，一次做完全部會逾時。所以做成可以重複按的
    動作，每次在時間預算內處理幾家還沒建過或太舊的，累積下去。
    """
    lat = float(params.get("lat", 25.0338))
    lng = float(params.get("lng", 121.5645))
    radius_km = min(max(float(params.get("radius_km", 3)), 0.5), 10)
    category = str(params.get("category", "all") or "all").strip().lower()
    budget = int(params.get("budget", 150))
    limit = min(max(int(params.get("limit", 20)), 1), 20)

    try:
        places = fetch_places(lat, lng, radius_km, category, budget, limit=limit)
    except Exception as error:
        raise VenueIndexUnavailable(f"店家搜尋失敗：{error}") from error
    if not places:
        raise VenueIndexUnavailable(f"半徑 {radius_km} km 內搜尋不到店家，請調整定位或把半徑放大。")

    deadline = time.monotonic() + budget_seconds
    already_cached = 0
    refreshed = 0
    analysed = 0
    failed = 0
    remaining = 0
    for place in places:
        name = str(place.get("name", "")).strip()
        if not name:
            continue
        place_id = str(place.get("google_place_id") or "").strip()
        cached = storage.get_restaurant_menu(name, place_id)
        # 太舊的快取要重新分析：店家會改菜單、漲價、換營業時間
        if cached and not storage.restaurant_menu_is_stale(cached):
            already_cached += 1
            continue
        if cached:
            refreshed += 1
        if time.monotonic() >= deadline:
            remaining += 1
            continue
        try:
            enriched = enrich_restaurant(name, place.get("address") or "台灣", "", deadline)
        except Exception as error:
            print(f"[venue-index] {name} 菜單分析失敗: {error}")
            failed += 1
            continue
        items = enriched.get("items", []) or []
        if not items:
            failed += 1
            continue
        storage.save_restaurant_menu(
            name,
            items,
            venue={
                "address": place.get("address", ""),
                "lat": place.get("lat"),
                "lng": place.get("lng"),
                "google_place_id": place_id,
                # 存下來才查得出這筆快取是什麼時候、什麼狀態下建的
                "business_status": place.get("business_status", ""),
                "is_open_at_index_time": place.get("is_open"),
                "opening_periods": place.get("opening_periods") or [],
            },
        )
        analysed += 1

    return {
        "found": len(places),
        "already_cached": already_cached,
        "refreshed": refreshed,
        "analysed": analysed,
        "failed": failed,
        "remaining": remaining,
        "total_cached": storage.count_restaurant_menus(),
    }
