"""Render + Supabase Auth smoke checks.

This script intentionally reads all sensitive values from environment variables.
Do not hard-code access tokens or database credentials in this file.
"""

import os
import sys
from urllib.parse import urljoin

import requests


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"[skip] Missing {name}; smoke test not run.")
        sys.exit(2)
    return value


def request_json(method: str, url: str, **kwargs):
    response = requests.request(method, url, timeout=30, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:200]}
    return response, payload


def assert_status(label: str, response: requests.Response, expected: int):
    if response.status_code != expected:
        print(f"[fail] {label}: expected {expected}, got {response.status_code}")
        print(response.text[:500])
        sys.exit(1)
    print(f"[ok] {label}: {response.status_code}")


def main():
    base_url = require_env("SMOKE_API_BASE_URL").rstrip("/") + "/"
    user_id = require_env("SMOKE_USER_ID")
    access_token = require_env("SMOKE_ACCESS_TOKEN")
    forbidden_user_id = os.environ.get("SMOKE_FORBIDDEN_USER_ID", "demo_user").strip() or "demo_user"
    if forbidden_user_id == user_id:
        forbidden_user_id = f"{user_id}_forbidden"

    health_response, health = request_json("GET", urljoin(base_url, "health"))
    assert_status("health", health_response, 200)
    if health.get("status") != "ok":
        print(f"[fail] health status expected ok, got {health.get('status')}")
        sys.exit(1)
    if health.get("postgres") is not True:
        print(f"[fail] health postgres expected true, got {health.get('postgres')}")
        sys.exit(1)
    print(f"[ok] health payload: postgres={health.get('postgres')} foods_in_tfda={health.get('foods_in_tfda')}")

    user_path = f"user/{user_id}"
    no_token_response, _ = request_json("GET", urljoin(base_url, user_path))
    assert_status("auth missing token", no_token_response, 401)

    headers = {"Authorization": f"Bearer {access_token}"}
    own_response, _ = request_json("GET", urljoin(base_url, user_path), headers=headers)
    assert_status("auth own user", own_response, 200)

    forbidden_response, _ = request_json("GET", urljoin(base_url, f"user/{forbidden_user_id}"), headers=headers)
    assert_status("auth forbidden user", forbidden_response, 403)

    print("[ok] Render + Supabase Auth smoke checks passed")


if __name__ == "__main__":
    main()
