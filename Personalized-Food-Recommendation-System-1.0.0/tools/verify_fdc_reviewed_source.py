"""Replay a previously captured real FDC response into temporary SQLite only."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from repositories.fdc_candidate_confirmation_repository import FdcCandidateConfirmationRepository
from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.fdc_profile_preview_repository import (
    FdcProfilePreviewRepository, FdcProfilePreviewRepositoryError,
)
from repositories.nutrition_profile_repository import (
    NutritionProfileSourceRepository, NutritionRepositoryError,
)
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_profile_preview_service import FdcProfilePreviewError, FdcProfilePreviewService
from services.fooddata_central_selection_service import CONFIRMATION_SCHEMA_VERSION
from services.nutrition_source_admission_service import validate_source_admission


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def denied(code, exception_type, action):
    try:
        action()
    except exception_type as error:
        require(error.code == code, f"Expected {code}, received {error.code}")
    else:
        raise AssertionError(f"Expected rejection: {code}")


def verify(payload_path, *, candidate_path=None, proof_path=None):
    evidence_root = ROOT / "docs" / "food-nutrition-evaluation" / "2026-11-14"
    proof_path = proof_path or evidence_root / "usda-fdc-detail-replay-20261115.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    capture = json.loads(payload_path.read_text(encoding="utf-8"))
    captured = capture.get("payload", capture)
    encoded = json.dumps(captured, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    require(digest in proof.get("observed_payload_hashes", [proof["payload_sha256"]]),
            "Input is not a previously verified capture")
    candidate_path = candidate_path or (ROOT / "backend" / "config" / "nutrition_source_candidates" /
                                       "usda-fdc-1750340.json")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    policy = validate_source_admission(candidate["policy"], candidate["admission_review"])
    if "policy_sha256" in proof:
        require(candidate["admission_review"]["policy_sha256"] == proof["policy_sha256"],
                "Policy differs from the source review")
    replayed_at = datetime.now(timezone.utc).isoformat()
    expected_id = policy["source_spec"]["fdc_id"]
    require(str(captured["fdcId"]) == expected_id == str(proof["fdc_id"]), "Capture/policy/proof ID differs")
    target_variant = policy["target_identity"]["variant"]
    retrieved_at = capture.get("retrieved_at", replayed_at)
    if "payload" in capture:
        require(capture.get("content_hash") == digest, "Capture envelope hash differs")
        require(capture.get("url") == policy["source_spec"]["source_url"], "Capture URL differs")
        require(capture.get("retrieval_version") == policy["source_spec"]["retrieval_version"],
                "Capture retrieval version differs")
        require(retrieved_at == proof["retrieved_at"], "Original retrieval time differs from source review")
    document = {"url": policy["source_spec"]["source_url"], "payload": captured,
                "content_hash": digest, "retrieved_at": retrieved_at,
                "retrieval_version": policy["source_spec"]["retrieval_version"]}
    # Preserve an original capture envelope's retrieval time. A bare historical
    # payload has only the replay time, never an inferred original timestamp.
    detail_calls = []

    class ReplayClient:
        def get_food(self, fdc_id, *, deadline):
            require(fdc_id == expected_id, "Unexpected FDC ID")
            detail_calls.append(fdc_id)
            return deepcopy(document)

        def close(self):
            pass

    now = lambda: 1000.0
    with tempfile.TemporaryDirectory(prefix="nutrilens-reviewed-fdc-") as directory:
        database_path = str(Path(directory) / "acceptance.db")
        sql = SqliteDatabase(database_path)

        def repositories():
            scans = NutritionScanContextRepository(sql, clock=now)
            snapshots = FdcCandidateSnapshotRepository(sql, scan_context_repository=scans, clock=now)
            confirmations = FdcCandidateConfirmationRepository(sql, snapshot_repository=snapshots, clock=now)
            sources = NutritionProfileSourceRepository(sql)
            previews = FdcProfilePreviewRepository(sql, source_repository=sources, clock=now)
            service = FdcProfilePreviewService(
                confirmation_repository=confirmations, scan_context_repository=scans,
                source_repository=sources, detail_client_factory=ReplayClient,
                clock=now, monotonic=lambda: 20.0)
            return scans, snapshots, confirmations, sources, previews, service

        def confirmed(scan_id, name, variant):
            item_id = scan_id + ":0"
            item = {"item_id": item_id, "item_revision": 0, "name_zh": name,
                    "confidence": 0.9, "weight_confidence": 0.8, "estimated_weight_g": 150,
                    **policy["target_identity"], "variant": variant, "validation_issues": []}
            scans.save_scan_context(user_id="replay-owner", scan_id=scan_id,
                                    scan_revision=0, items=[item], ttl_seconds=120)
            snapshot = snapshots.save_candidates(
                user_id="replay-owner", scan_id=scan_id, scan_revision=0,
                candidates_by_item={item_id: [{"fdcId": expected_id, "description": captured["description"],
                                              "dataType": captured["dataType"],
                                              "brandOwner": None, "foodCategory": "Fruit"}]})["snapshot"]
            confirmation = confirmations.record_confirmation(
                authenticated_user_id="replay-owner", actor_id="replay-owner",
                scan_id=scan_id, scan_revision=0, idempotency_key="confirm-" + scan_id,
                confirmation={"schema_version": CONFIRMATION_SCHEMA_VERSION,
                              "snapshot_digest": snapshot["snapshot_digest"], "scan_revision": 0,
                              "items": [{"item_id": item_id, "decision": "confirm",
                                         "candidate_fdc_id": expected_id}]})
            return dict(authenticated_user_id="replay-owner", scan_id=scan_id,
                        issued_scan_revision=1, item_id=item_id,
                        confirmation_id=confirmation["confirmation_id"])

        try:
            scans, snapshots, confirmations, sources, previews, service = repositories()
            sources.save_source_policy(policy)
            counterexamples = (
                ("unknown-apple", "蘋果", None),
                ("missing-variety", policy["accepted_names"][0], None),
                ("renamed-apple", "蘋果", "fuji_with_skin"),
            ) if expected_id == "1750340" else (
                ("unknown-skin", "蘋果", None),
                ("peeled-apple", "去皮蘋果", "without_skin"),
                ("fuji-apple", "富士蘋果", "fuji_with_skin"),
            )
            for scan_id, name, variant in counterexamples:
                request = confirmed(scan_id, name, variant)
                denied("identity_mismatch", FdcProfilePreviewError, lambda: service.preview(**request))
                context = scans.get_scan_context(user_id="replay-owner", scan_id=scan_id, scan_revision=1)
                require(context["items"][0]["name_zh"] == name, "Candidate confirmation renamed the food")
                require(context["items"][0]["variant"] == variant, "Candidate confirmation inferred a variety")
            require(not detail_calls, "Identity mismatch fetched Detail")
            request = confirmed("reviewed-apple", policy["accepted_names"][0], target_variant)
            result = service.preview(**request)
            profile = result["preview"]["nutrition_profile"]
            portion = result["preview"]["portion"]
            require(profile["per_100g"] == proof["per_100g"], "Per-100g values differ from captured evidence")
            require(portion["values"] == proof["portion_150g"]["values"], "Portion differs from original-cell calculation")
            require(result["preview"]["recognition_identity"]["name_zh"] == policy["accepted_names"][0],
                    "Source description replaced recognition name")
            saved = previews.save_preview(result, preview_id="reviewed-preview")
            pending = previews.save_preview(result, preview_id="withdrawal-preview")
            require(sql.query_one("SELECT COUNT(*) AS n FROM nutrition_profiles")["n"] == 0,
                    "Preview wrote a profile")
            sql.close()
            sql = SqliteDatabase(database_path)
            scans, snapshots, confirmations, sources, previews, service = repositories()
            require(previews.get_preview(authenticated_user_id="replay-owner", preview_id="reviewed-preview") == saved,
                    "Preview changed after reopening SQLite")
            accepted = previews.accept_preview(authenticated_user_id="replay-owner",
                                               preview_id="reviewed-preview", idempotency_key="accept-once")
            require(not accepted["replayed"], "First acceptance was a replay")
            require(accepted["profile_hash"] == saved["profile_hash"], "Accepted profile hash changed")
            source_details = accepted["profile"]["profile"]["source_details"]
            require(source_details["content_hash"] == digest and source_details["fdc_id"] == expected_id,
                    "Accepted source provenance changed")
            sql.close()
            sql = SqliteDatabase(database_path)
            scans, snapshots, confirmations, sources, previews, service = repositories()
            replay = previews.accept_preview(authenticated_user_id="replay-owner",
                                             preview_id="reviewed-preview", idempotency_key="accept-once")
            require(replay["replayed"] and replay["profile_hash"] == saved["profile_hash"], "Restart replay changed")
            denied("ownership_conflict", NutritionRepositoryError, lambda: sources.get_profile_for_user(
                "another-owner", saved["profile_id"]))
            sources.withdraw_source_policy(policy["source_spec"]["source_id"], expected_revision=0)
            denied("source_unavailable", FdcProfilePreviewRepositoryError, lambda: previews.accept_preview(
                authenticated_user_id="replay-owner", preview_id=pending["preview_id"], idempotency_key="after-withdrawal"))
            denied("source_unavailable", NutritionRepositoryError, lambda: sources.get_profile_for_user(
                "replay-owner", saved["profile_id"]))
            historical = sources.get_profile_for_user("replay-owner", saved["profile_id"], include_withdrawn=True)
            require(historical["profile_hash"] == saved["profile_hash"], "Withdrawal erased historical owner evidence")
            require(sql.query_one("SELECT COUNT(*) AS n FROM nutrition_profiles")["n"] == 1,
                    "Replay or withdrawal created another profile")
        finally:
            sql.close()

    return {"scope": "captured_real_fdc_replay_into_temporary_sqlite", "fdc_id": expected_id,
            "replayed_at": replayed_at,
            "retrieved_at": retrieved_at, "original_capture_envelope": "payload" in capture,
            "payload_sha256": digest, "policy_sha256": candidate["admission_review"]["policy_sha256"],
            "provider_mode": "offline replay; no new network retrieval", "detail_replay_count": len(detail_calls),
            "recognition": "synthetic explicit compatible identity, not image recognition",
            "recognition_identity": result["preview"]["recognition_identity"],
            "source_identity": result["preview"]["source_identity"],
            "identity_rejections": len(counterexamples), "reopen_count": 2,
            "profile_count": 1, "meal_records_written": 0,
            "per_100g": profile["per_100g"], "portion_150g": portion["values"],
            "profile_hash": saved["profile_hash"],
            "checks": {"preview_did_not_write_profile": True, "accept_after_reopen": True,
                       "idempotent_replay_after_second_reopen": True, "owner_only_profile": True,
                       "confirmation_did_not_rename_or_infer_variety": True,
                       "withdrawal_blocked_pending_accept_and_current_lookup": True,
                       "historical_owner_snapshot_retained": True},
            "limitations": ["No live model, USDA or Tavily calls; no credentials loaded",
                            "For a bare payload only, retrieval time is the replay time, not original capture time",
                            "SQLite close/reopen, not a process crash or mobile save test",
                            "Identity compatibility follows the selected policy, not candidate confirmation",
                            "No production DB, registry, feature flag or service changed"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--proof", type=Path)
    args = parser.parse_args()
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
        report = json.dumps(verify(args.payload, candidate_path=args.candidate, proof_path=args.proof),
                            ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")
