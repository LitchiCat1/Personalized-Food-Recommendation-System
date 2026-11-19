"""Run an isolated SQLite HTTP server for the scanner browser E2E only."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time


TEST_USER_ID = "browser-e2e-user"
TEST_TOKEN = "browser-e2e-token"
STATE_KIND = "nutrilens-scanner-browser-e2e-v1"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-path", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reviewed-apple-capture", help="Offline reviewed171688 capture; never calls providers")
    parser.add_argument("--frontend-dist", help="Optional static Expo export inside this test DB's temp directory")
    parser.add_argument("--identity-correction-fixture", action="store_true",
                        help="Enable an isolated generic-food name correction fixture")
    return parser.parse_args()


def validate_database_path(value, *, resume=False):
    path = Path(value).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        path.relative_to(temp_root)
    except ValueError as error:
        raise SystemExit("Refusing to start: E2E database must be under the system temp directory") from error
    if not path.parent.name.startswith("nutrilens-scanner-browser-e2e-"):
        raise SystemExit("Refusing to start: E2E database must use a dedicated temporary directory")
    if resume:
        read_test_state(path)
        if not path.is_file():
            raise SystemExit("Refusing to resume: E2E database must already exist")
    elif path.exists() or state_path(path).exists():
        raise SystemExit("Refusing to start: E2E database path must not already exist")
    return path


def state_path(database_path):
    return database_path.with_name(database_path.name + ".e2e-state.json")


def validate_frontend_dist(value, database_path):
    path = Path(value).resolve()
    try:
        path.relative_to(database_path.parent.resolve())
    except ValueError as error:
        raise SystemExit("Static test export must stay inside the dedicated temporary directory") from error
    if not path.is_dir() or not (path / "index.html").is_file():
        raise SystemExit("A completed static Expo export is required")
    return path


def read_test_state(database_path):
    marker = state_path(database_path)
    try:
        if marker.is_symlink() or marker.stat().st_size > 4096:
            raise ValueError("Invalid marker file")
        state = json.loads(marker.read_text(encoding="utf-8"))
        if (not isinstance(state, dict)
                or set(state) != {"kind", "database_path", "clock_offset_seconds"}
                or state["kind"] != STATE_KIND
                or state["database_path"] != str(database_path)
                or isinstance(state["clock_offset_seconds"], bool)
                or not isinstance(state["clock_offset_seconds"], (int, float))
                or not math.isfinite(state["clock_offset_seconds"])
                or not 0 <= state["clock_offset_seconds"] <= 86400):
            raise ValueError("Marker does not match this E2E database")
        return state
    except (OSError, ValueError, TypeError) as error:
        raise SystemExit("Refusing to resume: valid database-specific E2E marker required") from error


class TestClock:
    __test__ = False

    def __init__(self, database_path, *, resume=False):
        self.database_path = database_path
        self.lock = threading.RLock()
        self.state = read_test_state(database_path) if resume else {
            "kind": STATE_KIND, "database_path": str(database_path), "clock_offset_seconds": 0,
        }
        if not resume:
            with state_path(database_path).open("x", encoding="utf-8") as marker:
                json.dump(self.state, marker)

    def __call__(self):
        with self.lock:
            return time.time() + self.state["clock_offset_seconds"]

    def advance(self, seconds):
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or seconds <= 0):
            raise ValueError("advance_seconds must be positive and finite")
        with self.lock:
            offset = self.state["clock_offset_seconds"] + seconds
            if offset > 86400:
                raise ValueError("E2E clock offset exceeds one day")
            self.state["clock_offset_seconds"] = offset
            marker = state_path(self.database_path)
            temporary = marker.with_name(marker.name + ".tmp")
            temporary.write_text(json.dumps(self.state), encoding="utf-8")
            temporary.replace(marker)
            return offset


def configure_environment(database_path):
    os.environ.update({
        "NUTRILENS_SKIP_LOCAL_ENV": "1",
        "DATABASE_PATH": str(database_path),
        "AUTH_REQUIRED": "true",
        "ALLOWED_ORIGINS": "http://localhost:8082",
        "GEMINI_API_KEY": "e2e-dummy-key-never-sent",
        "FDC_CANDIDATE_ROUTE_ENABLED": "true",
        "FDC_REVIEWED_SELECTION_ROUTE_ENABLED": "false",
        "FDC_CONFIRMATION_ROUTE_ENABLED": "true",
        "FDC_PROFILE_PREVIEW_ROUTE_ENABLED": "true",
        "FDC_PROFILE_ACCEPT_ROUTE_ENABLED": "false",
        "FDC_DETAIL_ROUTE_ENABLED": "false",
        "NUTRITION_IDENTITY_CONFIRMATION_ROUTE_ENABLED": "false",
        "NUTRITION_ENRICHMENT_ROUTE_ENABLED": "false",
        "NUTRITION_SCAN_CONTEXT_TTL_SECONDS": "120",
    })
    os.environ.pop("DATABASE_URL", None)


class FakeSearchClient:
    candidate = {
        "fdcId": "171688",
        "description": "Apples, raw, with skin",
        "dataType": "SR Legacy",
        "brandOwner": None,
        "foodCategory": "Fruit",
    }

    def __init__(self):
        self.calls = []
        self.failures = 0
        self.lock = threading.Lock()

    def search_foods(self, query, *, deadline, page_size):
        with self.lock:
            self.calls.append({"query": query, "page_size": page_size})
            if self.failures:
                self.failures -= 1
                from services.fooddata_central_client import FoodDataCentralClientError
                raise FoodDataCentralClientError("upstream_error", "Synthetic E2E provider failure")
        return {"candidates": [dict(self.candidate)]}

    def close(self):
        return None


def main():
    args = parse_args()
    if args.host not in {"127.0.0.1", "::1"}:
        raise SystemExit("Refusing to start: E2E server must bind to a literal loopback address")
    database_path = validate_database_path(args.database_path, resume=args.resume)
    clock = TestClock(database_path, resume=args.resume)
    configure_environment(database_path)
    if args.identity_correction_fixture:
        os.environ["NUTRITION_IDENTITY_CONFIRMATION_ROUTE_ENABLED"] = "true"

    backend_dir = Path(__file__).resolve().parents[1]
    tests_dir = backend_dir / "tests"
    sys.path.insert(0, str(backend_dir))
    sys.path.insert(0, str(tests_dir))

    from test_fdc_profile_preview_service import FakeClient, detail_document, reviewed_policy
    from services.fdc_profile_preview_service import FdcProfilePreviewService
    from services.fdc_reviewed_selection_service import FdcReviewedSelectionService

    import app as backend

    if args.frontend_dist:
        backend.FRONTEND_DIST = str(validate_frontend_dist(args.frontend_dist, database_path))

    backend.app.config.update(TESTING=True)
    for repository in (
        backend.nutrition_scan_context_repository,
        backend.nutrition_identity_confirmation_repository,
        backend.fdc_candidate_snapshot_repository,
        backend.fdc_candidate_confirmation_repository,
        backend.fdc_profile_preview_repository,
    ):
        repository.clock = clock

    def verify_test_token(_repository, authorization):
        if authorization != f"Bearer {TEST_TOKEN}":
            raise backend.AuthError("Test authentication required", 401)
        return {"id": TEST_USER_ID, "email": "browser-e2e@example.invalid"}

    backend.verify_access_token = verify_test_token
    reviewed_entry = None
    replay_document = detail_document()
    if args.reviewed_apple_capture:
        root = backend_dir.parent
        candidate = json.loads((backend_dir / "config" / "nutrition_source_candidates" /
                                "usda-fdc-171688.json").read_text(encoding="utf-8"))
        proof = json.loads((root / "docs" / "food-nutrition-evaluation" / "2026-11-14" /
                           "fdc-generic-apple-source-20261116.json").read_text(encoding="utf-8"))
        replay_document = json.loads(Path(args.reviewed_apple_capture).read_text(encoding="utf-8"))
        digest = hashlib.sha256(json.dumps(replay_document["payload"], ensure_ascii=True,
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        spec = candidate["policy"]["source_spec"]
        if (digest != proof["payload_sha256"] or digest != replay_document.get("content_hash")
                or str(replay_document["payload"].get("fdcId")) != "171688"
                or replay_document.get("url") != spec["source_url"]
                or replay_document.get("retrieval_version") != spec["retrieval_version"]
                or replay_document.get("retrieved_at") != proof["retrieved_at"]
                or replay_document["payload"].get("description") != spec["food_identity"]["name"]):
            raise SystemExit("Refusing unverified reviewed-apple capture")
        reviewed_entry = {"policy": candidate["policy"], "admission_review": candidate["admission_review"],
            "candidate": {"fdcId": "171688", "description": replay_document["payload"]["description"],
                          "dataType": replay_document["payload"]["dataType"],
                          "brandOwner": None, "foodCategory": None}}
        backend.fdc_reviewed_selection_route_enabled = True
        backend.fdc_candidate_route_enabled = False
        backend.fdc_reviewed_selection_service = FdcReviewedSelectionService(
            scan_context_repository=backend.nutrition_scan_context_repository,
            snapshot_repository=backend.fdc_candidate_snapshot_repository,
            source_repository=backend.nutrition_profile_repository,
            local_lookup_factory=lambda _owner: lambda _item: {"status": "no_local_mapping"},
            official_health={name: {"status": "available"} for name in ("TFDA", "USDA FNDDS")},
            reviewed_sources=[reviewed_entry])

    if args.identity_correction_fixture:
        vision_fixture = {
            "meal_guess": "炒菜葉",
            "items": [{
                "name_zh": "炒菜葉",
                "name_en": "stir-fried leafy greens",
                "confidence": 0.92,
                "estimated_weight_g": 120,
                "weight_confidence": 0.82,
                "food_state": "prepared",
                "preparation_method": "stir_fried",
                "components_scope": "food_only",
                "count": 1,
                "portion_description": "一份炒菜",
                "visual_evidence": "Synthetic generic-food identity fixture",
                "alternatives": [],
            }],
            "uncertainty_notes": [],
        }
    else:
        vision_fixture = {
            "meal_guess": "蘋果",
            "items": [{
                "name_zh": "蘋果",
                "name_en": "Apples, raw, with skin",
                "confidence": 0.95,
                "estimated_weight_g": 150,
                "weight_confidence": 0.9,
                "food_state": "raw",
                "preparation_method": "mixed",
                "components_scope": "food_only",
                "variant": "with_skin" if reviewed_entry else None,
                "count": 1,
                "portion_description": "一顆中型蘋果",
                "visual_evidence": "Synthetic E2E recognition fixture",
                "alternatives": [],
            }],
            "uncertainty_notes": [],
        }
    backend.call_gemini_food_recognition_with_rotation = lambda *_args: vision_fixture

    backend.storage.upsert_user({
        "user_id": TEST_USER_ID,
        "name": "Browser E2E",
        "email": "browser-e2e@example.invalid",
        "gender": "female",
        "height": 165,
        "weight": 60,
        "age": 30,
        "activity_level": "輕度活動量",
        "activity_multiplier": 1.375,
        "health_conditions": [],
        "allergens": [],
        "target_weight": 60,
        "diet_type": "葷食",
        "profile_complete": True,
    })
    if not args.resume:
        backend.nutrition_profile_repository.save_source_policy(
            reviewed_entry["policy"] if reviewed_entry else reviewed_policy())

    fake_search = FakeSearchClient()
    backend.fdc_candidate_search_service.local_lookup_factory = (
        lambda _user_id: lambda _item: {"status": "no_local_mapping"})
    backend.fdc_candidate_search_service.client_factory = lambda: fake_search
    backend.fdc_candidate_search_service.official_health = {
        "TFDA": {"status": "available"},
        "USDA FNDDS": {"status": "available"},
    }
    detail_calls = []
    detail_control = {"advance_seconds": 0}

    def detail_returned():
        detail_calls.append(True)
        advance = detail_control["advance_seconds"]
        detail_control["advance_seconds"] = 0
        if advance:
            clock.advance(advance)

    def detail_client():
        return FakeClient(replay_document, on_get=detail_returned)

    backend.fdc_profile_preview_service = FdcProfilePreviewService(
        confirmation_repository=backend.fdc_candidate_confirmation_repository,
        scan_context_repository=backend.nutrition_scan_context_repository,
        source_repository=backend.nutrition_profile_repository,
        detail_client_factory=detail_client,
        clock=clock,
    )

    from flask import jsonify, request

    def test_control_auth():
        return request.headers.get("Authorization") == f"Bearer {TEST_TOKEN}"

    @backend.app.get("/__e2e__/state")
    def test_state():
        if not test_control_auth():
            return jsonify({"error": "Test authentication required"}), 401
        tables = {
            "scan_contexts": "nutrition_scan_contexts",
            "candidate_snapshots": "nutrition_fdc_candidate_snapshots",
            "confirmations": "nutrition_fdc_candidate_confirmations",
            "identity_confirmations": "nutrition_identity_confirmations",
            "previews": "nutrition_fdc_profile_previews",
            "nutrition_profiles": "nutrition_profiles",
            "meal_records": "records",
        }
        counts = {name: backend.sql_db.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
                  for name, table in tables.items()}
        return jsonify({
            "pid": os.getpid(), "now": clock(), "clock_offset_seconds": clock.state["clock_offset_seconds"],
            "search_calls": len(fake_search.calls), "detail_calls": len(detail_calls),
            "identity_confirmation_route_enabled": backend.nutrition_identity_confirmation_route_enabled,
            "scan_ttl_seconds": backend._nutrition_scan_context_ttl_seconds(), "counts": counts,
            "policies": [dict(row) for row in backend.sql_db.query_all(
                "SELECT source_id, policy_revision, status FROM nutrition_source_policies")],
            "scans": [dict(row) for row in backend.sql_db.query_all(
                "SELECT scan_id, scan_revision, expires_at, status FROM nutrition_scan_contexts")],
            "previews": [dict(row) for row in backend.sql_db.query_all(
                "SELECT preview_id, expires_at, status FROM nutrition_fdc_profile_previews")],
        })

    @backend.app.post("/__e2e__/control")
    def test_control():
        if not test_control_auth():
            return jsonify({"error": "Test authentication required"}), 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "A control object is required"}), 400
        try:
            if set(body) == {"advance_seconds"}:
                clock.advance(body["advance_seconds"])
            elif set(body) == {"search_failures"} and type(body["search_failures"]) is int \
                    and 0 <= body["search_failures"] <= 10:
                fake_search.failures = body["search_failures"]
            elif (set(body) == {"detail_advance_seconds"}
                  and not isinstance(body["detail_advance_seconds"], bool)
                  and isinstance(body["detail_advance_seconds"], (int, float))
                  and math.isfinite(body["detail_advance_seconds"])
                  and 0 <= body["detail_advance_seconds"] <= 3600):
                detail_control["advance_seconds"] = body["detail_advance_seconds"]
            else:
                raise ValueError("Unknown or invalid E2E control")
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        return jsonify({"ok": True, "now": clock(), "clock_offset_seconds": clock.state["clock_offset_seconds"]})

    from werkzeug.serving import make_server

    server = make_server(args.host, args.port, backend.app, threaded=True)
    print(f"E2E_SERVER_READY database={database_path} host={args.host} port={args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if backend.sql_db is not None:
            backend.sql_db.close()


if __name__ == "__main__":
    main()
