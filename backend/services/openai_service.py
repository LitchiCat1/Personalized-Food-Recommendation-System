"""ChatGPT（OpenAI API）：菜單分析先問它，失敗才換 Gemini。

只用在菜單：依店名估菜單（enrich_restaurant_with_gemini）與菜單照片辨識
（parse_menu_image_with_gemini）。ChatGPT 出錯、逾時、額度用完或說看不出來時，
才改問 Gemini。沒設 OPENAI_API_KEY 就完全不會呼叫，跟原本一樣只用 Gemini。
"""

import os


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
# 都是非推理模型：回得快，max_completion_tokens 也不會被思考過程吃掉。
# 帳號沒有前一個模型時回 404，換下一個。可用 OPENAI_MODELS 覆寫。
DEFAULT_OPENAI_MODELS = ["gpt-4.1-mini", "gpt-4o-mini"]
# 429 時這些代碼表示帳戶沒錢了（要儲值），不是暫時限流。
# 新帳號實際回的是 credit_balance_exhausted，舊文件寫的是 insufficient_quota。
OPENAI_NO_CREDIT_CODES = {"insufficient_quota", "credit_balance_exhausted"}


def get_openai_api_key() -> str | None:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    return key or None


def get_openai_models() -> list[str]:
    raw_models = [os.environ.get("OPENAI_MODELS"), os.environ.get("OPENAI_MODEL")]
    models: list[str] = []
    seen = set()
    for raw in raw_models:
        if not raw:
            continue
        for model in raw.split(","):
            normalized = model.strip()
            if normalized and normalized not in seen:
                models.append(normalized)
                seen.add(normalized)
    for model in DEFAULT_OPENAI_MODELS:
        if model not in seen:
            models.append(model)
            seen.add(model)
    return models


def openai_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def openai_chat_payload(
    model: str,
    prompt: str,
    max_tokens: int,
    image_base64: str | None = None,
    image_mime_type: str | None = None,
) -> dict:
    """要求回 JSON 物件。json_object 模式規定提示裡要出現「JSON」，兩個菜單提示都有。"""
    content = prompt
    if image_base64:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{image_mime_type or 'image/jpeg'};base64,{image_base64}"}},
        ]
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": max_tokens,
    }


def openai_response_text(body: dict) -> tuple[str, str | None]:
    """回 (模型輸出的文字, finish_reason)。"""
    choice = (body.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    return text.strip() if isinstance(text, str) else "", choice.get("finish_reason")


def openai_error(res) -> tuple[str, str]:
    """回 (錯誤代碼, 訊息)。429 要靠代碼分辨是暫時限流還是帳戶沒錢了（insufficient_quota）。"""
    try:
        error = res.json().get("error") or {}
    except (TypeError, ValueError, AttributeError):
        return "", ""
    return str(error.get("code") or error.get("type") or ""), str(error.get("message") or "")
