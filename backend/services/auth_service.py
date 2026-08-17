import os

import requests


TRUTHY_VALUES = {"1", "true", "yes", "on"}


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def is_auth_required() -> bool:
    configured_value = os.environ.get("SUPABASE_AUTH_REQUIRED")
    if configured_value is not None:
        return configured_value.strip().lower() in TRUTHY_VALUES
    return os.environ.get("RENDER", "").strip().lower() in TRUTHY_VALUES


def is_supabase_auth_configured() -> bool:
    supabase_url = (os.environ.get("SUPABASE_URL") or "").strip()
    publishable_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    return bool(supabase_url and publishable_key)


def extract_bearer_token(auth_header: str | None) -> str:
    if not auth_header:
        raise AuthError("缺少 Authorization Bearer token", 401)

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization header 必須使用 Bearer token", 401)
    return token.strip()


def verify_supabase_user(auth_header: str | None) -> dict:
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    publishable_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")

    if not supabase_url or not publishable_key:
        raise AuthError("伺服器尚未設定 Supabase Auth 驗證環境變數", 500)

    token = extract_bearer_token(auth_header)
    response = requests.get(
        f"{supabase_url}/auth/v1/user",
        headers={"apikey": publishable_key, "Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if response.status_code != 200:
        raise AuthError("Supabase access token 無效或已過期", 401)

    user = response.json()
    if not user.get("id"):
        raise AuthError("Supabase Auth 回應缺少 user id", 401)
    return user
