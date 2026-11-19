"""Short-lived phone gateway to the loopback-only, synthetic scanner E2E.

Serve this gateway on a separate HTTPS port. Never publish the underlying
browser harness: it has a fixed credential and mutable test controls.
"""

import argparse
from collections import deque
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.serving import make_server

from scanner_browser_e2e_server import TEST_TOKEN, TEST_USER_ID


MAX_REPLY_BYTES = 2 * 1024 * 1024
PUBLIC_FLAGS = {
    "EXPO_PUBLIC_API_BASE_URL": "same-origin",
    "EXPO_PUBLIC_AUTH_REQUIRED": "true",
    "EXPO_PUBLIC_FDC_CANDIDATE_SEARCH_ENABLED": "true",
    "EXPO_PUBLIC_FDC_CONFIRMATION_ENABLED": "true",
    "EXPO_PUBLIC_FDC_PROFILE_PREVIEW_ENABLED": "true",
    "EXPO_PUBLIC_NUTRITION_ENRICHMENT_ENABLED": "false",
}
API_METHODS = {
    "/auth/user": {"GET"},
    f"/user/{TEST_USER_ID}": {"GET"},
    "/medical-metadata": {"GET"},
    "/predict/vision-food": {"POST"},
    "/nutrition/fdc/candidates": {"GET", "POST"},
    "/nutrition/fdc/confirmation": {"POST"},
    "/nutrition/fdc/profile-preview": {"POST"},
}


def validate_origin(value):
    parsed = urlsplit(value)
    # Port 443 already hosts the normal site, with a different DB and bundle.
    if (parsed.scheme != "https" or parsed.port != 8443 or parsed.path
            or parsed.query or parsed.fragment or parsed.username or parsed.password
            or not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.ts\.net", parsed.hostname or "")
            or value != f"https://{parsed.hostname}:8443"):
        raise ValueError("Use a canonical Tailscale HTTPS origin on the separate port 8443")
    return value


def isolated_environment():
    # Preserve only OS/toolchain settings; never inherit provider or DB secrets.
    allowed = {"path", "pathext", "systemroot", "windir", "comspec", "temp", "tmp",
               "userprofile", "appdata", "localappdata", "programfiles", "programfiles(x86)",
               "programdata", "homedrive", "homepath", "number_of_processors", "home",
               "lang", "lc_all"}
    return {key: value for key, value in os.environ.items() if key.lower() in allowed}


def build_frontend(directory):
    project = Path(__file__).resolve().parents[2]
    frontend = project / "frontend"
    env = isolated_environment()
    env.update(PUBLIC_FLAGS, EXPO_NO_DOTENV="1", CI="1", NODE_ENV="production",
               EXPO_PUBLIC_GOOGLE_MAPS_API_KEY="")
    subprocess.run(
        ["node", str(frontend / "node_modules/expo/bin/cli"), "export", "--platform", "web",
         "--output-dir", str(directory), "--clear"], cwd=frontend, env=env, check=True,
        timeout=240,
    )
    (directory / "phone-e2e-build.json").write_text(json.dumps(PUBLIC_FLAGS), encoding="utf-8")


BOOTSTRAP_HTML = """<!doctype html>
<html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NutriLens 隔離流程測試</title>
<style>
body{font:16px system-ui;margin:0;padding:24px;background:#f5f7f8;color:#172329}
main{max-width:600px;margin:32px auto}h1{font-size:24px;letter-spacing:0}
p{line-height:1.6}button{min-height:48px;padding:12px 20px;font:inherit;cursor:pointer}
#status{color:#a13535;overflow-wrap:anywhere}
</style><main><h1>NutriLens 隔離流程測試</h1>
<p>本次拍照或選圖會固定回傳蘋果測試資料，用來驗證候選確認與營養預覽。</p>
<p>測試結果不會加入飲食紀錄。營養數字為固定測試值。</p>
<button id="start">開始測試</button><p id="status" role="status"></p></main>
<script>
const token = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
document.querySelector('#start').onclick = async () => {
  const button = document.querySelector('#start');
  button.disabled = true;
  try {
    const response = await fetch('/__phone__/session', {
      method: 'POST', headers: {Authorization: 'Bearer ' + token}
    });
    if (!response.ok) throw new Error('測試連結已失效，請使用新的測試連結。');
    localStorage.setItem('nutrilens.auth.session', JSON.stringify(await response.json()));
    location.replace('/scanner');
  } catch (error) {
    document.querySelector('#status').textContent = error.message;
    button.disabled = false;
  }
};
</script></html>"""


