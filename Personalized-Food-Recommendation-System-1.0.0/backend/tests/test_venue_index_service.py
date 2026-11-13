import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import services.venue_index_service as venue_index
from repositories.storage import StorageRepository
from services.venue_index_service import VenueIndexUnavailable, index_nearby_venues, reset_venue_index_state

MENU = [{"name": "雞腿飯", "calories": 700, "protein": 30, "carbs": 80, "fat": 22, "fiber": 4, "sodium": 800}]
# 等待別的執行緒時的上限；正常情況下不會等到，只是避免測試壞掉時卡住
WAIT = 5


def places(*names):
    return [{"name": name, "address": "台南安平", "google_place_id": f"pid-{name}"} for name in names]


def menu_for_everyone(*args, **kwargs):
    return {"items": MENU}


class ConcurrencyProbe:
    """記錄同時有幾家店在分析。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.started_with = {}

    def enter(self, name):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
            self.started_with[name] = self.running

    def leave(self):
        with self.lock:
            self.running -= 1


class VenueIndexTests(unittest.TestCase):
    def setUp(self):
        self.storage = StorageRepository(None, False, {}, [], [])
        reset_venue_index_state()
        self.addCleanup(reset_venue_index_state)

    def run_index(self, found, enrich, **kwargs):
        return index_nearby_venues(
            self.storage, {"lat": 23.0, "lng": 120.16}, lambda *a, **k: found, enrich, **kwargs
        )

    def test_several_venues_are_analysed_at_the_same_time(self):
        """一家 20~30 秒，一家一家做的話 75 秒只做得完兩三家。"""
        # 四家都到齊才放行：沒有同時跑的話，這裡會等到逾時而失敗
        all_four_running = threading.Barrier(4, timeout=WAIT)

        def menu(name, address, text, deadline=None):
            all_four_running.wait()
            return {"items": MENU}

        summary = self.run_index(places(*[f"店{i}" for i in range(8)]), menu, max_workers=4)

        self.assertEqual(summary["analysed"], 8)
        self.assertEqual(summary["remaining"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["total_cached"], 8)

    def test_counts_cover_every_venue(self):
        for name in ("新鮮店", "過期店", "過期又失敗"):
            self.storage.save_restaurant_menu(name, MENU, venue={"google_place_id": f"pid-{name}"})
        old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        self.storage.mem_restaurant_menus["place:pid-過期店"]["cached_at"] = old
        self.storage.mem_restaurant_menus["place:pid-過期又失敗"]["cached_at"] = old

        def menu(name, address, text, deadline=None):
            if name in {"空白店", "過期又失敗"}:
                return {"items": [], "failure": "no_items"}
            if name == "壞掉店":
                raise RuntimeError("boom")
            return {"items": MENU}

        found = places("新鮮店", "過期店", "過期又失敗", "新店", "空白店", "壞掉店") + [{"name": "  "}]
        summary = self.run_index(found, menu)

        self.assertEqual(summary["found"], 7)
        self.assertEqual(summary["already_cached"], 1)
        self.assertEqual(summary["refreshed"], 2)
        self.assertEqual(summary["analysed"], 2)  # 過期店、新店
        self.assertEqual(summary["failed"], 3)  # 過期又失敗、空白店、壞掉店
        self.assertEqual(summary["remaining"], 0)
        self.assertEqual(summary["cooling_down"], 0)
        self.assertEqual(summary["total_cached"], 4)
        # 過期又失敗的店還留著舊菜單，仍算有菜單
        self.assertEqual(summary["with_menu"], 4)
        # 空白店、壞掉店、沒有店名的那筆
        self.assertEqual(summary["unbuildable"], 3)
        # 做完時「能建的都建了」：進度條才會走到滿
        self.assertEqual(summary["found"] - summary["unbuildable"], summary["with_menu"])

    def test_venues_not_started_before_the_deadline_are_left_for_next_time(self):
        def slow_menu(name, address, text, deadline=None):
            # 保證第一家做完時時間預算已經用完，後面的店不會再送出
            time.sleep(max(0.0, deadline - time.monotonic()) + 0.05)
            return {"items": MENU}

        summary = self.run_index(
            places(*[f"店{i}" for i in range(8)]), slow_menu, budget_seconds=0.5, max_workers=2
        )

        self.assertEqual(summary["analysed"], 2)
        self.assertEqual(summary["remaining"], 6)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["found"] - summary["unbuildable"], summary["with_menu"] + summary["remaining"])

    def test_a_venue_cut_short_by_the_deadline_counts_as_remaining_not_failed(self):
        def menu(name, address, text, deadline=None):
            return {"items": [], "failure": "out_of_budget"}

        summary = self.run_index(places("甲", "乙"), menu)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["remaining"], 2)
        self.assertEqual(summary["unbuildable"], 0)

        # 也不該被記進冷卻名單
        again = self.run_index(places("甲", "乙"), menu_for_everyone)
        self.assertEqual(again["analysed"], 2)
        self.assertEqual(again["cooling_down"], 0)

    def test_fewer_venues_run_at_once_after_a_rate_limit(self):
        probe = ConcurrencyProbe()
        first_three = threading.Barrier(3, timeout=WAIT)
        release = threading.Event()

        def menu(name, address, text, deadline=None):
            probe.enter(name)
            try:
                if name in {"店0", "店1", "店2"}:
                    first_three.wait()
                if name == "店0":
                    return {"items": [], "failure": "rate_limited"}
                if name in {"店1", "店2"}:
                    # 沒有降速的話，店3 會在這段時間裡跟店1、店2 一起跑
                    release.wait(0.3)
                return {"items": MENU}
            finally:
                probe.leave()

        summary = self.run_index(places(*[f"店{i}" for i in range(6)]), menu, max_workers=3)

        self.assertEqual(probe.peak, 3)
        for later in ("店3", "店4", "店5"):
            self.assertLessEqual(probe.started_with[later], 2, probe.started_with)
        self.assertEqual(summary["rate_limited"], 1)
        # 額度滿了不是店家的問題：算還沒建，不算失敗
        self.assertEqual(summary["remaining"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["analysed"], 5)

    def test_the_slower_pace_is_remembered_for_the_next_round(self):
        """前端會馬上送下一輪；只在單次請求裡降速，下一輪又全速撞上額度上限。"""
        def out_of_quota(*args, **kwargs):
            return {"items": [], "failure": "rate_limited"}

        self.run_index(places("甲"), out_of_quota, max_workers=4)

        probe = ConcurrencyProbe()

        def menu(name, address, text, deadline=None):
            probe.enter(name)
            time.sleep(0.05)
            probe.leave()
            return {"items": MENU}

        self.run_index(places("乙", "丙", "丁"), menu, max_workers=4)
        self.assertEqual(probe.peak, 1)

        # 降速的紀錄過期之後恢復全速
        with patch.object(venue_index, "RATE_LIMIT_BACKOFF_SECONDS", -1):
            self.run_index(places("甲"), out_of_quota, max_workers=4)
        both_running = threading.Barrier(2, timeout=WAIT)

        def paired_menu(name, address, text, deadline=None):
            both_running.wait()
            return {"items": MENU}

        summary = self.run_index(places("戊", "己"), paired_menu, max_workers=4)
        self.assertEqual(summary["analysed"], 2)

    def test_a_round_stops_once_every_key_is_out_of_quota(self):
        calls = []

        def menu(name, address, text, deadline=None):
            calls.append(name)
            return {"items": [], "failure": "rate_limited"}

        summary = self.run_index(places(*[f"店{i}" for i in range(6)]), menu, max_workers=1)

        self.assertEqual(calls, ["店0"])
        self.assertEqual(summary["remaining"], 6)
        self.assertEqual(summary["analysed"], 0)

    def test_a_venue_that_failed_is_not_retried_on_the_next_press(self):
        calls = []

        def menu(name, address, text, deadline=None):
            calls.append(name)
            if name == "看不出賣什麼":
                return {"items": [], "failure": "no_items"}
            if name == "會出錯":
                raise RuntimeError("boom")
            return {"items": MENU}

        found = places("看不出賣什麼", "會出錯", "正常店")
        first = self.run_index(found, menu)
        self.assertEqual(first["failed"], 2)
        self.assertEqual(first["analysed"], 1)

        calls.clear()
        second = self.run_index(found, menu)
        self.assertEqual(calls, [])
        self.assertEqual(second["failed"], 0)
        self.assertEqual(second["cooling_down"], 2)
        self.assertEqual(second["already_cached"], 1)
        # 冷卻中的店不算「還沒建」，前端才不會一直自動重送
        self.assertEqual(second["remaining"], 0)
        self.assertEqual(second["unbuildable"], 2)

    def test_the_cooldown_is_kept_in_storage(self):
        """Render 閒置會休眠，冷卻名單放在記憶體的話，重啟就沒了。"""
        self.run_index(places("甲"), lambda *a, **k: {"items": [], "failure": "no_items"})

        # 模擬重啟：行程裡的狀態清空，資料庫還在
        reset_venue_index_state()
        calls = []

        def menu(name, address, text, deadline=None):
            calls.append(name)
            return {"items": MENU}

        summary = self.run_index(places("甲"), menu)

        self.assertEqual(calls, [])
        self.assertEqual(summary["cooling_down"], 1)
        self.assertEqual(self.storage.active_restaurant_menu_failures(["place:pid-甲"]), {"place:pid-甲"})

    def test_the_failure_cooldown_expires(self):
        calls = []

        def menu(name, address, text, deadline=None):
            calls.append(name)
            return {"items": []}

        with patch.object(venue_index, "FAILED_VENUE_COOLDOWN_SECONDS", -1):
            self.run_index(places("甲"), menu)
            self.run_index(places("甲"), menu)
        self.assertEqual(calls, ["甲", "甲"])

    def test_an_unfinished_analysis_gets_a_shorter_cooldown(self):
        def menu(name, address, text, deadline=None):
            return {"items": [], "failure": "inconclusive"}

        with patch.object(self.storage, "mark_restaurant_menu_failure") as mark:
            self.run_index(places("甲"), menu)
        mark.assert_called_once_with("place:pid-甲", "inconclusive", venue_index.INCONCLUSIVE_VENUE_COOLDOWN_SECONDS)
        self.assertLess(venue_index.INCONCLUSIVE_VENUE_COOLDOWN_SECONDS, venue_index.FAILED_VENUE_COOLDOWN_SECONDS)

    def test_models_being_unavailable_is_not_blamed_on_the_venue(self):
        """全部模型 404 是設定或服務的問題，修好後這些店要能馬上再建。"""
        def menu(name, address, text, deadline=None):
            return {"items": [], "failure": "unavailable"}

        first = self.run_index(places("甲"), menu)
        self.assertEqual(first["failed"], 1)

        second = self.run_index(places("甲"), menu_for_everyone)
        self.assertEqual(second["analysed"], 1)
        self.assertEqual(second["cooling_down"], 0)

    def test_a_venue_another_request_is_analysing_is_skipped(self):
        """兩個分頁同時按建檔，同一家店不該被問兩次。"""
        started = threading.Event()
        finish = threading.Event()
        calls = []

        def slow_menu(name, address, text, deadline=None):
            calls.append(name)
            started.set()
            finish.wait(WAIT)
            return {"items": MENU}

        def quick_menu(name, address, text, deadline=None):
            calls.append(name)
            return {"items": MENU}

        first_result = {}
        first = threading.Thread(target=lambda: first_result.update(self.run_index(places("甲"), slow_menu)))
        first.start()
        try:
            self.assertTrue(started.wait(WAIT))
            second = self.run_index(places("甲", "乙"), quick_menu)
        finally:
            finish.set()
            first.join(WAIT)

        self.assertEqual(calls, ["甲", "乙"])
        self.assertEqual(second["in_progress"], 1)
        self.assertEqual(second["remaining"], 1)
        self.assertEqual(second["analysed"], 1)
        self.assertEqual(first_result["analysed"], 1)
        # 做完要放掉，不然之後這家店永遠被當成「別人在做」
        self.assertEqual(venue_index._in_progress, set())

    def test_the_claim_is_released_even_when_saving_fails(self):
        with patch.object(self.storage, "save_restaurant_menu", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.run_index(places("甲"), menu_for_everyone)
        self.assertEqual(venue_index._in_progress, set())

    def test_nothing_nearby_is_reported(self):
        with self.assertRaises(VenueIndexUnavailable):
            self.run_index([], menu_for_everyone)


if __name__ == "__main__":
    unittest.main()
