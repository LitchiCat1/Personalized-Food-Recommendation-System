"""從其他裝置或 tunnel 連進來時的防護。

Flask 測試用戶端預設的來源是 127.0.0.1，等於「這台電腦」；要模擬別台裝置，
就把 REMOTE_ADDR 換成區網位址，或帶上 cloudflared 會加的標頭。
"""

import os
from unittest.mock import patch

from test_api_routes import ApiTestBase

LAN = {"REMOTE_ADDR": "192.168.0.50"}
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}
TUNNEL_HEADERS = {"Cf-Connecting-Ip": "203.0.113.9"}
FUNNEL_URL = "https://my-pc.tail1234.ts.net/"


class RequestOriginTests(ApiTestBase):
    def test_client_ip_ignores_forwarding_headers_from_other_machines(self):
        with self.app_module.app.test_request_context(
            "/", environ_base=LAN, headers={"X-Forwarded-For": "1.2.3.4", "Cf-Connecting-Ip": "5.6.7.8"}
        ):
            self.assertEqual(self.app_module.client_ip(), "192.168.0.50")
            self.assertFalse(self.app_module.is_local_request())

    def test_tunnel_traffic_uses_the_address_cloudflare_reports(self):
        with self.app_module.app.test_request_context("/", environ_base=LOCAL, headers=TUNNEL_HEADERS):
            self.assertEqual(self.app_module.client_ip(), "203.0.113.9")
            self.assertFalse(self.app_module.is_local_request())

    def test_this_machine_is_local(self):
        with self.app_module.app.test_request_context("/", environ_base=LOCAL):
            self.assertTrue(self.app_module.is_local_request())

    def test_this_machine_by_ip_address_is_local(self):
        for base_url in ("http://127.0.0.1:5000/", "http://[::1]:5000/"):
            with self.subTest(base_url=base_url):
                with self.app_module.app.test_request_context("/", base_url=base_url, environ_base=LOCAL):
                    self.assertTrue(self.app_module.is_local_request())

    def test_a_tunnel_that_adds_no_forwarding_headers_is_still_not_local(self):
        # Tailscale Funnel 跑在這台電腦上，轉進來的請求來源也是 127.0.0.1，
        # 而且不保證會加轉送標頭。外面的人打的是 tunnel 的網域，看 Host 就分得出來。
        with self.app_module.app.test_request_context("/", base_url=FUNNEL_URL, environ_base=LOCAL):
            self.assertFalse(self.app_module.is_local_request())

    def test_a_funnel_visitor_is_counted_by_the_address_tailscale_reports(self):
        # tailscaled（ipn/ipnlocal/serve.go）會先刪掉請求方帶的 Tailscale-Funnel-Request，
        # 再對 Funnel 流量設成 ?1，並用 Header.Set 覆寫 X-Forwarded-For 為連線的來源位址。
        with self.app_module.app.test_request_context(
            "/", base_url=FUNNEL_URL, environ_base=LOCAL,
            headers={"Tailscale-Funnel-Request": "?1", "X-Forwarded-For": "203.0.113.50"},
        ):
            self.assertEqual(self.app_module.client_ip(), "203.0.113.50")
            self.assertFalse(self.app_module.is_local_request())

    def test_cloudflares_address_still_wins_over_a_forged_funnel_marker(self):
        # cloudflared 會把請求方的標頭原樣轉過來，所以它的訪客可以自己塞 Funnel 標記
        with self.app_module.app.test_request_context(
            "/", environ_base=LOCAL,
            headers={**TUNNEL_HEADERS, "Tailscale-Funnel-Request": "?1", "X-Forwarded-For": "1.1.1.1"},
        ):
            self.assertEqual(self.app_module.client_ip(), "203.0.113.9")

    def test_the_funnel_marker_from_another_machine_is_ignored(self):
        with self.app_module.app.test_request_context(
            "/", environ_base=LAN, headers={"Tailscale-Funnel-Request": "?1", "X-Forwarded-For": "1.1.1.1"},
        ):
            self.assertEqual(self.app_module.client_ip(), "192.168.0.50")

    def test_a_forwarded_address_through_another_tunnel_does_not_change_the_rate_limit_key(self):
        # 沒辦法確定 tunnel 會不會把請求方自己填的 X-Forwarded-For 原樣轉過來，
        # 採用它的話，每次換一個值就能繞過以 IP 計的限流
        for spoofed in ("1.1.1.1", "2.2.2.2, 203.0.113.7"):
            with self.subTest(spoofed=spoofed):
                with self.app_module.app.test_request_context(
                    "/", base_url=FUNNEL_URL, environ_base=LOCAL, headers={"X-Forwarded-For": spoofed}
                ):
                    self.assertEqual(self.app_module.client_ip(), "127.0.0.1")
                    self.assertFalse(self.app_module.is_local_request())


