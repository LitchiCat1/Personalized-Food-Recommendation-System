import os
import unittest
from unittest.mock import patch

from services.google_places_service import _fetch_new_places_api, fetch_google_places_restaurants


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


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
    @patch("services.google_places_service.requests.get")
    def test_legacy_result_includes_verified_website_menu_link(self, mock_get):
        mock_get.side_effect = [
            FakeResponse(200, {"status": "OK", "results": [legacy_place_result()]}),
            FakeResponse(200, {"status": "OK", "result": {"website": "https://bento.example/menu", "url": "https://maps.google.com/?cid=123"}}),
        ]

        restaurants = fetch_google_places_restaurants(25.0338, 121.5645, 3, "all", 150)

        self.assertEqual(restaurants[0]["official_website_url"], "https://bento.example/menu")
        self.assertEqual(restaurants[0]["google_maps_url"], "https://maps.google.com/?cid=123")
        self.assertEqual(restaurants[0]["menu_link"], {"url": "https://bento.example/menu", "source": "google_places_website"})

    @patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-key", "GOOGLE_MAPS_API_KEY": ""}, clear=False)
    @patch("services.google_places_service.requests.get")
    def test_legacy_detail_failure_keeps_restaurant_without_menu_link(self, mock_get):
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
