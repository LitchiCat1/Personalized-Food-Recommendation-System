"""本地端登入：Email + 密碼，帳號存在本機的 SQLite。

密碼用 bcrypt 雜湊後存在 auth_users，登入後發一組隨機 token，
資料庫裡只留它的 SHA-256。不依賴任何雲端登入服務。
"""

from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
import secrets

import bcrypt

from repositories.auth_repository import AuthRepository, EmailAlreadyRegistered


TRUTHY_VALUES = {"1", "true", "yes", "on"}
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 8
# 最常被拿來猜的那幾組。不求完整，只擋掉一猜就中的。
COMMON_PASSWORDS = {
    "12345678", "123456789", "1234567890", "87654321", "11111111", "00000000",
    "password", "password1", "passw0rd", "qwertyui", "qwerty123", "abcd1234",
    "1qaz2wsx", "iloveyou", "aaaaaaaa", "asdfghjk", "zxcvbnm1", "abc12345",
}
# bcrypt 只看前 72 bytes，5.0 版之後超過會直接丟錯，不如一開始就擋下來
MAX_PASSWORD_BYTES = 72
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 帳號不存在時也做一次比對，回應時間才不會洩漏「這個 Email 有沒有註冊」
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode()


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def is_auth_required() -> bool:
    """預設就要驗證。

    先前只有偵測到 RENDER 環境變數才驗證，所以本機或任何其他部署方式跑起來
    都是完全不設防的。安全的預設值應該是「要驗證」，要關掉就明確關掉。
    """
    configured_value = os.environ.get("AUTH_REQUIRED")
    if configured_value is not None:
        return configured_value.strip().lower() in TRUTHY_VALUES
    return True


def normalize_email(value) -> str:
    return str(value or "").strip().lower()


def validate_credentials(email: str, password) -> str:
    if not EMAIL_PATTERN.match(email):
        raise AuthError("Email 格式不對，請再確認一次。", 400)
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"密碼太短了，請至少 {MIN_PASSWORD_LENGTH} 個字元。", 400)
    if password.lower() in COMMON_PASSWORDS or len(set(password)) == 1 or password.lower() == email.split("@")[0]:
        raise AuthError("這個密碼太容易被猜到，請換一個。", 400)
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise AuthError("密碼太長了，請在 72 個英數字（約 24 個中文字）以內。", 400)
    return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def verify_password(password, password_hash: str) -> bool:
    if not isinstance(password, str) or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # 超過 72 bytes 或雜湊格式不對
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def extract_bearer_token(auth_header: str | None) -> str:
    if not auth_header:
        raise AuthError("缺少 Authorization Bearer token", 401)

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization header 必須使用 Bearer token", 401)
    return token.strip()


def _issue_session(repo: AuthRepository, user: dict) -> dict:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    repo.create_session(user["id"], hash_token(token), expires_at)
    return {
        "access_token": token,
        "expires_at": expires_at.isoformat(),
        "user": {"id": user["id"], "email": user["email"]},
    }


def sign_up(repo: AuthRepository, email, password) -> dict:
    email = normalize_email(email)
    password = validate_credentials(email, password)
    try:
        user = repo.create_user(email, hash_password(password))
    except EmailAlreadyRegistered:
        raise AuthError("這個 Email 已經註冊過了，請直接登入。", 409)
    return _issue_session(repo, user)


def sign_in(repo: AuthRepository, email, password) -> dict:
    user = repo.get_user_by_email(normalize_email(email))
    if not verify_password(password, user["password_hash"] if user else _DUMMY_HASH) or not user:
        raise AuthError("Email 或密碼不對。", 401)
    return _issue_session(repo, user)


def sign_out(repo: AuthRepository, auth_header: str | None) -> None:
    repo.delete_session(hash_token(extract_bearer_token(auth_header)))


def reset_password(repo: AuthRepository, email, new_password) -> dict:
    """給管理員在電腦上用（scripts/reset_password.py）。本地端沒有寄信功能。"""
    email = normalize_email(email)
    password = validate_credentials(email, new_password)
    user = repo.get_user_by_email(email)
    if not user:
        raise AuthError("找不到這個 Email 的帳號。", 404)
    repo.set_password(user["id"], hash_password(password))
    return {"id": user["id"], "email": user["email"]}


def verify_access_token(repo: AuthRepository, auth_header: str | None) -> dict:
    user = repo.get_session_user(hash_token(extract_bearer_token(auth_header)))
    if not user:
        raise AuthError("登入已過期，請重新登入。", 401)
    return user