def create_gateway(*, frontend_dist, backend_port, gateway_port, public_origin,
                   token, duration_seconds=1800, clock=time.monotonic, transport=None):
    validate_origin(public_origin)
    if not 1024 <= backend_port <= 65535 or not 1024 <= gateway_port <= 65535:
        raise ValueError("Dedicated ports are required")
    if backend_port == gateway_port or {backend_port, gateway_port} & {5000, 8081}:
        raise ValueError("Do not use the existing production/development ports")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token):
        raise ValueError("A fresh random phone credential is required")
    if not 60 <= duration_seconds <= 3600:
        raise ValueError("Phone sessions must last between one minute and one hour")
    app = Flask("scanner-phone-e2e", static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=8 * 1024 * 1024)
    deadline = clock() + duration_seconds
    expires_at = datetime.fromtimestamp(time.time() + duration_seconds, timezone.utc).isoformat()
    trace = deque(maxlen=1000)
    session = transport or requests.Session()
    session.trust_env = False
    local_hosts = {f"127.0.0.1:{gateway_port}", f"localhost:{gateway_port}"}
    allowed_hosts = local_hosts | {urlsplit(public_origin).netloc}
    origins = {public_origin} | {"http://" + host for host in local_hosts}

    @app.before_request
    def check_boundary():
        if request.host not in allowed_hosts:
            return jsonify(error="Wrong test origin"), 403
        if request.headers.get("Origin") and request.headers["Origin"] not in origins:
            return jsonify(error="Wrong test origin"), 403
        if clock() >= deadline:
            return jsonify(error="Phone test session expired", error_code="expired"), 410
        if request.path in API_METHODS or request.path in {"/__phone__/session", "/__phone__/state"}:
            supplied = request.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
                return jsonify(error="Phone test authentication required"), 401

    @app.after_request
    def response_boundary(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        if request.path in API_METHODS:
            trace.append({"method": request.method, "path": request.path, "status": response.status_code})
        return response

    def forward(path):
        response = None
        try:
            # The caller cannot choose host, headers, redirect target or test token.
            response = session.request(
                request.method, f"http://127.0.0.1:{backend_port}" + path,
                headers={"Authorization": "Bearer " + TEST_TOKEN, "Content-Type": "application/json"},
                params=list(request.args.items(multi=True)) if request.method == "GET" else None,
                data=request.get_data() if request.method == "POST" else None,
                timeout=(3, 30), allow_redirects=False, stream=True,
            )
            chunks, size = [], 0
            for chunk in response.iter_content(8192):
                size += len(chunk)
                if size > MAX_REPLY_BYTES:
                    raise ValueError("Oversized test response")
                chunks.append(chunk)
            body = json.loads(b"".join(chunks))
            if not isinstance(body, dict) or not (200 <= response.status_code < 300 or 400 <= response.status_code < 600):
                return jsonify(error="Isolated backend unavailable"), 502
            return jsonify(body), response.status_code
        except (requests.RequestException, ValueError):
            return jsonify(error="Isolated backend unavailable"), 502
        finally:
            if response is not None:
                response.close()

    @app.get("/health")
    def health():
        return jsonify(status="ok", test_only=True, provider_mode="synthetic",
                       app_version="v1.0.3", database="temporary-sqlite", expires_at=expires_at,
                       allowed_operations=["scan", "candidates", "confirmation", "preview"])

    @app.get("/__phone__/start")
    def start():
        return Response(BOOTSTRAP_HTML, content_type="text/html; charset=utf-8")

    @app.post("/__phone__/session")
    def bootstrap_session():
        return jsonify(accessToken=token, expiresAt=expires_at,
                       user={"id": TEST_USER_ID, "email": "browser-e2e@example.invalid"})

    @app.get("/__phone__/state")
    def state():
        # Counts only: no clock/provider control and no DB paths or policy bodies.
        response = None
        try:
            response = session.get(f"http://127.0.0.1:{backend_port}/__e2e__/state",
                                   headers={"Authorization": "Bearer " + TEST_TOKEN},
                                   timeout=(3, 5), allow_redirects=False)
            response.raise_for_status()
            body = response.json()
            return jsonify(counts=body["counts"], search_calls=body["search_calls"],
                           detail_calls=body["detail_calls"], trace=list(trace))
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return jsonify(error="Isolated backend unavailable"), 502
        finally:
            if response is not None:
                response.close()

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def dispatch(path):
        api_path = "/" + path
        if api_path in API_METHODS and request.method in API_METHODS[api_path]:
            return forward(api_path)
        if request.method == "GET":
            if path in {"", "scanner"}:
                return send_from_directory(frontend_dist, "index.html")
            if path.startswith(("_expo/", "assets/")) or path == "favicon.ico":
                return send_from_directory(frontend_dist, path)
        return jsonify(error="Operation is outside the phone preview test"), 403

    return app


def available_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def funnel_config(executable):
    result = subprocess.run([executable, "serve", "status", "--json"],
                            check=True, capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)


def configure_funnel(executable, origin, port, *, enable):
    config = funnel_config(executable)
    host = urlsplit(origin).netloc
    web = config.get("Web", {}).get(host)
    expected = {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{port}"}}}
    if enable:
        if "8443" in config.get("TCP", {}) or web or host in config.get("AllowFunnel", {}):
            raise ValueError("Port 8443 already has a Tailscale configuration; nothing was changed")
        subprocess.run([executable, "funnel", "--bg", "--https=8443", "--yes", str(port)],
                       check=True, timeout=30)
    elif web == expected and config.get("AllowFunnel", {}).get(host) is True:
        # Only remove this exact test proxy, preserving the existing 443 site.
        subprocess.run([executable, "funnel", "--https=8443", "off"], check=True, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--funnel", action="store_true", help="Publish only the isolated gateway on HTTPS 8443")
    args = parser.parse_args()
    validate_origin(args.origin)
    if not 1024 <= args.port <= 65535 or args.port in {5000, 8081} or not 1 <= args.minutes <= 60:
        parser.error("Use a dedicated port and a one-to-sixty-minute lifetime")
    directory = Path(tempfile.mkdtemp(prefix="nutrilens-scanner-browser-e2e-phone-")).resolve()
    dist = directory / "web"
    build_frontend(dist)
    backend_port = available_port()
    token = secrets.token_urlsafe(32)
    gateway = create_gateway(frontend_dist=dist, backend_port=backend_port, gateway_port=args.port,
                             public_origin=args.origin, token=token, duration_seconds=args.minutes * 60)
    server = make_server("127.0.0.1", args.port, gateway, threaded=True)
    child = None
    funnel = (shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe") if args.funnel else None
    published = False
    log = (directory / "backend.log").open("w", encoding="utf-8")
    try:
        env = isolated_environment()
        env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        child = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).with_name("scanner_browser_e2e_server.py")),
             "--database-path", str(directory / "scanner.sqlite3"), "--port", str(backend_port)],
            env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        with requests.Session() as probe:
            probe.trust_env = False
            until = time.monotonic() + 30
            while True:
                if child.poll() is not None or time.monotonic() >= until:
                    raise RuntimeError("Isolated backend failed to start; inspect temporary backend.log")
                try:
                    response = probe.get(f"http://127.0.0.1:{backend_port}/__e2e__/state",
                                         headers={"Authorization": "Bearer " + TEST_TOKEN}, timeout=1)
                    if response.status_code == 200 and response.json().get("pid") == child.pid:
                        break
                except (requests.RequestException, ValueError):
                    pass
                time.sleep(0.1)
        if funnel:
            configure_funnel(funnel, args.origin, args.port, enable=True)
            published = True
        # Save the link only to this local temporary run, never to evidence/Git.
        run = {"origin": args.origin, "port": args.port, "pid": os.getpid(), "backend_pid": child.pid,
               "backend_port": backend_port, "directory": str(directory),
               "url": args.origin + "/__phone__/start#" + token,
               "local_url": f"http://127.0.0.1:{args.port}/__phone__/start#" + token}
        (directory / "phone-run.json").write_text(json.dumps(run), encoding="utf-8")
        print("PHONE_E2E_READY " + str(directory), flush=True)
        print(run["url"], flush=True)
        stop_at = time.monotonic() + args.minutes * 60
        server.timeout = 0.5
        while time.monotonic() < stop_at and child.poll() is None:
            server.handle_request()
    finally:
        server.server_close()
        if published:
            try:
                configure_funnel(funnel, args.origin, args.port, enable=False)
            except (OSError, ValueError, subprocess.SubprocessError):
                print("Phone test ended; verify that the temporary HTTPS 8443 proxy was removed", flush=True)
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        log.close()


if __name__ == "__main__":
    main()
