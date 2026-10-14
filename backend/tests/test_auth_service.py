import os
import unittest
from unittest.mock import patch

from repositories.auth_repository import AuthRepository
from repositories.sqlite_db import SqliteDatabase
from services.auth_service import AuthError, is_auth_required, reset_password, sign_in, sign_out, sign_up, verify_access_token
from test_api_routes import ApiTestBase


class AuthServiceConfigurationTests(unittest.TestCase):
    def test_auth_is_required_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(is_auth_required())

    def test_explicit_auth_flag_turns_auth_off(self):
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false"}, clear=True):
            self.assertFalse(is_auth_required())


class LocalAuthTests(unittest.TestCase):
    def setUp(self):
        self.repo = AuthRepository()

    def bearer(self, session):
        return f"Bearer {session['access_token']}"

    def test_sign_up_then_sign_in_with_the_same_password(self):
        created = sign_up(self.repo, "Someone@Example.com", "secret-pass")
        signed_in = sign_in(self.repo, "someone@example.com", "secret-pass")

        self.assertEqual(created["user"]["id"], signed_in["user"]["id"])
        self.assertEqual(signed_in["user"]["email"], "someone@example.com")
        self.assertEqual(verify_access_token(self.repo, self.bearer(signed_in))["id"], created["user"]["id"])

    def test_wrong_password_and_unknown_email_get_the_same_answer(self):
        sign_up(self.repo, "a@example.com", "secret-pass")
        for email, password in (("a@example.com", "wrong-pw"), ("nobody@example.com", "secret-pass")):
            with self.assertRaises(AuthError) as caught:
                sign_in(self.repo, email, password)
            self.assertEqual(caught.exception.status_code, 401)
            self.assertEqual(str(caught.exception), "暱稱或密碼不對。")

    def test_duplicate_email_is_rejected(self):
        sign_up(self.repo, "a@example.com", "secret-pass")
        with self.assertRaises(AuthError) as caught:
            sign_up(self.repo, "A@example.com", "another1")
        self.assertEqual(caught.exception.status_code, 409)

    def test_any_nickname_and_any_password_can_sign_up(self):
        sign_up(self.repo, "  小明 ", "1")
        self.assertTrue(sign_in(self.repo, "小明", "1")["access_token"])
        sign_up(self.repo, "Amy", "amy")
        self.assertEqual(sign_in(self.repo, "amy", "amy")["user"]["email"], "amy")

    def test_empty_or_too_long_values_are_rejected(self):
        for nickname, password in (("", "pw"), ("   ", "pw"), ("小明", ""), ("x" * 31, "pw"), ("小明", "x" * 73)):
            with self.assertRaises(AuthError) as caught:
                sign_up(self.repo, nickname, password)
            self.assertEqual(caught.exception.status_code, 400, (nickname, password))

    def test_taken_nickname_is_rejected(self):
        sign_up(self.repo, "小明", "1")
        with self.assertRaises(AuthError) as caught:
            sign_up(self.repo, "小明", "2")
        self.assertEqual(caught.exception.status_code, 409)

    def test_sign_out_invalidates_only_that_token(self):
        sign_up(self.repo, "a@example.com", "secret-pass")
        phone = sign_in(self.repo, "a@example.com", "secret-pass")
        laptop = sign_in(self.repo, "a@example.com", "secret-pass")

        sign_out(self.repo, self.bearer(phone))

        with self.assertRaises(AuthError):
            verify_access_token(self.repo, self.bearer(phone))
        self.assertEqual(verify_access_token(self.repo, self.bearer(laptop))["email"], "a@example.com")

    def test_reset_password_logs_out_every_device(self):
        sign_up(self.repo, "a@example.com", "secret-pass")
        old_session = sign_in(self.repo, "a@example.com", "secret-pass")

        reset_password(self.repo, "a@example.com", "brand-new")

        with self.assertRaises(AuthError):
            verify_access_token(self.repo, self.bearer(old_session))
        with self.assertRaises(AuthError):
            sign_in(self.repo, "a@example.com", "secret-pass")
        self.assertTrue(sign_in(self.repo, "a@example.com", "brand-new")["access_token"])

    def test_missing_or_malformed_header_is_rejected(self):
        for header in (None, "", "Token abc", "Bearer "):
            with self.assertRaises(AuthError) as caught:
                verify_access_token(self.repo, header)
            self.assertEqual(caught.exception.status_code, 401)



class SqliteLocalAuthTests(LocalAuthTests):
    """同一組登入測試，帳號改存在 SQLite。"""

    def setUp(self):
        self.repo = AuthRepository(SqliteDatabase(":memory:"))


class AuthRouteTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.app_module.auth_repo.mem_users.clear()
        self.app_module.auth_repo.mem_sessions.clear()
        self.app_module._auth_limiter.reset()

    def signup(self, email="route@example.com", password="secret-pass"):
        return self.client.post("/auth/signup", json={"email": email, "password": password})

    def test_signed_up_token_reaches_the_users_own_routes(self):
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        session = response.get_json()
        headers = {"Authorization": f"Bearer {session['access_token']}"}

        me = self.client.get("/auth/user", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["user"]["email"], "route@example.com")

        own = self.client.get(f"/records/{session['user']['id']}", headers=headers)
        self.assertEqual(own.status_code, 200)
        other = self.client.get("/records/user-a", headers=headers)
        self.assertEqual(other.status_code, 403)

    def test_login_logout_round_trip(self):
        self.signup()
        login = self.client.post("/auth/login", json={"email": "ROUTE@example.com", "password": "secret-pass"})
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": f"Bearer {login.get_json()['access_token']}"}

        self.assertEqual(self.client.post("/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/auth/user", headers=headers).status_code, 401)

    def test_wrong_password_and_duplicate_signup_return_readable_errors(self):
        self.signup()
        wrong = self.client.post("/auth/login", json={"email": "route@example.com", "password": "nope-nope"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.get_json()["error"], "暱稱或密碼不對。")

        duplicate = self.signup()
        self.assertEqual(duplicate.status_code, 409)

    def test_login_attempts_are_rate_limited(self):
        self.signup()
        statuses = [
            self.client.post("/auth/login", json={"email": "route@example.com", "password": "guess-000"}).status_code
            for _ in range(12)
        ]
        self.assertIn(429, statuses)


if __name__ == "__main__":
    unittest.main()
