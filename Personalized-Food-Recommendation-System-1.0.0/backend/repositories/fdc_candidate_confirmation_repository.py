"""Persist authenticated user decisions for server-owned FDC snapshots.

This repository deliberately accepts a confirmation payload, not a snapshot.
It loads and validates the snapshot by authenticated user/scan/revision, then
persists only the normalized decision contract. A confirmed candidate remains
pending a new server-owned scan revision and never changes visual confidence.
"""

from copy import deepcopy
import hashlib
import json
import math
import secrets
import threading
import time

from repositories.sqlite_db import from_json, to_json, utc_iso
from repositories.scan_context_repository import ScanContextRepositoryError
from repositories.fdc_candidate_snapshot_repository import (
    FdcCandidateSnapshotRepositoryError,
)
from services.fooddata_central_selection_service import (
    FdcCandidateSelectionError,
    validate_fdc_candidate_confirmation,
)
from services.food_identity_service import requires_food_identity_confirmation


MAX_ID = 256
MAX_KEY = 128
MAX_PAYLOAD_BYTES = 128 * 1024

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_fdc_candidate_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    scan_revision INTEGER NOT NULL,
    item_set_digest TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    result_payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL,
    UNIQUE (user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_fdc_confirmations_snapshot
    ON nutrition_fdc_candidate_confirmations (user_id, scan_id, scan_revision, created_at);
"""


class FdcCandidateConfirmationRepositoryError(ValueError):
    """Typed confirmation persistence error."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FdcCandidateConfirmationRepositoryError(code, message)


def _identifier(value, field, maximum=MAX_ID):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("invalid_request", "scan_revision is invalid")
    return value


def _canonical(value):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise FdcCandidateConfirmationRepositoryError(
            "invalid_confirmation", "Confirmation must be finite canonical JSON") from error
    if len(encoded) > MAX_PAYLOAD_BYTES:
        _fail("oversized_request", "Confirmation exceeds its size budget")
    return encoded


def _items_from_snapshot(snapshot):
    return [
        {"item_id": item["item_id"], "item_revision": item["item_revision"],
         **deepcopy(item["recognition_identity"])}
        for item in snapshot["items"]
    ]


def _overall_status(items):
    statuses = {item["status"] for item in items}
    if "confirmed_pending_revision" in statuses:
        return "confirmed_pending_revision"
    if "confirmation_required" in statuses:
        return "confirmation_required"
    return "rejected"


class FdcCandidateConfirmationRepository:
    """Durable, idempotent confirmation records for SQLite deployments."""

    def __init__(self, sql, *, snapshot_repository, clock=time.time):
        if sql is None or getattr(sql, "dialect", None) != "sqlite":
            _fail("unsupported_database", "FDC confirmations require SQLite")
        if snapshot_repository is None or not hasattr(snapshot_repository, "get_snapshot"):
            _fail("storage_unavailable", "A server-owned FDC snapshot repository is required")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        self.sql = sql
        self.snapshot_repository = snapshot_repository
        self.scan_context_repository = getattr(snapshot_repository, "scan_context_repository", None)
        if self.scan_context_repository is None or not hasattr(
                self.scan_context_repository, "create_revision_in_transaction"):
            _fail("storage_unavailable", "A transactional scan context repository is required")
        self.clock = clock
        self._lock = threading.RLock()
        self.sql.executescript(SQLITE_TABLES)

    def _by_key(self, user_id, idempotency_key):
        row = self.sql.query_one(
            "SELECT confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id, "
            "scan_revision, item_set_digest, snapshot_digest, result_payload, created_at, expires_at "
            "FROM nutrition_fdc_candidate_confirmations WHERE user_id = ? AND idempotency_key = ?",
            (user_id, idempotency_key),
        )
        return self._document(row)

    def _document(self, row, *, replayed=False):
        if row is None:
            return None
        result = from_json(row["result_payload"])
        return {
            "confirmation_id": row["confirmation_id"],
            "user_id": row["user_id"], "actor_id": row["actor_id"],
            "idempotency_key": row["idempotency_key"], "scan_id": row["scan_id"],
            "scan_revision": int(row["scan_revision"]),
            "item_set_digest": row["item_set_digest"],
            "snapshot_digest": row["snapshot_digest"],
            # Confirmation remains pending the fixed Detail replay even after
            # the new scan revision is issued atomically.
            "status": _overall_status(result["items"]),
            "items": deepcopy(result["items"]),
            "requires_new_scan_revision": result["requires_new_scan_revision"],
            "issued_scan_revision": result.get("issued_scan_revision"),
            "requires_detail_replay": bool(result.get("requires_detail_replay")),
            "photo_confidence_changed": False,
            "created_at": row["created_at"], "expires_at": float(row["expires_at"]),
            "replayed": bool(replayed),
        }

    def record_confirmation(self, *, authenticated_user_id, actor_id, scan_id,
                            scan_revision, idempotency_key, confirmation):
        """Validate against a stored snapshot and persist an immutable decision.

        ``confirmation`` contains only the user decision envelope. It must not
        include a snapshot; the reference is resolved from authenticated server
        state using user, scan, revision and the digest in that envelope.
        """
        user_id = _identifier(authenticated_user_id, "user_id")
        actor_id = _identifier(actor_id, "actor_id")
        scan_id = _identifier(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        idempotency_key = _identifier(idempotency_key, "idempotency_key", MAX_KEY)
        if actor_id != user_id:
            _fail("wrong_actor", "Confirmation actor must match the authenticated user")
        if not isinstance(confirmation, (dict, str)):
            _fail("invalid_confirmation", "Confirmation payload is required")
        now = self.clock()
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            _fail("invalid_clock", "The confirmation clock is invalid")
        now = float(now)

        try:
            if isinstance(confirmation, str):
                decoded_confirmation = json.loads(confirmation)
            else:
                decoded_confirmation = confirmation
            request_hash = hashlib.sha256(_canonical(decoded_confirmation)).hexdigest()
        except (TypeError, ValueError, RecursionError, FdcCandidateConfirmationRepositoryError):
            # Invalid input still reaches the strict confirmation validator below;
            # this digest only lets an existing idempotency key fail closed.
            request_hash = hashlib.sha256(repr(confirmation).encode("utf-8", "replace")).hexdigest()
            decoded_confirmation = None
        requested_digest = (decoded_confirmation.get("snapshot_digest")
                            if isinstance(decoded_confirmation, dict) else None)

        with self._lock, self.sql.transaction():
            existing = self._by_key(user_id, idempotency_key)
            if existing is not None:
                row = self.sql.query_one(
                    "SELECT request_hash, actor_id, scan_id, scan_revision, snapshot_digest "
                    "FROM nutrition_fdc_candidate_confirmations WHERE user_id = ? AND idempotency_key = ?",
                    (user_id, idempotency_key),
                )
                if (row["request_hash"] != request_hash or row["actor_id"] != actor_id
                        or row["scan_id"] != scan_id or int(row["scan_revision"]) != scan_revision
                        or row["snapshot_digest"] != requested_digest):
                    _fail("idempotency_conflict", "The idempotency key was used for another confirmation")
                if now >= existing["expires_at"]:
                    _fail("expired", "The candidate confirmation has expired")
                existing["replayed"] = True
                return existing

            if isinstance(confirmation, dict):
                digest = confirmation.get("snapshot_digest")
            else:
                digest = (decoded_confirmation.get("snapshot_digest")
                          if isinstance(decoded_confirmation, dict) else None)
            try:
                stored = self.snapshot_repository.get_snapshot(
                    user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                    snapshot_digest=digest, include_inactive=False, now=now,
                )
            except FdcCandidateSnapshotRepositoryError as error:
                raise FdcCandidateConfirmationRepositoryError(error.code, str(error)) from error
            if stored is None:
                _fail("snapshot_unavailable", "The server-owned candidate snapshot is unavailable")
            if now >= stored["expires_at"]:
                _fail("expired", "The candidate confirmation has expired")
            snapshot = stored["snapshot"]
            expected_items = _items_from_snapshot(snapshot)
            try:
                source_context = self.scan_context_repository.get_scan_context(
                    user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                    include_inactive=False, now=now,
                )
            except ScanContextRepositoryError as error:
                raise FdcCandidateConfirmationRepositoryError(error.code, str(error)) from error
            if source_context is None:
                _fail("scan_unavailable", "The server-owned scan context is unavailable")
            try:
                normalized_items = validate_fdc_candidate_confirmation(
                    confirmation, snapshot=snapshot, expected_items=expected_items,
                    scan_revision=scan_revision,
                )
            except FdcCandidateSelectionError as error:
                raise FdcCandidateConfirmationRepositoryError(error.code, str(error)) from error

            prior_rows = self.sql.query_all(
                "SELECT result_payload FROM nutrition_fdc_candidate_confirmations "
                "WHERE user_id = ? AND scan_id = ? AND scan_revision = ? AND snapshot_digest = ?",
                (user_id, scan_id, scan_revision, stored["snapshot_digest"]),
            )
            for row in prior_rows:
                prior = from_json(row["result_payload"])
                if any(item["status"] in {"confirmed_pending_revision", "rejected"}
                       for item in prior["items"]):
                    _fail("confirmation_conflict", "This candidate snapshot already has a final decision")

            requires_new_revision = any(item["requires_new_scan_revision"]
                                        for item in normalized_items)
            issued_revision = None
            if requires_new_revision:
                try:
                    self.scan_context_repository.create_revision_in_transaction(
                        user_id=user_id, scan_id=scan_id, from_revision=scan_revision,
                        items=source_context["items"], issued_at=now, expires_at=now + 120,
                    )
                except ScanContextRepositoryError as error:
                    raise FdcCandidateConfirmationRepositoryError(error.code, str(error)) from error
                issued_revision = scan_revision + 1
            result = {
                "items": normalized_items,
                # Historical clients use this as the confirmation contract:
                # the choice required a fresh revision. ``issued_scan_revision``
                # tells newer clients that the transaction already completed.
                "requires_new_scan_revision": requires_new_revision,
                "issued_scan_revision": issued_revision,
                "requires_detail_replay": requires_new_revision,
            }
            created_at = utc_iso()
            expiry = float(stored["expires_at"])
            confirmation_id = secrets.token_urlsafe(18)
            self.sql.execute(
                "INSERT INTO nutrition_fdc_candidate_confirmations "
                "(confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id, "
                "scan_revision, item_set_digest, snapshot_digest, result_payload, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id,
                 scan_revision, stored["item_set_digest"], stored["snapshot_digest"],
                 to_json(result), created_at, expiry),
            )
            row = self.sql.query_one(
                "SELECT confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id, "
                "scan_revision, item_set_digest, snapshot_digest, result_payload, created_at, expires_at "
                "FROM nutrition_fdc_candidate_confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            )
            return self._document(row)

    def get_confirmation(self, *, authenticated_user_id, confirmation_id,
                         scan_id=None, issued_scan_revision=None, now=None):
        """Load a server-owned confirmation for a later fixed-detail replay.

        The detail route must use this read boundary instead of accepting a
        client-supplied FDC ID. Only confirmations that issued a new revision
        and still have at least one confirmed item are eligible.
        """
        user_id = _identifier(authenticated_user_id, "user_id")
        confirmation_id = _identifier(confirmation_id, "confirmation_id")
        if scan_id is not None:
            scan_id = _identifier(scan_id, "scan_id")
        if issued_scan_revision is not None:
            issued_scan_revision = _revision(issued_scan_revision)
        current = self.clock() if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
            _fail("invalid_clock", "The confirmation clock is invalid")
        row = self.sql.query_one(
            "SELECT confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id, "
            "scan_revision, item_set_digest, snapshot_digest, result_payload, created_at, expires_at "
            "FROM nutrition_fdc_candidate_confirmations WHERE confirmation_id = ? AND user_id = ?",
            (confirmation_id, user_id),
        )
        if row is None:
            return None
        if scan_id is not None and row["scan_id"] != scan_id:
            _fail("wrong_confirmation", "Confirmation does not belong to this scan")
        result = from_json(row["result_payload"])
        issued = result.get("issued_scan_revision")
        if issued is None or (issued_scan_revision is not None and int(issued) != issued_scan_revision):
            _fail("revision_conflict", "Confirmation is not bound to the requested issued revision")
        if float(current) >= float(row["expires_at"]):
            _fail("expired", "The confirmation has expired")
        try:
            issued_context = self.scan_context_repository.get_scan_context(
                user_id=user_id, scan_id=row["scan_id"], scan_revision=int(issued),
                include_inactive=False, now=float(current),
            )
        except ScanContextRepositoryError as error:
            raise FdcCandidateConfirmationRepositoryError(error.code, str(error)) from error
        if issued_context is None:
            _fail("stale_revision", "The issued scan revision is no longer active")
        items = [item for item in result.get("items", [])
                 if item.get("status") == "confirmed_pending_revision"
                 and isinstance(item.get("confirmed_fdc_id"), str)
                 and item["confirmed_fdc_id"]]
        if not items:
            _fail("confirmation_required", "Confirmation has no confirmed FDC candidate")
        # Old issued confirmations may predate the generic-name gate. Keep
        # their evidence intact, but never treat them as detail authority.
        for confirmed in items:
            matches = [item for item in issued_context["items"]
                       if item.get("item_id") == confirmed.get("item_id")]
            if len(matches) != 1 or requires_food_identity_confirmation(matches[0].get("name_zh")):
                _fail("confirmation_required", "The issued scan requires a specific food identity before FDC detail retrieval")
        document = self._document(row)
        document["issued_scan_revision"] = int(issued)
        document["confirmed_items"] = deepcopy(items)
        return document


__all__ = ["FdcCandidateConfirmationRepository", "FdcCandidateConfirmationRepositoryError", "SQLITE_TABLES"]
