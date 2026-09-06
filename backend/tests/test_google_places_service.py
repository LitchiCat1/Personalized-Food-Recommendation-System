import os
import unittest
from unittest.mock import patch

from services.google_places_service import _fetch_new_places_api, clear_search_cache, fetch_google_places_restaurants


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def new_places_api_place():
    return {
        "geometry": {"location": {"lat": 25.0338, "lng": 121.5645}},
        "name": "測試店",
        "vicinity": "台北",
        "place_id": "p1",
        "rating": 4.5,
        "user_ratings_total": 100,
        "price_level": 2,
        "opening_hours": {"open_now": True},
        "types": ["restaurant"],
        "website": None,
        "url": None,
        "_new_places_api": True,
    }


def legacy_place_result():
    return {
        "place_id": "place-1",
        "name": "Healthy Bento",
        "vicinity": "Taipei",
        "geometry": {"location": {"lat": 25.0338, "lng": 121.5645}},
        "opening_hours": {"open_now": True},
        "types": ["restaurant"],
        "rating": 4.5,
        "user_ratings_total": 42,
        "price_level": 1,
    }


class GooglePlacesServiceTests(unittest.TestCase):
    def setUp(self):
        clear_search_cache()

    @patch("services.google_places_service.requests.post")
    def test_new_places_result_keeps_public_links_from_field_mask(self, mock_post):
        mock_post.return_value = FakeResponse(200, {
            "places": [{
                "id": "new-place-1",
                "displayName": {"text": "New Places Bento"},
                "formattedAddress": "Taipei",
                "location": {"latitude": 25.0338, "longitude": 121.5645},
                "types": ["restaurant"],
                "websiteUri": "https://bento.example/menu",
                "googleMapsUri": "https://maps.google.com/?cid=456",
            }],
        })

        places = _fetch_new_places_api(25.0338, 121.5645, 3000, "test-key")

        self.assertEqual(places[0]["website"], "https://bento.example/menu")
        self.assertEqual(places[0]["url"], "https://maps.google.com/?cid=456")
        self.assertIn("places.websiteUri", mock_post.call_args.kwargs["headers"]["X-Goog-FieldMask"])

    @patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-key", "GOOGLE_MAPS_API_KEY": ""}, clear=False)
    @patch("services.google_places_service._fetch_new_places_api")
    def test_repeated_search_reuses_cache_instead_of_billing_again(self, mock_new):
        """Places API (New) 依 field mask 計費，連按更新地圖不該每次都送出請求。"""
        mock_new.return_value = [new_places_api_place()]

        for _ in range(5):
            fetch_google_places_restaurants(25.0338, 121.5645, 3, "all", 150, limit=6)
        self.assertEqual(mock_new.call_count, 1)

        fetch_google_places_restaurants(25.0338, 121.5645, 5, "all", 150, limit=6)  # 換半徑
        self.assertEqual(mock_new.call_count, 2)

        fetch_google_places_restaurants(25.0500, 121.5645, 3, "all", 150, limit=6)  # 移動位置
        self.assertEqual(mock_new.call_count, 3)

    @patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-key", "GOOGLE_MAPS_API_KEY": ""}, clear=False)
    @patch("services.google_places_service.requests.post", return_value=FakeResponse(403, {}))
    @patch("services.google_places_service.requests.get")
    def test_legacy_result_includes_verified_website_menu_link(self, mock_get, _mock_post):
        mock_get.side_effect = [
            FakeResponse(200, {"status": "OK", "results": [legacy_place_result()]}),
            FakeResponse(200, {"status": "OK", "result": {"website": "https://bento.example/menu", "url": "https://maps.google.com/?cid=123"}}),
        ]

        restaurants = fetch_google_places_restaurants(25.0338, 121.5645, 3, "all", 150)

        self.assertEqual(restaurants[0]["official_website_url"], "https://bento.example/menu")
        self.assertEqual(restaurants[0]["google_maps_url"], "https://maps.google.com/?cid=123")
        self.assertEqual(restaurants[0]["menu_link"], {"url": "https://bento.example/menu", "source": "google_places_website"})

    @patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-key", "GOOGLE_MAPS_API_KEY": ""}, clear=False)
    @patch("services.google_places_service.requests.post", return_value=FakeResponse(403, {}))
    @patch("services.google_places_service.requests.get")
    def test_legacy_detail_failure_keeps_restaurant_without_menu_link(self, mock_get, _mock_post):
        mock_get.side_effect = [
            FakeResponse(200, {"status": "OK", "results": [legacy_place_result()]}),
            FakeResponse(200, {"status": "REQUEST_DENIED", "result": {}}),
        ]

        restaurants = fetch_google_places_restaurants(25.0338, 121.5645, 3, "all", 150)

        self.assertEqual(len(restaurants), 1)
        self.assertNotIn("menu_link", restaurants[0])
        self.assertNotIn("official_website_url", restaurants[0])