class BindHostTests(ApiTestBase):
    def test_only_this_machine_by_default(self):
        self.assertEqual(self.app_module.bind_host([], {}), "127.0.0.1")

    def test_lan_flag_opens_every_network(self):
        self.assertEqual(self.app_module.bind_host(["--lan"], {}), "0.0.0.0")
        self.assertEqual(self.app_module.bind_host([], {"SHARE_ON_LAN": "true"}), "0.0.0.0")

    def test_render_needs_every_network(self):
        # Render 只看 0.0.0.0 上有沒有開埠；綁 127.0.0.1 會部署失敗、一直跑舊版
        self.assertEqual(self.app_module.bind_host([], {"RENDER": "true"}), "0.0.0.0")


class LoginLimitTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.client.post("/auth/signup", json={"email": "target@example.com", "password": "secret-pass"})
        self.app_module._auth_limiter.reset()
        self.app_module._auth_ip_limiter.reset()

    def test_changing_the_forwarded_header_does_not_reset_the_limit(self):
        statuses = [
            self.client.post(
                "/auth/login",
                json={"email": "target@example.com", "password": f"wrong-{i:04d}"},
                environ_base=LAN,
                headers={"X-Forwarded-For": f"10.0.0.{i}"},
            ).status_code
            for i in range(12)
        ]
        self.assertIn(429, statuses)

    def test_one_funnel_visitor_hitting_the_limit_does_not_lock_out_the_others(self):
        # 先前所有 Funnel 訪客都算成 127.0.0.1，一個人連打就讓全部人登入不了
        self.app_module._auth_ip_limiter.max_calls = 2
        self.addCleanup(setattr, self.app_module._auth_ip_limiter, "max_calls", 60)

        def login(address, nickname):
            return self.client.post(
                "/auth/login", json={"email": nickname, "password": "wrong"},
                base_url="https://my-pc.tail1234.ts.net/", environ_base=LOCAL,
                headers={"Tailscale-Funnel-Request": "?1", "X-Forwarded-For": address},
            ).status_code

        noisy = [login("203.0.113.66", f"noisy{i}") for i in range(3)]
        self.assertEqual(noisy[-1], 429)
        self.assertNotEqual(login("198.51.100.7", "someone-else"), 429)

    def test_the_per_account_limit_holds_across_source_addresses(self):
        statuses = [
            self.client.post(
                "/auth/login",
                json={"email": "target@example.com", "password": f"wrong-{i:04d}"},
                environ_base={"REMOTE_ADDR": f"192.168.0.{100 + i}"},
            ).status_code
            for i in range(12)
        ]
        self.assertIn(429, statuses)


class SignupGateTests(ApiTestBase):
    def signup(self, email, code=None, **kwargs):
        payload = {"email": email, "password": "secret-pass"}
        if code is not None:
            payload["invite_code"] = code
        return self.client.post("/auth/signup", json=payload, **kwargs)

    def test_this_machine_can_always_sign_up(self):
        self.assertEqual(self.client.get("/auth/config").get_json()["signup"], "open")
        self.assertEqual(self.signup("owner@example.com").status_code, 201)

    def test_other_devices_cannot_sign_up_without_a_configured_code(self):
        with patch.dict(os.environ, {"SIGNUP_CODE": ""}):
            self.assertEqual(self.client.get("/auth/config", environ_base=LAN).get_json()["signup"], "closed")
            self.assertEqual(self.signup("guest@example.com", environ_base=LAN).status_code, 403)
            self.assertEqual(self.signup("guest2@example.com", headers=TUNNEL_HEADERS).status_code, 403)

    def test_other_devices_need_the_right_code(self):
        with patch.dict(os.environ, {"SIGNUP_CODE": "nutri-2026"}):
            self.assertEqual(self.client.get("/auth/config", headers=TUNNEL_HEADERS).get_json()["signup"], "code")
            self.assertEqual(self.signup("a@example.com", "wrong", headers=TUNNEL_HEADERS).status_code, 403)
            self.assertEqual(self.signup("b@example.com", "nutri-2026", headers=TUNNEL_HEADERS).status_code, 201)

    def test_open_signup_lets_every_device_sign_up_without_a_code(self):
        with patch.dict(os.environ, {"OPEN_SIGNUP": "true", "SIGNUP_CODE": ""}):
            self.assertEqual(self.client.get("/auth/config", headers=TUNNEL_HEADERS).get_json()["signup"], "open")
            self.assertEqual(self.signup("guest@example.com", environ_base=LAN).status_code, 201)
            self.assertEqual(self.signup("guest2@example.com", headers=TUNNEL_HEADERS).status_code, 201)

    def test_render_is_open_unless_turned_off(self):
        # Render 上每個連線都算其他裝置，環境變數要到後台設；沒設就預設開放
        with patch.dict(os.environ, {"RENDER": "true", "SIGNUP_CODE": ""}):
            os.environ.pop("OPEN_SIGNUP", None)
            self.assertEqual(self.client.get("/auth/config", environ_base=LAN).get_json()["signup"], "open")
            self.assertEqual(self.signup("guest@example.com", environ_base=LAN).status_code, 201)
        with patch.dict(os.environ, {"RENDER": "true", "OPEN_SIGNUP": "false", "SIGNUP_CODE": ""}):
            self.assertEqual(self.client.get("/auth/config", environ_base=LAN).get_json()["signup"], "closed")
            self.assertEqual(self.signup("guest2@example.com", environ_base=LAN).status_code, 403)

    def test_existing_accounts_can_still_log_in_from_other_devices(self):
        self.signup("owner@example.com")
        response = self.client.post(
            "/auth/login", json={"email": "owner@example.com", "password": "secret-pass"}, environ_base=LAN
        )
        self.assertEqual(response.status_code, 200)


