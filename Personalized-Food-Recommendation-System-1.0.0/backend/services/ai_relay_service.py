"""OpenAI-compatible relay configuration and one shared, exclusive key pool."""

import os
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import requests

from services.openai_service import openai_chat_payload, openai_headers, openai_response_text


DEFAULT_KEYS_FILE = Path(__file__).resolve().parents[2] / "key.txt"
RETRYABLE_STATUSES = {401, 403, 404, 408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RelayConfig:
    base_url: str
    model: str
    keys: tuple[str, ...] = field(repr=False)

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"


def _config(base_url: str, model: str, keys) -> RelayConfig:
    base_url = base_url.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("AI relay Base URL must be an HTTP(S) API base without credentials or query parameters")
    unique_keys = tuple(dict.fromkeys(key.strip() for key in keys if key.strip()))
    if not model.strip() or not unique_keys:
        raise ValueError("AI relay requires a model and at least one API key")
    return RelayConfig(base_url, model.strip(), unique_keys)


@lru_cache(maxsize=4)
def _read_keys_file(path: str, modified_ns: int, size: int) -> RelayConfig:
    base_url = model = ""
    keys = []
    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("sk-"):
            keys.append(line)
            continue
        match = re.fullmatch(r'(Base\s*URL|\u6307\u5b9a\u6a21\u578bID)\s*[:=]?\s*["\u201c](.+?)["\u201d]', line, re.IGNORECASE)
        if match:
            if match[1].lower().startswith("base"):
                base_url = match[2]
            else:
                model = match[2]
    return _config(base_url, model, keys)


def get_relay_config() -> RelayConfig | None:
    """Explicit relay environment overrides the local file; legacy keys never mix in."""
    settings = [os.environ.get(name, "").strip() for name in ("AI_BASE_URL", "AI_MODEL", "AI_API_KEYS")]
    if any(settings):
        if not all(settings):
            raise ValueError("Set AI_BASE_URL, AI_MODEL and AI_API_KEYS together")
        return _config(settings[0], settings[1], settings[2].split(","))
    explicit_path = os.environ.get("AI_RELAY_KEYS_FILE", "").strip()
    if not explicit_path and os.environ.get("NUTRILENS_SKIP_LOCAL_ENV"):
        return None
    path = Path(explicit_path).expanduser() if explicit_path else DEFAULT_KEYS_FILE
    if not path.is_absolute():
        path = DEFAULT_KEYS_FILE.parent / path
    if not path.is_file():
        if explicit_path:
            raise ValueError("AI_RELAY_KEYS_FILE does not point to a readable file")
        return None
    stat = path.stat()
    return _read_keys_file(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def _http_error(status: int) -> requests.HTTPError:
    # Do not retain the upstream request (Authorization) or its untrusted error body.
    response = requests.Response()
    response.status_code = status
    response._content = f"AI relay returned HTTP {status}".encode("ascii")
    return requests.HTTPError(response.text, response=response)


class RelayKeyPool:
    def __init__(self, keys: tuple[str, ...]):
        self.keys = keys
        self._condition = threading.Condition()
        self._busy: set[str] = set()
        self._cooldown: dict[str, float] = {}
        self._next = 0

    def acquire(self, excluded: set[str], deadline: float) -> str:
        with self._condition:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise requests.Timeout("AI relay request budget exhausted while waiting for a key")
                eligible = False
                for offset in range(len(self.keys)):
                    index = (self._next + offset) % len(self.keys)
                    key = self.keys[index]
                    if key in excluded or self._cooldown.get(key, 0) > now:
                        continue
                    eligible = True
                    if key not in self._busy:
                        self._busy.add(key)
                        self._next = (index + 1) % len(self.keys)
                        return key
                if not eligible:
                    raise _http_error(429)
                self._condition.wait(timeout=deadline - now)

    def release(self, key: str, cooldown: float = 0) -> None:
        with self._condition:
            self._busy.discard(key)
            if cooldown:
                self._cooldown[key] = time.monotonic() + cooldown
            self._condition.notify_all()


_pool_lock = threading.Lock()


@lru_cache(maxsize=8)
def _cached_pool(base_url: str, keys: tuple[str, ...]) -> RelayKeyPool:
    return RelayKeyPool(keys)


def _key_pool(base_url: str, keys: tuple[str, ...]) -> RelayKeyPool:
    # lru_cache alone permits duplicate construction on simultaneous first use.
    with _pool_lock:
        return _cached_pool(base_url, keys)


def _retry_after(response) -> float:
    try:
        return max(1, min(float(response.headers.get("Retry-After", "60")), 300))
    except (TypeError, ValueError):
        return 60


def relay_chat(
    prompt: str,
    max_tokens: int = 4096,
    image_base64: str | None = None,
    image_mime_type: str | None = None,
    timeout: float = 60,
    deadline: float | None = None,
) -> tuple[str, str | None]:
    config = get_relay_config()
    if config is None:
        raise ValueError("AI relay is not configured")
    deadline = min(deadline, time.monotonic() + timeout) if deadline is not None else time.monotonic() + timeout
    pool = _key_pool(config.base_url, config.keys)
    attempted: set[str] = set()
    last_error = None
    payload = openai_chat_payload(config.model, prompt, max_tokens, image_base64, image_mime_type)
    while len(attempted) < len(config.keys):
        try:
            key = pool.acquire(attempted, deadline)
        except requests.HTTPError:
            if last_error is not None:
                raise last_error from None
            raise
        attempted.add(key)
        cooldown = 0
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout("AI relay request budget exhausted")
            response = requests.post(
                config.chat_url,
                headers=openai_headers(key),
                json=payload,
                timeout=remaining,
                allow_redirects=False,
            )
            if response.status_code == 200:
                try:
                    text, finish = openai_response_text(response.json())
                except (ValueError, TypeError, AttributeError, IndexError):
                    raise ValueError("AI relay returned an invalid completion") from None
                if not text:
                    raise ValueError("AI relay returned an empty completion")
                return text, finish
            last_error = _http_error(response.status_code)
            if response.status_code not in RETRYABLE_STATUSES:
                raise last_error
            cooldown = (_retry_after(response) if response.status_code == 429 else
                        300 if response.status_code in {401, 403, 404} else 2)
        except requests.Timeout:
            cooldown = 2
            last_error = requests.Timeout("AI relay timed out")
        except requests.ConnectionError:
            cooldown = 2
            last_error = requests.ConnectionError("AI relay connection failed")
        finally:
            pool.release(key, cooldown)
    raise last_error from None


def relay_diagnostics(timeout: float = 10, generate: bool = False) -> dict:
    config = get_relay_config()
    report = {
        "provider": "openai-compatible-relay",
        "configured_models": [config.model],
        "key_count": len(config.keys),
        "rotation": "exclusive-round-robin",
    }
    if generate:
        try:
            relay_chat('Return JSON: {"ok":true}', max_tokens=128, timeout=timeout)
            report["generate_status"] = "ok"
        except (requests.RequestException, ValueError):
            report["generate_status"] = "unavailable"
    return report
