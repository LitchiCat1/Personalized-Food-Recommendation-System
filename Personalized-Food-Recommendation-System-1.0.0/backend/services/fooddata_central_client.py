"""Bounded server-side client for one USDA FoodData Central food record.

This client is deliberately narrower than the eventual nutrition fallback. It
fetches one fixed API resource and returns a credential-free document suitable
for :mod:`fooddata_central_adapter`. It does not search, choose food identity,
or grant source authority.
"""

from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Timeout

from services.strict_json_service import parse_strict_model_json


MAX_RESPONSE_BYTES = 512 * 1024
RETRIEVAL_VERSION = "usda-fdc-api-v1"
SEARCH_RETRIEVAL_VERSION = "usda-fdc-search-v1"
_FDC_ID = re.compile(r"[0-9]{1,18}\Z")
_ENDPOINT = "https://api.nal.usda.gov/fdc/v1/food/{}"
_SEARCH_ENDPOINT = "https://api.nal.usda.gov/fdc/v1/foods/search"
_SEARCH_DATA_TYPES = {"Foundation", "SR Legacy", "Survey (FNDDS)"}
_MAX_SEARCH_QUERY = 128
_MAX_SEARCH_PAGE_SIZE = 10


class FoodDataCentralClientError(ValueError):
    """Sanitized, stable error returned by the bounded USDA client."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise FoodDataCentralClientError(code, message)


def _canonical_payload(payload):
    try:
        text = json.dumps(payload, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise FoodDataCentralClientError("invalid_response", "USDA response is not finite JSON") from error
    return text


def _canonical_id(value):
    if isinstance(value, bool):
        valid = False
    elif isinstance(value, int):
        valid = value > 0
        value = str(value)
    elif isinstance(value, str):
        valid = bool(_FDC_ID.fullmatch(value)) and value != "0"
    else:
        valid = False
    _require(valid and _FDC_ID.fullmatch(value) is not None,
             "invalid_request", "USDA requires a numeric FoodData Central ID")
    return str(int(value))


class FoodDataCentralClient:
    """Fetch a single FDC record without redirects, retries, or proxy use."""

    def __init__(self, api_key, *, session=None, clock=time.monotonic):
        _require(isinstance(api_key, str) and 0 < len(api_key) <= 512
                 and api_key.isascii()
                 and all(33 <= ord(character) <= 126 for character in api_key),
                 "not_configured", "USDA FoodData Central requires a backend API key")
        self._api_key = api_key
        self._session = session if session is not None else requests.Session()
        if session is None:
            # Keep provider failures single-attempt; the caller owns retry or
            # fallback policy and must not multiply paid/quota-bearing calls.
            adapter = HTTPAdapter(max_retries=0)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)
        self._session.trust_env = False
        self._clock = clock

    @classmethod
    def from_environment(cls):
        """Load only the server-side key; local key files and client env are ignored."""
        return cls(os.environ.get("USDA_FDC_API_KEY", ""))

    def close(self):
        self._session.close()

    def _remaining(self, deadline):
        try:
            valid = (isinstance(deadline, (int, float)) and not isinstance(deadline, bool)
                     and math.isfinite(deadline))
        except OverflowError:
            valid = False
        _require(valid, "invalid_request", "A finite shared deadline is required")
        remaining = deadline - self._clock()
        _require(remaining > 0, "timeout", "USDA retrieval exceeded its time budget")
        return remaining

    def get_food(self, fdc_id, *, deadline):
        """Return an adapter document for one numeric FDC record.

        The API key is passed as a request parameter but never appears in the
        returned URL, document, exception text, or provider response handling.
        """
        food_id = _canonical_id(fdc_id)
        remaining = self._remaining(deadline)
        url = _ENDPOINT.format(food_id)
        response = None
        failure = None
        body = None
        try:
            response = self._session.get(
                url,
                params={"api_key": self._api_key},
                headers={"Accept": "application/json"},
                timeout=Timeout(total=remaining, connect=min(8, remaining), read=remaining),
                stream=True,
                allow_redirects=False,
            )
            self._remaining(deadline)
            status = response.status_code
            if status != 200:
                code = ({401: "authentication_failed", 403: "authentication_failed",
                         404: "not_found", 429: "rate_limited"}.get(status, "upstream_http_error"))
                failure = (code, "USDA FoodData Central retrieval could not complete")
            else:
                declared = response.headers.get("Content-Length")
                _require(declared is None or
                         (declared.isascii() and declared.isdigit() and int(declared) <= MAX_RESPONSE_BYTES),
                         "oversized_response", "USDA response exceeds the retrieval budget")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=8192):
                    self._remaining(deadline)
                    _require(isinstance(chunk, bytes), "invalid_response", "USDA response is not byte content")
                    size += len(chunk)
                    _require(size <= MAX_RESPONSE_BYTES, "oversized_response",
                             "USDA response exceeds the retrieval budget")
                    chunks.append(chunk)
                text = b"".join(chunks).decode("utf-8")
                body = parse_strict_model_json(text, max_bytes=MAX_RESPONSE_BYTES)
                _require(isinstance(body, dict), "invalid_response", "USDA response requires a JSON object")
                try:
                    response_id = _canonical_id(body.get("fdcId"))
                except FoodDataCentralClientError as error:
                    raise FoodDataCentralClientError("invalid_response", "USDA response has no valid FoodData Central ID") from error
                _require(response_id == food_id, "response_mismatch",
                         "USDA response does not match the requested FoodData Central ID")
                self._remaining(deadline)
        except FoodDataCentralClientError as error:
            failure = (error.code, str(error))
        except requests.Timeout:
            failure = ("timeout", "USDA retrieval exceeded its time budget")
        except requests.RequestException:
            failure = ("transport_error", "USDA retrieval transport failed")
        except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
            failure = ("invalid_response", "USDA response is not valid bounded JSON")
        finally:
            if response is not None:
                try:
                    response.close()
                except requests.RequestException:
                    pass
        if failure is not None:
            raise FoodDataCentralClientError(*failure)
        canonical = _canonical_payload(body)
        return {
            "url": url,
            "payload": body,
            "content_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "retrieval_version": RETRIEVAL_VERSION,
        }

    def search_foods(self, query, *, deadline, data_types=("Foundation", "SR Legacy", "Survey (FNDDS)"), page_size=10):
        """Return bounded candidate metadata only; this does not select a food or nutrition profile."""
        _require(isinstance(query, str) and 0 < len(query) <= _MAX_SEARCH_QUERY
                 and query.strip() == query
                 and not any(ord(character) < 32 or ord(character) == 127 for character in query),
                 "invalid_request", "USDA search query is invalid")
        _require(isinstance(data_types, (list, tuple)) and 0 < len(data_types) <= len(_SEARCH_DATA_TYPES)
                 and all(isinstance(value, str) and value in _SEARCH_DATA_TYPES for value in data_types)
                 and len(set(data_types)) == len(data_types),
                 "invalid_request", "USDA search data types are invalid")
        _require(type(page_size) is int and 1 <= page_size <= _MAX_SEARCH_PAGE_SIZE,
                 "invalid_request", "USDA search page size is invalid")

        remaining = self._remaining(deadline)
        response = None
        failure = None
        body = None
        try:
            response = self._session.post(
                _SEARCH_ENDPOINT,
                params={"api_key": self._api_key},
                json={"query": query, "dataType": list(data_types), "pageSize": page_size, "pageNumber": 1},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=Timeout(total=remaining, connect=min(8, remaining), read=remaining),
                stream=True,
                allow_redirects=False,
            )
            self._remaining(deadline)
            status = response.status_code
            if status != 200:
                code = ({401: "authentication_failed", 403: "authentication_failed",
                         404: "not_found", 429: "rate_limited"}.get(status, "upstream_http_error"))
                failure = (code, "USDA FoodData Central search could not complete")
            else:
                declared = response.headers.get("Content-Length")
                _require(declared is None or
                         (declared.isascii() and declared.isdigit() and int(declared) <= MAX_RESPONSE_BYTES),
                         "oversized_response", "USDA search response exceeds the retrieval budget")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=8192):
                    self._remaining(deadline)
                    _require(isinstance(chunk, bytes), "invalid_response", "USDA search response is not byte content")
                    size += len(chunk)
                    _require(size <= MAX_RESPONSE_BYTES, "oversized_response",
                             "USDA search response exceeds the retrieval budget")
                    chunks.append(chunk)
                text = b"".join(chunks).decode("utf-8")
                body = parse_strict_model_json(text, max_bytes=MAX_RESPONSE_BYTES)
                _require(isinstance(body, dict), "invalid_response", "USDA search response requires a JSON object")
                self._remaining(deadline)
        except FoodDataCentralClientError as error:
            failure = (error.code, str(error))
        except requests.Timeout:
            failure = ("timeout", "USDA search exceeded its time budget")
        except requests.RequestException:
            failure = ("transport_error", "USDA search transport failed")
        except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
            failure = ("invalid_response", "USDA search response is not valid bounded JSON")
        finally:
            if response is not None:
                try:
                    response.close()
                except requests.RequestException:
                    pass
        if failure is not None:
            raise FoodDataCentralClientError(*failure)

        foods = body.get("foods")
        _require(isinstance(foods, list) and len(foods) <= page_size,
                 "invalid_response", "USDA search results exceed the requested page")
        candidates, seen = [], set()
        for food in foods:
            _require(isinstance(food, dict), "invalid_response", "USDA search candidate must be an object")
            try:
                fdc_id = _canonical_id(food.get("fdcId"))
            except FoodDataCentralClientError as error:
                raise FoodDataCentralClientError("invalid_response", "USDA search candidate ID is invalid") from error
            description = food.get("description")
            data_type = food.get("dataType")
            _require(isinstance(description, str) and 0 < len(description) <= 300
                     and description.strip() == description
                     and not any(ord(character) < 32 or ord(character) == 127 for character in description),
                     "invalid_response", "USDA search candidate description is invalid")
            _require(isinstance(data_type, str) and data_type in _SEARCH_DATA_TYPES and data_type in data_types,
                     "invalid_response", "USDA search returned an unrequested data type")
            _require(fdc_id not in seen, "invalid_response", "USDA search returned duplicate food IDs")
            seen.add(fdc_id)
            candidate = {"fdcId": fdc_id, "description": description, "dataType": data_type}
            for field in ("brandOwner", "foodCategory"):
                value = food.get(field)
                _require(value is None or isinstance(value, str) and len(value) <= 300
                         and value.strip() == value
                         and not any(ord(character) < 32 or ord(character) == 127 for character in value),
                         "invalid_response", "USDA search candidate metadata is invalid")
                candidate[field] = value
            candidates.append(candidate)

        canonical = _canonical_payload(body)
        return {
            "candidates": candidates,
            "confirmed_no_hits": not candidates and type(body.get("totalHits")) is int
            and body["totalHits"] == 0,
            "response_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "retrieval_version": SEARCH_RETRIEVAL_VERSION,
        }

    fetch_food = get_food

