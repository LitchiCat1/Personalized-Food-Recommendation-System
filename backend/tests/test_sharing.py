"""讓其他裝置連進來：網站由後端一起提供、同一台電腦其他埠的 CORS、限流以帳號計。"""

import os
import tempfile
from unittest.mock import patch

from test_api_routes import ApiTestBase


class FrontendServingTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        dist = self.folder.name
        os.makedirs(os.path.join(dist, "_expo", "static", "js"))
        for name, text in (("index.html", "<html>home</html>"), ("history.html", "<html>history</html>"),
                           (os.path.join("_expo", "static", "js", "entry-abc.js"), "console.log(1)")):
            with open(os.path.join(dist, name), "w", encoding="utf-8") as f:
                f.write(text)
        self.dist = patch.object(self.app_module, "FRONTEND_DIST", dist)
        self.dist.start()

    def tearDown(self):
        self.dist.stop()
        self.folder.cleanup()

    def get(self, path):
        """讀完就關，送檔案的回應不關會留下沒關的檔案。"""
        response = self.client.get(path)
        response.get_data()
        response.close()
        return response

    def test_pages_scripts_and_api_share_one_port(self):
        self.assertIn(b"home", self.get("/").data)
        self.assertIn(b"history", self.get("/history").data)
        # 沒有對應檔案的頁面交給前端路由
        self.assertIn(b"home", self.get("/scanner").data)
        script = self.get("/_expo/static/js/entry-abc.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("immutable", script.headers["Cache-Control"])
        self.assertEqual(self.get("/").headers["Cache-Control"], "no-cache")
        self.assertEqual(self.get("/health").get_json()["status"], "ok")

    def test_missing_files_and_escapes_are_not_served(self):
        self.assertEqual(self.get("/_expo/static/js/missing.js").status_code, 404)
        self.assertEqual(self.get("/logo.png").status_code, 404)
        self.assertNotIn(b"import", self.get("/..%2fapp.py").data)

    def test_without_a_build_the_root_is_still_the_api_index(self):
        with patch.object(self.app_module, "FRONTEND_DIST", os.path.join(self.folder.name, "nope")):
            self.assertEqual(self.get("/").get_json()["status"], "ok")
            self.assertEqual(self.get("/scanner").status_code, 404)


class SameMachineCorsTests(ApiTestBase):
    def preflight(self, origin, host):
        return self.client.options(
            "/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                     "Access-Control-Request-Headers": "authorization"},
            base_url=f"http://{host}",
        )

    def test_a_dev_server_opened_by_lan_ip_is_allowed(self):
        response = self.preflight("http://192.168.0.102:8081", "192.168.0.102:5000")
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://192.168.0.102:8081")
        self.assertIn("authorization", response.headers.get("Access-Control-Allow-Headers", "").lower())

    def test_other_sites_are_still_blocked(self):
        response = self.preflight("http://evil.example", "192.168.0.102:5000")
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))


class SharedNetworkRateLimitTests(ApiTestBase):
    def test_classmates_behind_one_ip_do_not_share_the_login_limit(self):
        statuses = [
            self.client.post("/auth/signup", json={"email": f"student{i}@school.test", "password": "secret-pass"}).status_code
            for i in range(15)
        ]
        self.assertEqual(statuses, [201] * 15)

    def test_paid_calls_are_counted_per_account(self):
        self.app_module._paid_api_limiter.reset()
        with patch.object(self.app_module._paid_api_limiter, "max_calls", 1):
            for user in ("user-a", "user-b"):
                with self.mock_auth(user):
                    response = self.client.get("/health/gemini", headers=self.auth_headers())
                self.assertNotEqual(response.status_code, 429, f"{user} 被別人的額度擋住")
