"""把附近店家的菜單建檔進資料庫。

Google Places 只給店名與位置，沒有菜色營養，所以推薦要逐道菜比對疾病禁忌，
就得先有菜單。分析一家店要 20~30 秒，不可能塞在使用者等待的請求裡完成，
因此獨立成一個可以重複執行、逐次累積的動作。

（原本這段程式住在 week_seed_service.py，隨「灌入七天」的測試資料功能一起
移除時抽出來——推薦功能依賴它，它不屬於測試工具。）
"""

import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

# 一次請求最多花在 Gemini 菜單分析上的秒數。超過就留給下一次按。
MENU_ANALYSIS_BUDGET_SECONDS = 75

# 一家一家做，75 秒只做得完兩三家，附近 20 家要按上好幾次。
# 同時分析幾家；遇到 429（額度用完）就少開一條，免得越催越擠。
MAX_CONCURRENT_ANALYSES = 4

# 降速要記一陣子：前端會馬上送下一輪，只在單次請求裡降速的話，
# 下一輪又會全速撞上同一個額度上限。
RATE_LIMIT_BACKOFF_SECONDS = 90

# 問不出菜單的店家冷卻多久。紀錄存在資料庫（storage.mark_restaurant_menu_failure），
# 短時間內再按不會把時間預算又燒在同一家上。
FAILED_VENUE_COOLDOWN_SECONDS = 6 * 60 * 60  # 每個模型都說看不出來，或分析直接出錯
INCONCLUSIVE_VENUE_COOLDOWN_SECONDS = 30 * 60  # 有模型逾時或出錯，沒問完

# 這兩種不是店家的問題（時間到了、額度滿了），算「還沒建」，下一輪再試。
_RETRY_LATER = {"out_of_budget", "rate_limited"}

_state_lock = threading.Lock()
# 別的請求正在分析的店家。兩個分頁同時按建檔時，同一家店不必問兩次。
_in_progress: set[str] = set()
_backoff = {"workers": MAX_CONCURRENT_ANALYSES, "until": 0.0}


class VenueIndexUnavailable(Exception):
    """建檔拿不到店家或菜單。對應 HTTP 409，並說明原因。"""


def _cooldown_for(failure: str) -> float:
    if failure == "unavailable":
        # 沒有任何模型能用是設定或服務的問題，修好之後這些店要能馬上再建
        return 0
    if failure == "inconclusive":
        return INCONCLUSIVE_VENUE_COOLDOWN_SECONDS
    return FAILED_VENUE_COOLDOWN_SECONDS


def _claim(keys: set[str]) -> set[str]:
    """把還沒有其他請求在做的店家登記下來，回傳登記到的。"""
    with _state_lock:
        claimed = keys - _in_progress
        _in_progress.update(claimed)
    return claimed


def _release(keys: set[str]) -> None:
    with _state_lock:
        _in_progress.difference_update(keys)


def _allowed_workers(max_workers: int) -> int:
    with _state_lock:
        if time.monotonic() < _backoff["until"]:
            return min(max_workers, _backoff["workers"])
    return max_workers


def _remember_backoff(workers: int) -> None:
    with _state_lock:
        _backoff["workers"] = workers
        _backoff["until"] = time.monotonic() + RATE_LIMIT_BACKOFF_SECONDS


def reset_venue_index_state() -> None:
    """清掉進行中名單與降速紀錄（測試用）。"""
    with _state_lock:
        _in_progress.clear()
        _backoff["workers"] = MAX_CONCURRENT_ANALYSES
        _backoff["until"] = 0.0


