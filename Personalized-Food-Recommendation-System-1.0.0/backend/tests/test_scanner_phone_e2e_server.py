import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("scanner_phone_e2e_server", SCRIPTS / "scanner_phone_e2e_server.py")
phone = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC.loader.exec_module(phone)
finally:
    sys.path.remove(str(SCRIPTS))


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.closed = body, status, False

    def iter_content(self, _size):
        yield json.dumps(self.body).encode()

    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.response = FakeResponse({"status": "ok"})

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class ScannerPhoneGatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dist = Path(self.directory.name)
        (self.dist / "index.html").write_text("test-only export", encoding="utf-8")
        self.now = 1000
        self.transport = FakeTransport()
        self.origin = "https://test-machine.example-tailnet.ts.net:8443"
        self.token = "a" * 43
        self.app = phone.create_gateway(
            frontend_dist=self.dist, backend_port=18090, gateway_port=18091,
            public_origin=self.origin, token=self.token, duration_seconds=60,
            clock=lambda: self.now, transport=self.transport,
        )
        self.client = self.app.test_client()

    def call(self, method, path, *, token=True, base_url=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = "Bearer " + self.token
        return self.client.open(path, method=method, base_url=base_url or self.origin, headers=headers, **kwargs)

    def test_auth_expiry_host_and_origin_reject_before_proxy(self):
        path = "/predict/vision-food"
        self.assertEqual(self.call("POST", path, token=False).status_code, 401)
        self.assertEqual(self.call("POST", path, base_url="https://attacker.example").status_code, 403)
        self.assertEqual(self.call("POST", path, headers={"Origin": "https://attacker.example"}).status_code, 403)
        self.now = 1060
        self.assertEqual(self.call("POST", path).status_code, 410)
        self.assertEqual(self.call("POST", "/__phone__/session").status_code, 410)
        self.assertEqual(self.transport.calls, [])

    def test_only_preview_routes_are_forwarded_with_internal_credential(self):
        body = {"scan_id": "scan-1", "scan_revision": 0}
        response = self.call("POST", "/nutrition/fdc/candidates", json=body)
        self.assertEqual(response.status_code, 200)
        method, url, options = self.transport.calls[0]
        self.assertEqual((method, url), ("POST", "http://127.0.0.1:18090/nutrition/fdc/candidates"))
        self.assertEqual(json.loads(options["data"]), body)
        self.assertEqual(options["headers"]["Authorization"], "Bearer " + phone.TEST_TOKEN)
        self.assertFalse(options["allow_redirects"])
        self.assertFalse(self.transport.trust_env)
        self.assertTrue(self.transport.response.closed)
        self.assertNotIn(self.token, response.get_data(as_text=True))

    def test_test_controls_writes_and_other_paid_routes_are_never_forwarded(self):
        for method, path in (
            ("POST", "/record"), ("POST", "/user"), ("POST", "/auth/signup"),
            ("POST", "/nutrition/fdc/profile-accept"), ("POST", "/nutrition/enrichment"),
            ("POST", "/nutrition/fdc/detail"), ("POST", "/menu/photo-check"),
            ("GET", "/__e2e__/state"), ("POST", "/__e2e__/control"),
            ("DELETE", "/nutrition/fdc/candidates"), ("GET", "/../backend/.env.local"),
            ("GET", "/phone-e2e-build.json"),
        ):
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(method, path, json={}).status_code, 403)
        self.assertEqual(self.transport.calls, [])

    def test_bootstrap_requires_random_token_and_does_not_publish_internal_token(self):
        response = self.call("GET", "/__phone__/start", token=False)
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("location.hash", html)
        self.assertIn("history.replaceState", html)
        self.assertNotIn(self.token, html)
        self.assertNotIn(phone.TEST_TOKEN, html)
        self.assertEqual(self.call("POST", "/__phone__/session", token=False).status_code, 401)
        session = self.call("POST", "/__phone__/session")
        self.assertEqual(session.json["accessToken"], self.token)
        self.assertEqual(session.json["user"]["id"], phone.TEST_USER_ID)
        self.assertEqual(session.headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", session.headers)

    def test_readonly_health_contains_no_database_path_or_fixed_credentials(self):
        response = self.call("GET", "/health", token=False)
        self.assertTrue(response.json["test_only"])
        self.assertEqual(response.json["provider_mode"], "synthetic")
        with self.call("GET", "/scanner", token=False) as page:
            self.assertEqual(page.get_data(as_text=True), "test-only export")
        self.assertNotIn("database_path", response.json)
        self.assertNotIn(phone.TEST_TOKEN, response.get_data(as_text=True))
        self.assertEqual(self.transport.calls, [])

    def test_provider_error_codes_preserved_and_oversized_replies_rejected(self):
        self.transport.response = FakeResponse({"error_code": "expired"}, status=409)
        self.assertEqual(self.call("POST", "/nutrition/fdc/confirmation", json={}).status_code, 409)
        self.transport.response = FakeResponse({"data": "a" * phone.MAX_REPLY_BYTES})
        self.assertEqual(self.call("POST", "/nutrition/fdc/profile-preview", json={}).status_code, 502)
        self.assertTrue(self.transport.response.closed)

    def test_build_and_backend_environment_do_not_inherit_keys_or_production_database(self):
        with patch.dict(phone.os.environ, {"DATABASE_PATH": "production.db", "AI_API_KEYS": "secret",
                        "AI_RELAY_KEYS_FILE": "key.txt", "TAVILY_API_KEY": "secret",
                        "EXPO_PUBLIC_API_BASE_URL": "https://production.example"}):
            env = phone.isolated_environment()
        for key in ("DATABASE_PATH", "AI_API_KEYS", "AI_RELAY_KEYS_FILE", "TAVILY_API_KEY", "EXPO_PUBLIC_API_BASE_URL"):
            self.assertNotIn(key, env)
        self.assertEqual(phone.PUBLIC_FLAGS["EXPO_PUBLIC_API_BASE_URL"], "same-origin")
        self.assertEqual(phone.PUBLIC_FLAGS["EXPO_PUBLIC_NUTRITION_ENRICHMENT_ENABLED"], "false")

    def test_production_ports_origins_and_predictable_credentials_rejected(self):
        for origin in ("https://test-machine.example-tailnet.ts.net", "http://test-machine.example-tailnet.ts.net:8443",
                       self.origin + "/scanner", "https://attacker.example:8443", self.origin + "#secret"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                phone.validate_origin(origin)
        for override in ({"backend_port": 5000}, {"gateway_port": 8081}, {"token": phone.TEST_TOKEN},
                         {"duration_seconds": 3601}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                phone.create_gateway(**{
                    "frontend_dist": self.dist, "backend_port": 18090, "gateway_port": 18091,
                    "public_origin": self.origin, "token": self.token, **override,
                })

    def test_funnel_refuses_existing_test_port_and_only_removes_its_own_proxy(self):
        host = "test-machine.example-tailnet.ts.net:8443"
        for config in ({"TCP": {"8443": {"HTTPS": True}}}, {"Web": {host: {"Handlers": {}}}},
                       {"AllowFunnel": {host: False}}):
            with patch.object(phone, "funnel_config", return_value=config), \
                    patch.object(phone.subprocess, "run") as run, self.assertRaises(ValueError):
                phone.configure_funnel("tailscale", self.origin, 18091, enable=True)
            run.assert_not_called()
        config = {"Web": {host: {"Handlers": {"/": {"Proxy": "http://127.0.0.1:18091"}}}},
                  "AllowFunnel": {host: True}}
        with patch.object(phone, "funnel_config", return_value=config), patch.object(phone.subprocess, "run") as run:
            phone.configure_funnel("tailscale", self.origin, 18091, enable=False)
            self.assertEqual(run.call_args.args[0], ["tailscale", "funnel", "--https=8443", "off"])
            run.reset_mock()
            phone.configure_funnel("tailscale", self.origin, 18092, enable=False)
            run.assert_not_called()
