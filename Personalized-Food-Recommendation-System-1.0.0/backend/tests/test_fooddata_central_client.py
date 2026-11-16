"""Offline bounded USDA client tests; no network or local key files."""

import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

from services.fooddata_central_client import (
    MAX_RESPONSE_BYTES, RETRIEVAL_VERSION, FoodDataCentralClient,
    FoodDataCentralClientError,
)


KEY = "test-usda-secret-never-log"
FOOD_ID = "1750340"
PAYLOAD = {"fdcId": 1750340, "description": "Apples, fuji, with skin, raw",
           "dataType": "Foundation", "foodNutrients": []}


class Response:
    def __init__(self, body=None, *, raw=None, status=200, chunks=None, headers=None, on_chunk=None):
        self.status_code = status
        self.headers = headers or {}
        self.raw_bytes = raw if raw is not None else json.dumps(body).encode("utf-8")
        self.chunks = chunks
        self.on_chunk = on_chunk
        self.closed = False

    def iter_content(self, chunk_size):
        for chunk in self.chunks if self.chunks is not None else [self.raw_bytes]:
            if self.on_chunk is not None:
                self.on_chunk()
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class FoodDataCentralClientTests(unittest.TestCase):
    def client(self, body=None, *, response=None, clock=None):
        response = response if response is not None else Response(body if body is not None else PAYLOAD)
        session = Session([response])
        client = FoodDataCentralClient(KEY, session=session, clock=clock or (lambda: 0))
        return client, session, response

    def assert_code(self, code, action):
        with self.assertRaises(FoodDataCentralClientError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(KEY, str(caught.exception))
        return caught.exception

    def test_returns_credential_free_adapter_document_and_fixed_request(self):
        client, session, response = self.client()
        document = client.get_food(FOOD_ID, deadline=25)
        self.assertEqual(document["url"], "https://api.nal.usda.gov/fdc/v1/food/1750340")
        self.assertEqual(document["payload"], PAYLOAD)
        canonical = json.dumps(PAYLOAD, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        self.assertEqual(document["content_hash"], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(document["retrieval_version"], RETRIEVAL_VERSION)
        self.assertTrue(document["retrieved_at"].endswith("+00:00"))
        url, options = session.calls[0]
        self.assertEqual(url, "https://api.nal.usda.gov/fdc/v1/food/1750340")
        self.assertEqual(options["params"], {"api_key": KEY})
        self.assertEqual(options["headers"], {"Accept": "application/json"})
        self.assertFalse(options["allow_redirects"])
        self.assertTrue(options["stream"])
        self.assertFalse(session.trust_env)
        self.assertTrue(response.closed)
        self.assertNotIn(KEY, repr(client))

    def test_environment_reads_only_backend_key_and_never_local_files(self):
        with patch.dict(os.environ, {"USDA_FDC_API_KEY": KEY, "EXPO_PUBLIC_USDA_FDC_API_KEY": "unused"}, clear=True), \
                patch.object(Path, "read_text", side_effect=AssertionError("must not read local keys")):
            client = FoodDataCentralClient.from_environment()
            self.assertEqual(client._api_key, KEY)
            client.close()
        with patch.dict(os.environ, {"EXPO_PUBLIC_USDA_FDC_API_KEY": KEY}, clear=True):
            self.assert_code("not_configured", FoodDataCentralClient.from_environment)

    def test_invalid_ids_and_deadlines_do_not_send_requests(self):
        for value in (None, True, 0, "0", -1, 1.5, "", "abc", "1/../../2", "9" * 19):
            client, session, _ = self.client()
            self.assert_code("invalid_request", lambda value=value: client.get_food(value, deadline=25))
            self.assertEqual(session.calls, [])
        for deadline in (0, -1, float("nan"), float("inf"), True, "25", 10 ** 500):
            client, session, _ = self.client()
            self.assert_code("timeout" if isinstance(deadline, (int, float)) and not isinstance(deadline, bool)
                             and deadline <= 0 else "invalid_request",
                             lambda deadline=deadline: client.get_food(FOOD_ID, deadline=deadline))
            self.assertEqual(session.calls, [])

    def test_no_redirect_retry_or_provider_error_body_is_retained(self):
        for status, code in ((301, "upstream_http_error"), (401, "authentication_failed"),
                             (403, "authentication_failed"), (404, "not_found"), (429, "rate_limited"),
                             (500, "upstream_http_error")):
            response = Response(raw=KEY.encode(), status=status)
            client, session, _ = self.client(response=response)
            error = self.assert_code(code, lambda: client.get_food(FOOD_ID, deadline=25))
            self.assertIsNone(error.__context__)
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(response.closed)

    def test_response_size_and_strict_json_are_bounded(self):
        cases = ((Response(headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}), "oversized_response"),
                 (Response(chunks=[b"x" * MAX_RESPONSE_BYTES, b"x"]), "oversized_response"),
                 (Response(raw=b'{"fdcId":1,"fdcId":2}'), "invalid_response"),
                 (Response(raw=b'{"fdcId":1} trailing'), "invalid_response"),
                 (Response(raw=b"\xff"), "invalid_response"))
        for response, expected_code in cases:
            client, _, response = self.client(response=response)
            self.assert_code(expected_code, lambda: client.get_food(FOOD_ID, deadline=25))
            self.assertTrue(response.closed)

    def test_response_food_id_must_match_the_fixed_endpoint(self):
        client, _, response = self.client(body={"fdcId": 1750341})
        self.assert_code("response_mismatch", lambda: client.get_food(FOOD_ID, deadline=25))
        self.assertTrue(response.closed)

    def test_shared_deadline_is_used_without_reset(self):
        now = [0]
        response = Response(PAYLOAD, on_chunk=lambda: now.__setitem__(0, 10))
        client, session, _ = self.client(response=response, clock=lambda: now[0])
        client.get_food(FOOD_ID, deadline=25)
        self.assertEqual(session.calls[0][1]["timeout"].total, 25)

    def test_transport_and_midstream_timeout_are_sanitized(self):
        for upstream, code in ((requests.Timeout(KEY), "timeout"), (requests.ConnectionError(KEY), "transport_error")):
            for streaming in (False, True):
                response = Response(chunks=[upstream]) if streaming else upstream
                client, session, _ = self.client(response=response)
                error = self.assert_code(code, lambda: client.get_food(FOOD_ID, deadline=25))
                self.assertIsNone(error.__context__)
                self.assertEqual(len(session.calls), 1)

    def test_close_releases_owned_session(self):
        client, session, _ = self.client()
        client.close()
        self.assertTrue(session.closed)

    def test_search_posts_bounded_identity_only_candidates_to_fixed_endpoint(self):
        foods = [{"fdcId": 171688, "description": "Apples, raw, with skin", "dataType": "SR Legacy",
                  "foodCategory": "Fruits and Fruit Juices", "brandOwner": None,
                  "foodNutrients": [{"nutrientId": 1008, "value": 52}]}]
        client, session, response = self.client(body={"foods": foods, "totalHits": 1})
        result = client.search_foods("apples raw", deadline=25, page_size=3)
        self.assertEqual(result["candidates"], [{"fdcId": "171688", "description": "Apples, raw, with skin",
                                                 "dataType": "SR Legacy", "brandOwner": None,
                                                 "foodCategory": "Fruits and Fruit Juices"}])
        self.assertNotIn("foodNutrients", repr(result))
        url, options = session.calls[0]
        self.assertEqual(url, "https://api.nal.usda.gov/fdc/v1/foods/search")
        self.assertEqual(options["params"], {"api_key": KEY})
        self.assertEqual(options["json"], {"query": "apples raw", "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)"],
                                            "pageSize": 3, "pageNumber": 1})
        self.assertFalse(options["allow_redirects"])
        self.assertTrue(response.closed)
        self.assertNotIn(KEY, repr(result))

    def test_search_request_inputs_are_bounded_and_analytical_only(self):
        invalid = (
            {"query": ""}, {"query": " apples"}, {"query": "a\nb"}, {"query": "x" * 129},
            {"query": True}, {"query": "糯米腸", "data_types": ("Branded",)},
            {"query": "糯米腸", "data_types": ("Foundation", "Foundation")},
            {"query": "糯米腸", "page_size": True}, {"query": "糯米腸", "page_size": 11},
        )
        for case in invalid:
            client, session, _ = self.client(body={"foods": []})
            kwargs = {key: value for key, value in case.items() if key != "query"}
            self.assert_code("invalid_request", lambda case=case, kwargs=kwargs: client.search_foods(
                case["query"], deadline=25, **kwargs))
            self.assertEqual(session.calls, [])
        client, session, _ = self.client(body={"foods": []})
        client.search_foods("糯米腸", deadline=25)
        self.assertEqual(session.calls[0][1]["json"]["query"], "糯米腸")

    def test_search_rejects_duplicate_ids_unrequested_types_and_oversized_result_sets(self):
        base = {"fdcId": 1, "description": "Apple, raw", "dataType": "Foundation"}
        for foods in (
            [base, {**base}],
            [{**base, "fdcId": 2, "dataType": "Branded"}],
            [{**base, "fdcId": 2, "dataType": []}],
            [{**base, "fdcId": 2, "description": ""}],
            [dict(base, fdcId=number) for number in range(11)],
        ):
            client, _, response = self.client(body={"foods": foods})
            self.assert_code("invalid_response", lambda client=client: client.search_foods("apple", deadline=25))
            self.assertTrue(response.closed)

    def test_search_never_retries_or_leaks_credentials_on_upstream_error(self):
        response = Response(raw=KEY.encode(), status=429)
        client, session, response = self.client(response=response)
        error = self.assert_code("rate_limited", lambda: client.search_foods("apple", deadline=25))
        self.assertIsNone(error.__context__)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(response.closed)

    def test_search_rejects_duplicate_json_keys_and_bad_candidate_ids(self):
        for response in (Response(raw=b'{"foods":[],"foods":[]}'),
                         Response(body={"foods": [{"fdcId": True, "description": "Apple", "dataType": "Foundation"}]}),
                         Response(body={"foods": [{"fdcId": 0, "description": "Apple", "dataType": "Foundation"}]})):
            client, _, response = self.client(response=response)
            self.assert_code("invalid_response", lambda: client.search_foods("apple", deadline=25))
            self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