def index_nearby_venues(
    storage,
    params: dict,
    fetch_places,
    enrich_restaurant,
    budget_seconds: float = MENU_ANALYSIS_BUDGET_SECONDS,
    max_workers: int = MAX_CONCURRENT_ANALYSES,
) -> dict:
    """把附近店家的菜單建檔進資料庫。

    分析一家店要 20~30 秒，所以同時分析幾家，在時間預算內能做多少做多少；
    做不完的回報在 remaining，前端會自動再送一次。
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
    # 現在有菜單可用的店家（包含過期、這次沒更新成功的）
    with_menu = 0
    # 這次怎樣都建不出菜單的店家：沒有店名、問不出來、還在冷卻中
    unbuildable = 0
    candidates = []
    for place in places:
        name = str(place.get("name", "")).strip()
        if not name:
            unbuildable += 1
            continue
        place_id = str(place.get("google_place_id") or "").strip()
        cached = storage.get_restaurant_menu(name, place_id)
        if cached:
            with_menu += 1
        # 太舊的快取要重新分析：店家會改菜單、漲價、換營業時間
        if cached and not storage.restaurant_menu_is_stale(cached):
            already_cached += 1
            continue
        if cached:
            refreshed += 1
        key = storage.venue_cache_key(name, place_id)
        candidates.append((place, name, place_id, key, bool(cached)))

    cooling = storage.active_restaurant_menu_failures([candidate[3] for candidate in candidates])
    cooling_down = 0
    in_progress = 0
    claimed = _claim({candidate[3] for candidate in candidates if candidate[3] not in cooling})
    todo = deque()
    taken = set()
    for candidate in candidates:
        key, has_menu = candidate[3], candidate[4]
        if key in cooling:
            cooling_down += 1
            if not has_menu:
                unbuildable += 1
        elif key in claimed and key not in taken:
            taken.add(key)
            todo.append(candidate)
        else:
            # 另一個請求正在分析這家店
            in_progress += 1

    def analyse(name: str, address: str) -> dict:
        try:
            return enrich_restaurant(name, address, "", deadline) or {}
        except Exception as error:
            print(f"[venue-index] {name} 菜單分析失敗: {error}")
            return {"items": [], "failure": "error"}

    # 計數與資料庫寫入只在這個（呼叫端的）執行緒裡做；工作執行緒只負責問 Gemini。
    analysed = 0
    failed = 0
    rate_limited = 0
    remaining = in_progress
    try:
        if todo:
            workers = max(1, min(_allowed_workers(max_workers), len(todo)))
            quota_exhausted = False
            with ThreadPoolExecutor(max_workers=workers) as pool:
                in_flight = {}
                while todo or in_flight:
                    while (
                        todo
                        and not quota_exhausted
                        and len(in_flight) < workers
                        and time.monotonic() < deadline
                    ):
                        candidate = todo.popleft()
                        place, name = candidate[0], candidate[1]
                        in_flight[pool.submit(analyse, name, place.get("address") or "台灣")] = candidate
                    if not in_flight:
                        break  # 時間到了或額度用完，剩下的留給下一次
                    done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                    for future in done:
                        place, name, place_id, key, has_menu = in_flight.pop(future)
                        enriched = future.result()
                        items = enriched.get("items") or []
                        if items:
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
                            if not has_menu:
                                with_menu += 1
                            continue
                        failure = enriched.get("failure") or "no_items"
                        if failure == "rate_limited":
                            rate_limited += 1
                            # 只剩一條還撞到 429，就是每把金鑰都用完了，這一輪先停
                            if workers == 1:
                                quota_exhausted = True
                            workers = max(1, workers - 1)
                            _remember_backoff(workers)
                        if failure in _RETRY_LATER:
                            remaining += 1
                            continue
                        failed += 1
                        if not has_menu:
                            unbuildable += 1
                        cooldown = _cooldown_for(failure)
                        if cooldown > 0:
                            storage.mark_restaurant_menu_failure(key, failure, cooldown)
        remaining += len(todo)
    finally:
        _release(claimed)

    return {
        "found": len(places),
        "already_cached": already_cached,
        "refreshed": refreshed,
        "analysed": analysed,
        "failed": failed,
        # 先前問不出菜單、還在冷卻中而這次沒再問的店家
        "cooling_down": cooling_down,
        # 另一個請求正在分析、這次跳過的店家（已算在 remaining 裡）
        "in_progress": in_progress,
        # 因 Gemini 額度用完而這次沒建成的店家（已算在 remaining 裡）
        "rate_limited": rate_limited,
        "remaining": remaining,
        "with_menu": with_menu,
        "unbuildable": unbuildable,
        "total_cached": storage.count_restaurant_menus(),
    }
