"""Offline provider fixtures; no application, credentials or database access."""

import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

from services.tavily_retrieval_service import (
    MAX_DOCUMENT_BYTES, MAX_RESPONSE_BYTES, RETRIEVAL_VERSION,
    TavilyClient, TavilyRetrievalError, validate_reviewed_url,
)


URL = "https://nutrition.example.com/food?id=1"
OTHER = "https://nutrition.example.com/other"
KEY = "test-provider-secret-never-log"


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

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class TavilyRetrievalTests(unittest.TestCase):
    def client(self, body=None, *, response=None, clock=None):
        response = response if response is not None else Response(body)
        session = Session([response])
        return TavilyClient(KEY, session=session, clock=clock or (lambda: 0)), session, response

    def search(self, client, query="rice sausage nutrition", allowed_urls=(URL,), deadline=25):
        return client.search(query, allowed_urls=allowed_urls, deadline=deadline)

    def assert_code(self, code, action):
        with self.assertRaises(TavilyRetrievalError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(KEY, str(caught.exception))
        return caught.exception

    def test_search_is_fixed_bounded_and_discards_answers_snippets_and_unreviewed_urls(self):
        client, session, response = self.client({"request_id": "req-1", "usage": {"credits": 1, "private": KEY},
                                                "answer": "invented answer", "results": [
                                                    {"url": URL, "content": "fabricated sodium zero", "raw_content": "unreviewed"},
                                                    {"url": OTHER}, {"url": URL}, {"url": "http://localhost/admin"}]})
        result = self.search(client)
        self.assertEqual(result, {"request_id": "req-1", "usage": {"credits": 1}, "urls": [URL]})
        endpoint, options = session.calls[0]
        self.assertEqual(endpoint, "https://api.tavily.com/search")
        self.assertFalse(options["allow_redirects"])
        self.assertTrue(options["stream"])
        self.assertFalse(session.trust_env)
        self.assertEqual(options["json"], {"query": "rice sausage nutrition", "search_depth": "basic", "auto_parameters": False,
                                         "topic": "general", "include_answer": False, "include_raw_content": False,
                                         "include_images": False, "include_usage": True, "max_results": 5,
                                         "include_domains": ["nutrition.example.com"], "include_domains_mode": "restrict"})
        self.assertEqual(options["headers"]["Authorization"], "Bearer " + KEY)
        self.assertTrue(response.closed)
        self.assertNotIn(KEY, repr(client))

    def test_default_session_disables_environment_proxy_and_netrc(self):
        client = TavilyClient(KEY)
        self.assertFalse(client._session.trust_env)
        client.close()

    def test_environment_loads_only_backend_key_without_reading_files(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": KEY, "EXPO_PUBLIC_TAVILY_API_KEY": "not-used"}, clear=True), \
                patch.object(Path, "read_text", side_effect=AssertionError("must not read local keys")):
            client = TavilyClient.from_environment()
            self.assertEqual(client._api_key, KEY)
            client.close()
        with patch.dict(os.environ, {"EXPO_PUBLIC_TAVILY_API_KEY": KEY}, clear=True):
            self.assert_code("not_configured", TavilyClient.from_environment)

    def test_invalid_keys_fail_without_echoing_the_supplied_key(self):
        for key in (None, "", " key ", "key\nsecret", "x" * 513):
            with self.subTest(key_type=type(key).__name__):
                self.assert_code("not_configured", lambda: TavilyClient(key))

    def test_expired_nonfinite_and_boolean_deadlines_never_send_a_request(self):
        for deadline in (0, -1, float("nan"), float("inf"), True, "25", 10 ** 500):
            client, session, _ = self.client()
            self.assert_code("timeout" if isinstance(deadline, (int, float)) and not isinstance(deadline, bool)
                             and deadline <= 0 else "invalid_request", lambda: self.search(client, deadline=deadline))
            self.assertEqual(session.calls, [])

    def test_search_input_budgets_and_source_validation_precede_network(self):
        for query, urls, code in (("", (URL,), "invalid_request"), ("x" * 513, (URL,), "invalid_request"),
                                 ("food\nname", (URL,), "invalid_request"), ("food", (), "invalid_request"),
                                 ("food", (URL, URL), "invalid_request"), ("food", (URL,) * 7, "invalid_request"),
                                 ("food", ("https://127.0.0.1/foo",), "invalid_url")):
            client, session, _ = self.client()
            self.assert_code(code, lambda: self.search(client, query, allowed_urls=urls))
            self.assertEqual(session.calls, [])

    def test_retrieval_uses_basic_full_markdown_and_owns_hash_timestamp_and_version(self):
        text = "Nutrition\n| Energy | 300 kcal |\n| Sodium | 200 mg |"
        client, session, response = self.client({"request_id": "extract-1", "usage": {"credits": 1},
                                                "results": [{"url": URL, "raw_content": text}], "failed_results": []})
        result = client.extract((URL,), deadline=25)
        self.assertEqual(result["failed_urls"], [])
        document = result["documents"][0]
        self.assertEqual(document["content_hash"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(document["raw_content"], text)
        self.assertEqual(document["retrieval_version"], RETRIEVAL_VERSION)
        self.assertTrue(document["retrieved_at"].endswith("+00:00"))
        endpoint, options = session.calls[0]
        self.assertEqual(endpoint, "https://api.tavily.com/extract")
        self.assertEqual(options["json"], {"urls": [URL], "extract_depth": "basic", "format": "markdown",
                                         "include_images": False, "include_usage": True, "timeout": 20})
        self.assertNotIn("query", options["json"])
        self.assertTrue(response.closed)

    def test_empty_explicit_failed_and_omitted_sources_all_remain_failed(self):
        for body in ({"results": [], "failed_results": [{"url": URL, "error": KEY}]},
                     {"results": []}, {"results": [{"url": URL, "raw_content": "  "}]}):
            client, _, _ = self.client(dict(body, request_id="empty-1"))
            self.assertEqual(client.extract((URL,), deadline=25),
                             {"request_id": "empty-1", "usage": None, "documents": [], "failed_urls": [URL]})

    def test_extract_rejects_extra_duplicate_or_conflicting_source_urls(self):
        for results, failures in (([{"url": OTHER, "raw_content": "text"}], []),
                                  ([{"url": URL, "raw_content": "text"}], [{"url": URL}]),
                                  ([], [{"url": "http://localhost/"}]),
                                  ([{"url": URL, "raw_content": "text"}, {"url": URL, "raw_content": "text"}], [])):
            client, _, response = self.client({"request_id": "bad-1", "results": results, "failed_results": failures})
            self.assert_code("invalid_response", lambda: client.extract((URL,), deadline=25))
            self.assertTrue(response.closed)

    def test_missing_and_nontext_source_content_are_invalid_not_successful(self):
        for entry in ({"url": URL}, {"url": URL, "raw_content": None}, {"url": URL, "raw_content": 0},
                      {"url": URL, "raw_content": "\ud800"}):
            client, _, _ = self.client({"request_id": "bad-1", "results": [entry]})
            self.assert_code("invalid_response", lambda: client.extract((URL,), deadline=25))

    def test_document_utf8_bytes_are_bounded_without_truncation(self):
        for text in ("x" * (MAX_DOCUMENT_BYTES + 1), "\u71df" * (MAX_DOCUMENT_BYTES // 3 + 1)):
            client, _, _ = self.client({"request_id": "large-1", "results": [{"url": URL, "raw_content": text}]})
            self.assert_code("oversized_response", lambda: client.extract((URL,), deadline=25))

    def test_combined_document_size_limit(self):
        urls = tuple("https://nutrition.example.com/" + str(index) for index in range(4))
        results = [{"url": url, "raw_content": "x" * (50 * 1024)} for url in urls]
        client, _, _ = self.client({"request_id": "large-1", "results": results})
        self.assert_code("oversized_response", lambda: client.extract(urls, deadline=25))

    def test_streaming_body_bound_is_enforced_even_without_content_length(self):
        response = Response(chunks=[b"x" * MAX_RESPONSE_BYTES, b"x"])
        client, _, _ = self.client(response=response)
        self.assert_code("oversized_response", lambda: self.search(client))
        self.assertTrue(response.closed)

    def test_oversized_declared_content_fails_before_read(self):
        response = Response(headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)},
                            on_chunk=lambda: self.fail("oversized body must not be consumed"))
        client, _, _ = self.client(response=response)
        self.assert_code("oversized_response", lambda: self.search(client))
        self.assertTrue(response.closed)

    def test_duplicate_nonfinite_fenced_trailing_and_invalid_utf8_json_fail_closed(self):
        for raw in (b'{"request_id":"a","request_id":"b","results":[]}',
                    b'{"request_id":"a","results":[],"usage":{"credits":NaN}}',
                    b'```json\n{"request_id":"a","results":[]}\n```',
                    b'{"request_id":"a","results":[]} trailing', b'\xff'):
            client, _, response = self.client(response=Response(raw=raw))
            self.assert_code("invalid_response", lambda: self.search(client))
            self.assertTrue(response.closed)

    def test_response_metadata_and_result_shape_are_strict(self):
        for body in ({"results": []}, {"request_id": "x\n", "results": []},
                     {"request_id": "x", "usage": {"credits": True}, "results": []},
                     {"request_id": "x", "usage": {"credits": -1}, "results": []},
                     {"request_id": "x", "usage": {"credits": 10 ** 500}, "results": []},
                     {"request_id": "x", "usage": {}, "results": []},
                     {"request_id": "x", "results": {}}, {"request_id": "x", "results": [None]},
                     {"request_id": "x", "results": [{"url": URL}] * 6}):
            client, _, _ = self.client(body)
            self.assert_code("invalid_response", lambda: self.search(client))

    def test_no_provider_redirect_or_http_error_retries_and_no_error_body_retention(self):
        for status, code in ((301, "upstream_http_error"), (401, "authentication_failed"), (403, "authentication_failed"),
                             (429, "rate_limited"), (432, "budget_exceeded"), (433, "budget_exceeded"),
                             (500, "upstream_http_error")):
            response = Response(raw=KEY.encode(), status=status)
            client, session, _ = self.client(response=response)
            error = self.assert_code(code, lambda: self.search(client))
            self.assertIsNone(error.__context__)
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(response.closed)

    def test_network_errors_and_midstream_timeouts_are_sanitized_without_chaining(self):
        for upstream, code in ((requests.Timeout(KEY), "timeout"), (requests.ConnectionError(KEY), "transport_error")):
            for streaming in (False, True):
                response = Response(chunks=[upstream]) if streaming else upstream
                client, session, _ = self.client(response=response)
                error = self.assert_code(code, lambda: self.search(client))
                self.assertIsNone(error.__context__)
                self.assertEqual(len(session.calls), 1)

    def test_shared_deadline_expiring_during_download_discards_results(self):
        now = [0]
        response = Response({"request_id": "late-1", "results": [{"url": URL}]}, on_chunk=lambda: now.__setitem__(0, 26))
        client, _, _ = self.client(response=response, clock=lambda: now[0])
        self.assert_code("timeout", lambda: self.search(client))
        self.assertTrue(response.closed)

    def test_search_and_extract_share_remaining_budget_without_reset(self):
        now = [0]
        search_response = Response({"request_id": "search-1", "results": [{"url": URL}]}, on_chunk=lambda: now.__setitem__(0, 10))
        extract_response = Response({"request_id": "extract-1", "results": []})
        session = Session([search_response, extract_response])
        client = TavilyClient(KEY, session=session, clock=lambda: now[0])
        self.search(client)
        client.extract((URL,), deadline=25)
        self.assertEqual(session.calls[0][1]["timeout"].total, 25)
        self.assertEqual(session.calls[1][1]["timeout"].total, 15)
        self.assertEqual(session.calls[1][1]["json"]["timeout"], 15)

    def test_close_releases_owned_session(self):
        client, session, _ = self.client()
        client.close()
        self.assertTrue(session.closed)


class ReviewedUrlTests(unittest.TestCase):
    def test_canonical_https_paths_queries_and_default_port_are_preserved(self):
        self.assertEqual(validate_reviewed_url(URL), URL)
        self.assertEqual(validate_reviewed_url("https://nutrition.example.com:443/food?id=1"), URL)
        self.assertEqual(validate_reviewed_url("https://nutrition.example.com/file%20name.pdf"),
                         "https://nutrition.example.com/file%20name.pdf")

    def test_unreviewable_authorities_schemes_control_characters_and_paths_are_rejected(self):
        urls = (None, "", "http://nutrition.example.com/", "HTTPS://nutrition.example.com/", "//nutrition.example.com/",
                "https://Nutrition.example.com/", "https://nutrition.example.com:444/", "https://user:pass@nutrition.example.com/",
                "https://nutrition.example.com/#section", "https://nutrition.example.com/#", "https://nutrition.example.com./",
                "https://nutrition.example.com\\@localhost/", "https://nutrition.example.com/a\nb", "https://nutrition.example.com/a%0Ab",
                "https://nutrition.example.com/a%5Cb", "https://nutrition.example.com/a%ZZ", "https://nutrition.example.com/../secret",
                "https://nutrition.example.com/%2e%2e/secret", "https://127.0.0.1/", "https://[::1]/", "https://2130706433/",
                "https://localhost/", "https://printer.local/", "https://server.internal/", "https://router.home.arpa/",
                "https://source.test/", "https://xn--bcher-kva.example/", "https://\u98df\u7269.example/", "https://bad..example.com/")
        for url in urls:
            with self.subTest(url=url), self.assertRaises(TavilyRetrievalError) as caught:
                validate_reviewed_url(url)
            self.assertEqual(caught.exception.code, "invalid_url")


if __name__ == "__main__":
    unittest.main()