if __name__ == "__main__":
    unittest.main()


class BusinessStatusTests(unittest.TestCase):
    """推薦的店必須真的還在營業，而且不能假裝知道營業時間。"""

    def setUp(self):
        clear_search_cache()
        os.environ["GOOGLE_PLACES_API_KEY"] = "test-key"

    def _search(self, places):
        with patch("services.google_places_service.requests.post",
                   return_value=FakeResponse(200, {"places": places})):
            return fetch_google_places_restaurants(25.0338, 121.5645, 3, "all", 150, limit=10)

    @staticmethod
    def _v1_place(place_id, name, *, status="OPERATIONAL", open_now=None):
        place = {
            "id": place_id,
            "displayName": {"text": name},
            "formattedAddress": "台北",
            "location": {"latitude": 25.0338, "longitude": 121.5645},
            "types": ["restaurant"],
            "rating": 4.5,
            "userRatingCount": 100,
            "businessStatus": status,
        }
        if open_now is not None:
            place["currentOpeningHours"] = {"openNow": open_now}
        return place

    def test_permanently_closed_venues_are_dropped(self):
        results = self._search([
            self._v1_place("open-1", "還在開的店", open_now=True),
            self._v1_place("gone-1", "已歇業的店", status="CLOSED_PERMANENTLY", open_now=True),
            self._v1_place("paused-1", "暫停營業的店", status="CLOSED_TEMPORARILY"),
        ])
        names = [restaurant["name"] for restaurant in results]
        self.assertIn("還在開的店", names)
        self.assertNotIn("已歇業的店", names)
        self.assertNotIn("暫停營業的店", names)

    def test_missing_opening_hours_are_unknown_not_open(self):
        """先前這裡寫死 True，等於對每一家店謊稱營業中。"""
        results = self._search([self._v1_place("p1", "沒有營業時間資料的店")])
        self.assertIsNone(results[0]["is_open"])

    def test_a_venue_known_to_be_open_outranks_one_with_unknown_hours(self):
        results = self._search([
            self._v1_place("unknown", "營業時間未知"),
            self._v1_place("open", "確定營業中", open_now=True),
        ])
        by_name = {restaurant["name"]: restaurant for restaurant in results}
        self.assertTrue(by_name["確定營業中"]["is_open"])
        self.assertIsNone(by_name["營業時間未知"]["is_open"])
        self.assertGreater(by_name["確定營業中"]["match_score"], by_name["營業時間未知"]["match_score"])

    def test_a_venue_that_is_closed_right_now_is_still_listed_but_marked(self):
        """現在沒開不代表不能推薦，明天可能就去了；標示清楚就好。"""
        results = self._search([self._v1_place("shut", "現在休息中", open_now=False)])
        self.assertEqual(results[0]["name"], "現在休息中")
        self.assertFalse(results[0]["is_open"])
