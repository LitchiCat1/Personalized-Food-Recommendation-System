"""Bounded Tavily discovery/retrieval for server-reviewed source URLs only.

Search snippets are deliberately discarded. Retrieved text remains untrusted
input for a source adapter; this client cannot grant reuse or food equivalence.
Source URLs are sent only to Tavily's fixed API, never fetched directly here.
"""

from datetime import datetime, timezone
import hashlib
import ipaddress
import math
import os
import re
import time
from urllib.parse import unquote, urlsplit, urlunsplit

import requests
from urllib3.util import Timeout

from services.strict_json_service import parse_strict_model_json


MAX_RESPONSE_BYTES = 512 * 1024
MAX_DOCUMENT_BYTES = 64 * 1024
MAX_DOCUMENT_TOTAL_BYTES = 192 * 1024
MAX_URLS = 6
RETRIEVAL_VERSION = "tavily-extract-basic-markdown-v1"
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa", ".test", ".invalid")


class TavilyRetrievalError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise TavilyRetrievalError(code, message)


def validate_reviewed_url(url):
    """Validate URL syntax, not DNS or source rights; normalize default port.

    A future direct fetcher must separately pin resolved public addresses and
    validate every redirect. This function intentionally performs no DNS I/O.
    """
    _require(isinstance(url, str) and 0 < len(url) <= 2048,
             "invalid_url", "A reviewed source requires a bounded HTTPS URL")
    _require(not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url)
             and "\\" not in url and "#" not in url and _BAD_ESCAPE.search(url) is None,
             "invalid_url", "A reviewed URL contains unsupported syntax")
    decoded = unquote(url)
    _require("\\" not in decoded and not any(ord(character) < 32 or ord(character) == 127 for character in decoded),
             "invalid_url", "A reviewed URL contains escaped control characters")
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
        valid = (parsed.scheme == "https" and url.startswith("https://") and bool(host)
                 and parsed.username is None and parsed.password is None and port in (None, 443))
    except ValueError:
        valid = False
    _require(valid, "invalid_url", "A reviewed source requires HTTPS without credentials")
    _require(host == host.lower() and parsed.netloc in (host, host + ":443") and len(host) <= 253
             and host.isascii() and "." in host and not host.endswith(_PRIVATE_SUFFIXES)
             and all(_HOST_LABEL.fullmatch(label) is not None and not label.startswith("xn--") for label in host.split("."))
             and re.fullmatch(r"[a-z]{2,63}", host.rsplit(".", 1)[-1]) is not None,
             "invalid_url", "A reviewed source requires a canonical public DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise TavilyRetrievalError("invalid_url", "IP address source URLs are unsupported")
    _require(not any(segment in (".", "..") for segment in unquote(parsed.path).split("/")),
             "invalid_url", "A reviewed source path cannot contain dot segments")
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


def _urls(values):
    _require(isinstance(values, (tuple, list)) and 0 < len(values) <= MAX_URLS,
             "invalid_request", "Source URLs must be a bounded nonempty list")
    result = tuple(validate_reviewed_url(value) for value in values)
    _require(len(set(result)) == len(result), "invalid_request", "Source URLs must be unique")
    return result


def _metadata(body):
    request_id = body.get("request_id")
    _require(isinstance(request_id, str) and 0 < len(request_id) <= 256
             and request_id.isascii() and all(33 <= ord(character) <= 126 for character in request_id),
             "invalid_response", "Tavily response is missing its request identifier")
    usage = body.get("usage")
    if usage is not None:
        _require(isinstance(usage, dict), "invalid_response", "Tavily usage metadata is invalid")
        credits = usage.get("credits")
        _require(isinstance(credits, (int, float)) and not isinstance(credits, bool)
                 and 0 <= credits <= 1000000 and math.isfinite(credits),
                 "invalid_response", "Tavily usage credits are invalid")
        usage = {"credits": credits}
    return {"request_id": request_id, "usage": usage}


class TavilyClient:
    def __init__(self, api_key, *, session=None, clock=time.monotonic):
        _require(isinstance(api_key, str) and 0 < len(api_key) <= 512
                 and api_key.isascii() and all(33 <= ord(character) <= 126 for character in api_key),
                 "not_configured", "Tavily requires a backend API key")
        self._api_key = api_key
        self._session = session if session is not None else requests.Session()
        self._session.trust_env = False
        self._clock = clock

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("TAVILY_API_KEY", ""))

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
        _require(remaining > 0, "timeout", "Tavily retrieval exceeded its time budget")
        return remaining

    def _post(self, endpoint, payload, deadline):
        remaining = self._remaining(deadline)
        response = None
        failure = None
        body = None
        try:
            response = self._session.post(
                "https://api.tavily.com/" + endpoint,
                headers={"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json"},
                json=payload, timeout=Timeout(total=remaining, connect=min(8, remaining), read=remaining),
                stream=True, allow_redirects=False,
            )
            self._remaining(deadline)
            status = response.status_code
            if status != 200:
                code = ({401: "authentication_failed", 403: "authentication_failed", 429: "rate_limited",
                         432: "budget_exceeded", 433: "budget_exceeded"}.get(status, "upstream_http_error"))
                failure = (code, "Tavily retrieval could not complete")
            else:
                declared = response.headers.get("Content-Length")
                _require(declared is None or (declared.isascii() and declared.isdigit() and int(declared) <= MAX_RESPONSE_BYTES),
                         "oversized_response", "Tavily response exceeds the retrieval budget")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=8192):
                    self._remaining(deadline)
                    _require(isinstance(chunk, bytes), "invalid_response", "Tavily response is not byte content")
                    size += len(chunk)
                    _require(size <= MAX_RESPONSE_BYTES, "oversized_response", "Tavily response exceeds the retrieval budget")
                    chunks.append(chunk)
                text = b"".join(chunks).decode("utf-8")
                _require(text.lstrip().startswith("{"), "invalid_response", "Tavily response requires a JSON object")
                body = parse_strict_model_json(text, max_bytes=MAX_RESPONSE_BYTES)
                self._remaining(deadline)
        except TavilyRetrievalError as error:
            failure = (error.code, str(error))
        except requests.Timeout:
            failure = ("timeout", "Tavily retrieval exceeded its time budget")
        except requests.RequestException:
            failure = ("transport_error", "Tavily retrieval transport failed")
        except (ValueError, TypeError, OverflowError, RecursionError):
            failure = ("invalid_response", "Tavily response is not valid bounded JSON")
        finally:
            if response is not None:
                try:
                    response.close()
                except requests.RequestException:
                    pass
        # Raising outside except prevents retaining a credential-bearing request
        # or the provider's untrusted error body in the exception chain.
        if failure is not None:
            raise TavilyRetrievalError(*failure)
        return body

    def search(self, query, *, allowed_urls, deadline):
        _require(isinstance(query, str) and 0 < len(query.strip()) <= 512
                 and not any(ord(character) < 32 or ord(character) == 127 for character in query),
                 "invalid_request", "A search requires a bounded food identity query")
        reviewed = _urls(allowed_urls)
        domains = list(dict.fromkeys(urlsplit(url).hostname for url in reviewed))
        payload = {
            "query": query.strip(), "search_depth": "basic", "auto_parameters": False,
            "topic": "general", "include_answer": False, "include_raw_content": False,
            "include_images": False, "include_usage": True, "max_results": 5,
            "include_domains": domains, "include_domains_mode": "restrict",
        }
        body = self._post("search", payload, deadline)
        metadata = _metadata(body)
        results = body.get("results")
        _require(isinstance(results, list) and len(results) <= 5,
                 "invalid_response", "Tavily search results exceed the bounded result set")
        urls = []
        for result in results:
            _require(isinstance(result, dict), "invalid_response", "Tavily search result is invalid")
            try:
                url = validate_reviewed_url(result.get("url"))
            except TavilyRetrievalError:
                continue
            if url in reviewed and url not in urls:
                urls.append(url)
        self._remaining(deadline)
        return dict(metadata, urls=urls)

    def extract(self, urls, *, deadline):
        reviewed = _urls(urls)
        payload = {"urls": list(reviewed), "extract_depth": "basic", "format": "markdown",
                   "include_images": False, "include_usage": True,
                   "timeout": min(20, self._remaining(deadline))}
        body = self._post("extract", payload, deadline)
        metadata = _metadata(body)
        results, failures = body.get("results"), body.get("failed_results", [])
        _require(isinstance(results, list) and len(results) <= len(reviewed)
                 and isinstance(failures, list) and len(failures) <= len(reviewed),
                 "invalid_response", "Tavily extract result sets are invalid")
        documents, seen, total_bytes = [], set(), 0
        for entry, succeeded in [(entry, True) for entry in results] + [(entry, False) for entry in failures]:
            _require(isinstance(entry, dict), "invalid_response", "Tavily extract result is invalid")
            try:
                url = validate_reviewed_url(entry.get("url"))
            except TavilyRetrievalError:
                raise TavilyRetrievalError("invalid_response", "Tavily extract returned an invalid URL") from None
            _require(url in reviewed and url not in seen,
                     "invalid_response", "Tavily extract returned an unrequested or duplicate URL")
            seen.add(url)
            if not succeeded:
                continue
            raw = entry.get("raw_content")
            _require(isinstance(raw, str), "invalid_response", "Tavily source text is invalid")
            encoded = None
            try:
                encoded = raw.encode("utf-8")
            except UnicodeError:
                pass
            _require(encoded is not None, "invalid_response", "Tavily source text contains invalid Unicode")
            size = len(encoded)
            total_bytes += size
            _require(size <= MAX_DOCUMENT_BYTES and total_bytes <= MAX_DOCUMENT_TOTAL_BYTES,
                     "oversized_response", "Tavily source text exceeds the document budget")
            if raw.strip():
                documents.append({"url": url, "raw_content": raw,
                                  "content_hash": hashlib.sha256(encoded).hexdigest(),
                                  "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                  "retrieval_version": RETRIEVAL_VERSION})
        self._remaining(deadline)
        successful = {document["url"] for document in documents}
        return dict(metadata, documents=documents,
                    failed_urls=[url for url in reviewed if url not in successful])
