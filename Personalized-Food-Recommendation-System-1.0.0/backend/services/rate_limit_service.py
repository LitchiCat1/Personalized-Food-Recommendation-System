"""呼叫外部付費 API 的路由要有速率限制。

Gemini 與 Google Places 都是按次計費，而後端沒有任何節流：一個迴圈就能
把額度打光。這裡用最小的實作——單一程序內的記憶體計數，因為 Render 免費
方案就是單一實例。要跑多實例時得換成 Redis。
"""

import os
import threading
import time

# (窗口秒數, 窗口內允許次數)
DEFAULT_WINDOW_SECONDS = 60
DEFAULT_MAX_CALLS = 20


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"請求太頻繁，請於 {retry_after} 秒後再試")
        self.retry_after = retry_after
        self.status_code = 429


class SlidingWindowLimiter:
    def __init__(self, max_calls: int = DEFAULT_MAX_CALLS, window_seconds: int = DEFAULT_WINDOW_SECONDS):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """記一次呼叫；超過上限就丟 RateLimitExceeded。"""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = [stamp for stamp in self._hits.get(key, []) if stamp > cutoff]
            if len(hits) >= self.max_calls:
                retry_after = max(1, int(hits[0] + self.window_seconds - now) + 1)
                self._hits[key] = hits
                raise RateLimitExceeded(retry_after)
            hits.append(now)
            self._hits[key] = hits

            # 順手清掉沒人用的 key，免得記憶體隨 IP 數量無限成長
            if len(self._hits) > 2048:
                self._hits = {
                    existing_key: stamps
                    for existing_key, stamps in self._hits.items()
                    if stamps and stamps[-1] > cutoff
                }

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def _env_int(name: str, fallback: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "")))
    except (TypeError, ValueError):
        return fallback


def build_limiter(max_calls_env: str, default_max_calls: int) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        max_calls=_env_int(max_calls_env, default_max_calls),
        window_seconds=_env_int("RATE_LIMIT_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS),
    )
