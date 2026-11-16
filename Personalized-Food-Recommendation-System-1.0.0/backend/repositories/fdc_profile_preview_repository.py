"""Durable server-owned FDC profile previews and atomic acceptance.

The preview is an immutable, short-lived capability.  It stores the exact
server-generated profile and every authorization binding needed to accept it;
the accept path rechecks those bindings and writes ``nutrition_profiles`` plus
the consumed marker in one SQLite transaction.  No client-supplied FDC ID,
weight, policy, or profile is accepted by this boundary.
"""

from copy import deepcopy
import hashlib
import json
import math
import secrets
import threading
import time

from repositories.sqlite_db import from_json, to_json, utc_iso
from repositories.nutrition_profile_repository import (
    NutritionProfileSourceRepository, NutritionRepositoryError, profile_hash,
    _canonical, _bounded_id, _identity, _revision, _profile,
)
from services.fdc_source_policy_service import FdcSourcePolicyError, validate_fdc_source_policy
from services.food_identity_service import requires_food_identity_confirmation


MAX_ID = 256
MAX_KEY = 128
MAX_PREVIEW_BYTES = 768 * 1024
MAX_RESULT_BYTES = 256 * 1024
_HASH = set("0123456789abcdef")


class FdcProfilePreviewRepositoryError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FdcProfilePreviewRepositoryError(code, message)


def _id(value, field, maximum=MAX_ID):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _digest(value, field):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in _HASH for c in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _revision_value(value, field):
    if type(value) is not int or value < 0:
        _fail("invalid_request", f"{field} is invalid")
    return value


def _clock(clock):
    value = clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_clock", "The preview clock is invalid")
    return float(value)


SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_fdc_profile_previews (
    preview_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    confirmation_id TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    issued_scan_revision INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    item_revision INTEGER NOT NULL,
    snapshot_digest TEXT NOT NULL,
    source_policy_id TEXT NOT NULL,
    source_policy_revision INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    fdc_id TEXT NOT NULL,
    detail_content_hash TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    weight_g REAL NOT NULL,
    food_identity TEXT NOT NULL,
    profile TEXT NOT NULL,
    portion TEXT NOT NULL,
    source_block TEXT NOT NULL,
    recognition_identity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL,
    accepted_idempotency_key TEXT,
    accepted_result TEXT,
    accepted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_nutrition_fdc_previews_user
    ON nutrition_fdc_profile_previews (user_id, status, expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nutrition_fdc_previews_profile_id
    ON nutrition_fdc_profile_previews (profile_id);
"""


class FdcProfilePreviewRepository:
    """SQLite-only persistence and one-transaction preview acceptance."""

    def __init__(self, sql, *, confirmation_repository=None,
                 scan_context_repository=None, source_repository=None,
                 profile_repository=None, clock=time.time):
        if sql is None or getattr(sql, "dialect", None) != "sqlite":
            _fail("unsupported_database", "FDC profile previews require SQLite")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        self.sql = sql
        self.clock = clock
        self.confirmation_repository = confirmation_repository
        self.scan_context_repository = scan_context_repository
        self.source_repository = source_repository
        self.profile_repository = profile_repository or NutritionProfileSourceRepository(sql)
        self._lock = threading.RLock()
        self.sql.executescript(SQLITE_TABLES)

    def _row(self, preview_id):
        return self.sql.query_one(
            "SELECT * FROM nutrition_fdc_profile_previews WHERE preview_id = ?",
            (preview_id,))

    @staticmethod
    def _document(row):
        if row is None:
            return None
        return {
            "preview_id": row["preview_id"], "user_id": row["user_id"],
            "confirmation_id": row["confirmation_id"], "scan_id": row["scan_id"],
            "issued_scan_revision": int(row["issued_scan_revision"]),
            "item_id": row["item_id"], "item_revision": int(row["item_revision"]),
            "snapshot_digest": row["snapshot_digest"],
            "source_policy_id": row["source_policy_id"],
            "source_policy_revision": int(row["source_policy_revision"]),
            "source_id": row["source_id"], "fdc_id": row["fdc_id"],
            "detail_content_hash": row["detail_content_hash"],
            "profile_hash": row["profile_hash"], "profile_id": row["profile_id"],
            "weight_g": float(row["weight_g"]),
            "food_identity": from_json(row["food_identity"]),
            "profile": from_json(row["profile"]), "portion": from_json(row["portion"]),
            "source_block": from_json(row["source_block"]),
            "recognition_identity": from_json(row["recognition_identity"]),
            "created_at": row["created_at"], "expires_at": float(row["expires_at"]),
            "status": row["status"],
            "accepted_idempotency_key": row["accepted_idempotency_key"],
            "accepted_result": (from_json(row["accepted_result"])
                                 if row["accepted_result"] else None),
            "accepted_at": row["accepted_at"],
        }

    def _normalize_preview(self, preview):
        if not isinstance(preview, dict) or preview.get("status") != "preview":
            _fail("invalid_preview", "A server-owned preview is required")
        for field in ("user_id", "confirmation_id", "scan_id", "item_id", "source_id",
                      "source_policy_id", "fdc_id"):
            _id(preview.get(field), field)
        for field in ("issued_scan_revision", "item_revision", "source_policy_revision"):
            _revision_value(preview.get(field), field)
        _digest(preview.get("snapshot_digest"), "snapshot_digest")
        result = preview.get("preview")
        if not isinstance(result, dict):
            _fail("invalid_preview", "Preview payload is missing")
        profile = result.get("nutrition_profile")
        portion = result.get("portion")
        source_block = result.get("source_block")
        recognition = result.get("recognition_identity")
        source_identity = result.get("source_identity")
        if not all(isinstance(value, dict) for value in (profile, portion, source_block, recognition, source_identity)):
            _fail("invalid_preview", "Preview payload is incomplete")
        try:
            checked_profile = _profile(profile)
            digest = profile_hash(checked_profile)
            identity = _identity(source_identity)
        except NutritionRepositoryError as error:
            _fail(error.code, str(error))
        if digest != profile.get("profile_hash", digest):
            _fail("profile_conflict", "Preview profile hash is inconsistent")
        details = checked_profile.get("source_details")
        if not isinstance(details, dict):
            _fail("invalid_provenance", "Preview profile provenance is required")
        detail_hash = source_block.get("content_hash")
        _digest(detail_hash, "detail_content_hash")
        if details.get("content_hash") != detail_hash:
            _fail("source_conflict", "Preview detail and profile content hashes differ")
        if details.get("source_id") != preview["source_id"] or details.get("fdc_id") != preview["fdc_id"]:
            _fail("source_conflict", "Preview profile source binding differs")
        if details.get("provider_kind") != "usda_fdc_api":
            _fail("source_conflict", "Preview must be an FDC profile")
        weight = preview.get("weight_g")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
            _fail("invalid_portion", "Preview weight is invalid")
        expected_identity = source_block.get("source_identity")
        if expected_identity is not None and expected_identity != identity:
            _fail("identity_mismatch", "Preview source identity is inconsistent")
        encoded = _canonical({"profile": checked_profile, "portion": portion,
                              "source_block": source_block,
                              "recognition_identity": recognition,
                              "food_identity": identity}, limit=MAX_PREVIEW_BYTES)
        if len(encoded) > MAX_PREVIEW_BYTES:
            _fail("oversized_preview", "Preview exceeds its size budget")
        return {
            "user_id": preview["user_id"], "confirmation_id": preview["confirmation_id"],
            "scan_id": preview["scan_id"], "issued_scan_revision": preview["issued_scan_revision"],
            "item_id": preview["item_id"], "item_revision": preview["item_revision"],
            "snapshot_digest": preview["snapshot_digest"],
            "source_policy_id": preview["source_policy_id"],
            "source_policy_revision": preview["source_policy_revision"],
            "source_id": preview["source_id"], "fdc_id": preview["fdc_id"],
            "detail_content_hash": detail_hash, "profile_hash": digest,
            "food_identity": identity, "profile": checked_profile,
            "portion": deepcopy(portion), "source_block": deepcopy(source_block),
            "recognition_identity": deepcopy(recognition), "weight_g": float(weight),
        }

    def save_preview(self, preview, *, preview_id=None, profile_id=None,
                     expires_at=None, ttl_seconds=120):
        """Persist a coordinator-generated preview; never accepts provider input."""
        checked = self._normalize_preview(preview)
        preview_id = secrets.token_urlsafe(18) if preview_id is None else _id(preview_id, "preview_id")
        profile_id = ("fdc-preview-" + preview_id) if profile_id is None else _id(profile_id, "profile_id")
        now = _clock(self.clock)
        if expires_at is None:
            if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
                    or not math.isfinite(ttl_seconds) or ttl_seconds <= 0 or ttl_seconds > 15 * 60):
                _fail("invalid_expiry", "ttl_seconds is invalid")
            expires_at = now + float(ttl_seconds)
        if (isinstance(expires_at, bool) or not isinstance(expires_at, (int, float))
                or not math.isfinite(expires_at) or expires_at <= now):
            _fail("invalid_expiry", "expires_at is invalid")
        now_text = utc_iso()
        with self._lock, self.sql.transaction():
            existing = self._row(preview_id)
            if existing:
                document = self._document(existing)
                if document["user_id"] != checked["user_id"]:
                    _fail("ownership_conflict", "Preview belongs to another user")
                bindings = (
                    "confirmation_id", "scan_id", "issued_scan_revision", "item_id",
                    "item_revision", "snapshot_digest", "source_policy_id",
                    "source_policy_revision", "source_id", "fdc_id",
                    "detail_content_hash", "profile_hash", "profile_id", "weight_g",
                )
                expected = dict(checked, profile_id=profile_id)
                if any(document[field] != expected[field] for field in bindings):
                    _fail("idempotency_conflict", "Preview ID is already bound to another preview")
                for field in ("food_identity", "profile", "portion", "source_block", "recognition_identity"):
                    if document[field] != checked[field]:
                        _fail("idempotency_conflict", "Preview ID is already bound to another payload")
                return document
            try:
                self.sql.execute(
                    "INSERT INTO nutrition_fdc_profile_previews "
                    "(preview_id, user_id, confirmation_id, scan_id, issued_scan_revision, item_id, item_revision, "
                    "snapshot_digest, source_policy_id, source_policy_revision, source_id, fdc_id, detail_content_hash, "
                    "profile_hash, profile_id, weight_g, food_identity, profile, portion, source_block, recognition_identity, "
                    "created_at, expires_at, status, accepted_idempotency_key, accepted_result, accepted_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (preview_id, checked["user_id"], checked["confirmation_id"], checked["scan_id"],
                     checked["issued_scan_revision"], checked["item_id"], checked["item_revision"],
                     checked["snapshot_digest"], checked["source_policy_id"], checked["source_policy_revision"],
                     checked["source_id"], checked["fdc_id"], checked["detail_content_hash"], checked["profile_hash"],
                     profile_id, checked["weight_g"], to_json(checked["food_identity"]), to_json(checked["profile"]),
                     to_json(checked["portion"]), to_json(checked["source_block"]), to_json(checked["recognition_identity"]),
                     now_text, float(expires_at), "active", None, None, None),)
            except Exception as error:
                if getattr(error, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_UNIQUE":
                    _fail("idempotency_conflict", "Preview ID or profile ID is already in use")
                raise
            return self._document(self._row(preview_id))

    def get_preview(self, *, authenticated_user_id, preview_id, include_consumed=False):
        user_id = _id(authenticated_user_id, "user_id")
        preview_id = _id(preview_id, "preview_id")
        row = self._row(preview_id)
        document = self._document(row)
        if document is None:
            return None
        if document["user_id"] != user_id:
            _fail("ownership_conflict", "Preview belongs to another user")
        if not include_consumed and document["status"] != "active":
            return None
        return document

    def _load_current_bindings(self, row, now):
        """Read confirmation/context/policy directly on the active transaction."""
        confirmation = self.sql.query_one(
            "SELECT confirmation_id, user_id, scan_id, scan_revision, snapshot_digest, result_payload, expires_at "
            "FROM nutrition_fdc_candidate_confirmations WHERE confirmation_id = ? AND user_id = ?",
            (row["confirmation_id"], row["user_id"]))
        if not confirmation:
            _fail("confirmation_required", "Confirmation is unavailable")
        if float(now) >= float(confirmation["expires_at"]):
            _fail("expired", "Confirmation has expired")
        if confirmation["scan_id"] != row["scan_id"] or confirmation["snapshot_digest"] != row["snapshot_digest"]:
            _fail("authorization_changed", "Confirmation binding changed")
        snapshot = self.sql.query_one(
            "SELECT user_id, scan_id, snapshot_digest, status, expires_at "
            "FROM nutrition_fdc_candidate_snapshots WHERE user_id = ? AND snapshot_digest = ?",
            (row["user_id"], row["snapshot_digest"]))
        if (not snapshot or snapshot["scan_id"] != row["scan_id"]
                or snapshot["status"] != "active" or float(now) >= float(snapshot["expires_at"])):
            _fail("stale_snapshot", "The FDC candidate snapshot is no longer active")
        result = from_json(confirmation["result_payload"])
        issued = result.get("issued_scan_revision") if isinstance(result, dict) else None
        if issued != int(row["issued_scan_revision"]):
            _fail("revision_conflict", "Issued scan revision changed")
        matches = [item for item in result.get("items", []) if isinstance(item, dict)
                   and item.get("item_id") == row["item_id"]
                   and item.get("status") == "confirmed_pending_revision"]
        if len(matches) != 1 or str(matches[0].get("confirmed_fdc_id")) != row["fdc_id"]:
            _fail("confirmation_required", "Confirmed FDC item changed")
        if matches[0].get("item_revision") != int(row["item_revision"]):
            _fail("revision_conflict", "Confirmed item revision changed")

        context = self.sql.query_one(
            "SELECT user_id, scan_id, scan_revision, item_set_hash, items, expires_at, status "
            "FROM nutrition_scan_contexts WHERE scan_id = ? AND scan_revision = ?",
            (row["scan_id"], row["issued_scan_revision"]))
        if not context or context["user_id"] != row["user_id"] or context["status"] != "active":
            _fail("stale_revision", "Issued scan context is no longer active")
        if float(now) >= float(context["expires_at"]):
            _fail("expired", "Issued scan context has expired")
        items = from_json(context["items"])
        scan_items = [item for item in items if isinstance(item, dict) and item.get("item_id") == row["item_id"]]
        if len(scan_items) != 1 or scan_items[0].get("item_revision") != int(row["item_revision"]):
            _fail("revision_conflict", "Scan item revision changed")
        weight = scan_items[0].get("estimated_weight_g")
        if (isinstance(weight, bool) or not isinstance(weight, (int, float))
                or not math.isfinite(weight) or float(weight) != float(row["weight_g"])):
            _fail("authorization_changed", "Scan portion changed")
        recognition = from_json(row["recognition_identity"])
        current_recognition = {
            "name_zh": scan_items[0].get("name_zh"),
            "food_state": scan_items[0].get("food_state"),
            "preparation_method": scan_items[0].get("preparation_method"),
            "components_scope": scan_items[0].get("components_scope"),
            "brand": scan_items[0].get("brand"),
            "variant": scan_items[0].get("variant"),
        }
        if recognition != current_recognition:
            _fail("authorization_changed", "Scan food identity changed")
        if requires_food_identity_confirmation(current_recognition.get("name_zh")):
            _fail("confirmation_required", "A specific food identity is required before accepting an FDC preview")

        source = self.sql.query_one(
            "SELECT source_id, policy_id, policy_revision, status, policy FROM nutrition_source_policies WHERE source_id = ?",
            (row["source_id"],))
        if not source or source["status"] != "active":
            _fail("source_unavailable", "FDC source policy is unavailable")
        if source["policy_id"] != row["source_policy_id"] or int(source["policy_revision"]) != int(row["source_policy_revision"]):
            _fail("revision_conflict", "FDC source policy revision changed")
        try:
            policy = validate_fdc_source_policy(from_json(source["policy"]))
        except FdcSourcePolicyError as error:
            _fail(error.code, str(error))
        spec = policy["source_spec"]
        if (spec.get("fdc_id") != row["fdc_id"] or spec.get("source_id") != row["source_id"]
                or not policy.get("rights", {}).get("snapshot_allowed")):
            _fail("source_conflict", "FDC source policy does not match preview")
        return confirmation, context, source, policy, scan_items[0]

    def accept_preview(self, *, authenticated_user_id, preview_id, idempotency_key):
        user_id = _id(authenticated_user_id, "user_id")
        preview_id = _id(preview_id, "preview_id")
        idempotency_key = _id(idempotency_key, "idempotency_key", MAX_KEY)
        now = _clock(self.clock)
        with self._lock, self.sql.transaction():
            row = self._row(preview_id)
            if not row:
                _fail("preview_not_found", "Preview is unavailable")
            if row["user_id"] != user_id:
                _fail("ownership_conflict", "Preview belongs to another user")
            status = row["status"]
            if status == "accepted":
                if row["accepted_idempotency_key"] != idempotency_key:
                    _fail("idempotency_conflict", "Preview was accepted with another idempotency key")
                result = from_json(row["accepted_result"])
                result = deepcopy(result)
                result["replayed"] = True
                return result
            if status != "active":
                _fail("preview_unavailable", "Preview is no longer active")
            if now >= float(row["expires_at"]):
                _fail("expired", "Preview has expired")
            self._load_current_bindings(row, now)
            profile = from_json(row["profile"])
            identity = from_json(row["food_identity"])
            if profile_hash(profile) != row["profile_hash"]:
                _fail("profile_conflict", "Persisted preview profile hash is invalid")
            # A new preview owns a new profile id.  Existing rows are a CAS
            # conflict rather than an overwrite of another profile revision.
            existing = self.profile_repository._profile_row(row["profile_id"])
            if existing is not None:
                _fail("revision_conflict", "Target profile already exists")
            try:
                saved = self.profile_repository._save_profile_in_transaction(
                    profile_id=row["profile_id"], user_id=user_id, checked_profile=profile,
                    identity=identity, source_id=row["source_id"],
                    source_policy_revision=int(row["source_policy_revision"]), reusable=False,
                    expected_revision=0, digest=row["profile_hash"], now=utc_iso())
            except NutritionRepositoryError as error:
                raise FdcProfilePreviewRepositoryError(error.code, str(error)) from error
            result = {"status": "accepted", "preview_id": preview_id,
                      "profile": deepcopy(saved), "portion": from_json(row["portion"]),
                      "profile_hash": row["profile_hash"], "replayed": False}
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > MAX_RESULT_BYTES:
                _fail("oversized_result", "Acceptance result exceeds its size budget")
            updated = self.sql.execute(
                "UPDATE nutrition_fdc_profile_previews SET status = ?, accepted_idempotency_key = ?, "
                "accepted_result = ?, accepted_at = ? WHERE preview_id = ? AND status = ?",
                ("accepted", idempotency_key, to_json(result), utc_iso(), preview_id, "active"))
            if updated != 1:
                _fail("preview_conflict", "Preview could not be consumed")
            return result


__all__ = ["FdcProfilePreviewRepository", "FdcProfilePreviewRepositoryError", "SQLITE_TABLES"]