class OwnerOnlyActionTests(ApiTestBase):
    def test_other_devices_cannot_wipe_the_shared_menu_cache(self):
        self.app_module.storage.save_restaurant_menu("好吃便當", [{"name": "雞腿飯"}])
        with self.mock_auth("user-a"):
            remote = self.client.delete("/restaurants/index/user-a", headers=self.auth_headers(), environ_base=LAN)
            self.assertEqual(remote.status_code, 403)
            self.assertEqual(self.app_module.storage.count_restaurant_menus(), 1)
            local = self.client.delete("/restaurants/index/user-a", headers=self.auth_headers())
        self.assertEqual(local.status_code, 200)
        self.assertEqual(self.app_module.storage.count_restaurant_menus(), 0)

    def test_diagnostics_are_only_shown_to_this_machine(self):
        self.assertIsNone(self.client.get("/health", headers=TUNNEL_HEADERS).get_json()["database_path"])
        with self.mock_auth("user-a"):
            response = self.client.get("/health/gemini", headers={**self.auth_headers(), **TUNNEL_HEADERS})
        self.assertEqual(response.status_code, 403)

    def test_visitors_through_a_funnel_cannot_use_owner_only_actions(self):
        self.app_module.storage.save_restaurant_menu("好吃便當", [{"name": "雞腿飯"}])
        self.assertIsNone(self.client.get("/health", base_url=FUNNEL_URL).get_json()["database_path"])
        with self.mock_auth("user-a"):
            wipe = self.client.delete("/restaurants/index/user-a", headers=self.auth_headers(), base_url=FUNNEL_URL)
            probe = self.client.get("/health/gemini", headers=self.auth_headers(), base_url=FUNNEL_URL)
        self.assertEqual(wipe.status_code, 403)
        self.assertEqual(probe.status_code, 403)
        self.assertEqual(self.app_module.storage.count_restaurant_menus(), 1)


class RequestShapeTests(ApiTestBase):
    def test_oversized_requests_are_rejected_before_parsing(self):
        body = b'{"image": "' + b"A" * (13 * 1024 * 1024) + b'"}'
        with self.mock_auth("user-a"):
            response = self.client.post(
                "/predict/vision-food", data=body, content_type="application/json", headers=self.auth_headers()
            )
        self.assertEqual(response.status_code, 413)
        self.assertIn("太大", response.get_json()["error"])

    def test_bad_coordinates_are_a_400_not_a_crash(self):
        with self.mock_auth("user-a"):
            for lat in ("abc", {"x": 1}, 999):
                response = self.client.post(
                    "/restaurant/menu", json={"name": "某某小吃", "lat": lat}, headers=self.auth_headers()
                )
                self.assertEqual(response.status_code, 400, lat)

    def test_an_uploaded_menu_photo_does_not_enter_the_shared_cache(self):
        recognized = {"items": [{"name": "假的低鈉便當", "price": 10, "calories": 100, "sodium": 1}]}
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "parse_menu_image_with_gemini", return_value=recognized):
            response = self.client.post(
                "/restaurant/menu",
                json={"name": "鼎泰豐 101店", "menu_image": "data:image/png;base64,iVBORw0KGgo="},
                headers=self.auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.app_module.storage.get_restaurant_menu(name="鼎泰豐 101店"))
