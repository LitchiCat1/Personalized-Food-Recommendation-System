"""Persist authenticated food-name decisions with an atomic scan revision."""

from copy import deepcopy
import hashlib
import json
import math
import secrets
import threading
import time

from repositories.scan_context_repository import ScanContextRepositoryError
from repositories.sqlite_db import from_json, to_json, utc_iso
from services.food_identity_service import (
    identity_attributes_are_known,
    requires_food_identity_confirmation,
)


MAX_ID = 256
MAX_KEY = 128
MAX_NAME = 120
DEFAULT_REVISION_TTL_SECONDS = 120

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_identity_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    source_scan_revision INTEGER NOT NULL,
    issued_scan_revision INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    source_item_revision INTEGER NOT NULL,
    issued_item_revision INTEGER NOT NULL,
    original_name TEXT NOT NULL,
    confirmed_name TEXT NOT NULL,
    source_item_set_hash TEXT NOT NULL,
    issued_item_set_hash TEXT NOT NULL,
    result_payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL,
    UNIQUE (user_id, idempotency_key),
    FOREIGN KEY (scan_id, issued_scan_revision)
        REFERENCES nutrition_scan_contexts (scan_id, scan_revision)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_identity_confirmations_scan
    ON nutrition_identity_confirmations (user_id, scan_id, source_scan_revision, item_id);
"""


class NutritionIdentityConfirmationError(ValueError):
    """Stable identity-confirmation boundary error."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise NutritionIdentityConfirmationError(code, message)


def _identifier(value, field, maximum=MAX_ID):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _revision(value, field):
    if type(value) is not int or value < 0:
        _fail("invalid_request", f"{field} is invalid")
    return value


def _canonical(value):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise NutritionIdentityConfirmationError(
            "invalid_request", "Identity decision must be finite JSON") from error
    if len(encoded) > 16 * 1024:
        _fail("oversized_request", "Identity decision exceeds its size budget")
    return encoded


class NutritionIdentityConfirmationRepository:
    """Owner-bound identity decisions; never treats HTTP flags as confirmation."""

    def __init__(self, sql, *, scan_context_repository,
                 clock=time.time, revision_ttl_seconds=DEFAULT_REVISION_TTL_SECONDS):
        if sql is None or getattr(sql, "dialect", None) != "sqlite":
            _fail("unsupported_database", "Identity confirmation requires SQLite")
        if (scan_context_repository is None
                or not hasattr(scan_context_repository, "create_identity_revision_in_transaction")):
            _fail("storage_unavailable", "A transactional scan context repository is required")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        if (isinstance(revision_ttl_seconds, bool)
                or not isinstance(revision_ttl_seconds, (int, float))
                or not math.isfinite(revision_ttl_seconds)
                or revision_ttl_seconds <= 0 or revision_ttl_seconds > 15 * 60):
            _fail("invalid_expiry", "revision_ttl_seconds is invalid")
        self.sql = sql
        self.scan_context_repository = scan_context_repository
        self.clock = clock
        self.revision_ttl_seconds = float(revision_ttl_seconds)
        self._lock = threading.RLock()
        self.sql.executescript(SQLITE_TABLES)

    def _by_key(self, user_id, idempotency_key):
        row = self.sql.query_one(
            "SELECT confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id, "
            "source_scan_revision, issued_scan_revision, item_id, source_item_revision, "
            "issued_item_revision, original_name, confirmed_name, source_item_set_hash, "
            "issued_item_set_hash, result_payload, created_at, expires_at "
            "FROM nutrition_identity_confirmations WHERE user_id = ? AND idempotency_key = ?",
            (user_id, idempotency_key),
        )
        return self._document(row)

    @staticmethod
    def _document(row, *, replayed=False):
        if row is None:
            return None
        return {
            "confirmation_id": row["confirmation_id"],
            "user_id": row["user_id"], "actor_id": row["actor_id"],
            "idempotency_key": row["idempotency_key"], "scan_id": row["scan_id"],
            "request_hash": row["request_hash"],
            "source_scan_revision": int(row["source_scan_revision"]),
            "issued_scan_revision": int(row["issued_scan_revision"]),
            "item_id": row["item_id"],
            "source_item_revision": int(row["source_item_revision"]),
            "issued_item_revision": int(row["issued_item_revision"]),
            "original_name": row["original_name"], "confirmed_name": row["confirmed_name"],
            "source_item_set_hash": row["source_item_set_hash"],
            "issued_item_set_hash": row["issued_item_set_hash"],
            "result": deepcopy(from_json(row["result_payload"])),
            "created_at": row["created_at"], "expires_at": float(row["expires_at"]),
            "replayed": bool(replayed),
        }

    def confirm_item_name(self, *, authenticated_user_id, actor_id, scan_id,
                          scan_revision, item_id, item_revision, confirmed_name,
                          idempotency_key):
        user_id = _identifier(authenticated_user_id, "user_id")
        actor_id = _identifier(actor_id, "actor_id")
        scan_id = _identifier(scan_id, "scan_id")
        item_id = _identifier(item_id, "item_id")
        scan_revision = _revision(scan_revision, "scan_revision")
        item_revision = _revision(item_revision, "item_revision")
        idempotency_key = _identifier(idempotency_key, "idempotency_key", MAX_KEY)
        if actor_id != user_id:
            _fail("wrong_actor", "Identity decision actor must match the authenticated user")
        if (not isinstance(confirmed_name, str) or not confirmed_name
                or len(confirmed_name) > MAX_NAME or confirmed_name.strip() != confirmed_name
                or requires_food_identity_confirmation(confirmed_name)):
            _fail("invalid_identity", "Enter a specific, unambiguous food name")

        request = {"scan_id": scan_id, "scan_revision": scan_revision,
                   "item_id": item_id, "item_revision": item_revision,
                   "confirmed_name": confirmed_name}
        request_hash = hashlib.sha256(_canonical(request)).hexdigest()
        now = self.clock()
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            _fail("invalid_clock", "The identity confirmation clock is invalid")
        now = float(now)
        confirmation_id = secrets.token_urlsafe(18)

        with self._lock, self.sql.transaction():
            existing = self._by_key(user_id, idempotency_key)
            if existing is not None:
                if (existing["request_hash"] != request_hash or existing["actor_id"] != actor_id
                        or existing["scan_id"] != scan_id
                        or existing["source_scan_revision"] != scan_revision
                        or existing["item_id"] != item_id
                        or existing["source_item_revision"] != item_revision):
                    _fail("idempotency_conflict", "The idempotency key was used for another identity decision")
                existing["replayed"] = True
                return existing

            try:
                source = self.scan_context_repository.get_scan_context(
                    user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                    include_inactive=False, now=now)
            except ScanContextRepositoryError as error:
                raise NutritionIdentityConfirmationError(error.code, str(error)) from error
            if source is None:
                try:
                    historical = self.scan_context_repository.get_scan_context(
                        user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                        include_inactive=True, now=now)
                except ScanContextRepositoryError as error:
                    raise NutritionIdentityConfirmationError(error.code, str(error)) from error
                if historical is not None and historical["status"] == "superseded":
                    _fail("stale_revision", "The scan context is no longer current")
                if historical is not None and historical["status"] == "expired":
                    _fail("expired", "The scan context has expired")
                _fail("scan_unavailable", "The current scan context is unavailable")
            source_item = next((item for item in source["items"] if item["item_id"] == item_id), None)
            if source_item is None:
                _fail("item_not_found", "The scan item is unavailable")
            if source_item["item_revision"] != item_revision:
                _fail("stale_revision", "The scan item revision is no longer current")
            if source_item.get("identity_confirmation_required") is not True:
                _fail("identity_confirmation_not_required", "This item is not awaiting identity confirmation")
            if source_item.get("validation_issues"):
                _fail("identity_context_incomplete", "The scan has unresolved recognition data")
            if not identity_attributes_are_known(source_item):
                _fail("identity_context_incomplete", "Confirm food state and preparation before its name")

            decision = "confirm" if confirmed_name == source_item["name_zh"] else "correct"
            expires_at = now + self.revision_ttl_seconds
            try:
                issued = self.scan_context_repository.create_identity_revision_in_transaction(
                    user_id=user_id, scan_id=scan_id, from_revision=scan_revision,
                    item_id=item_id, item_revision=item_revision,
                    confirmed_name=confirmed_name, confirmation_id=confirmation_id,
                    issued_at=now, expires_at=expires_at,
                )
            except ScanContextRepositoryError as error:
                raise NutritionIdentityConfirmationError(error.code, str(error)) from error
            issued_item = next(item for item in issued["items"] if item["item_id"] == item_id)
            result = {
                "status": "confirmed", "decision": decision,
                "scan_id": scan_id, "source_scan_revision": scan_revision,
                "issued_scan_revision": issued["scan_revision"],
                "item_id": item_id, "source_item_revision": item_revision,
                "issued_item_revision": issued_item["item_revision"],
                "name_zh": issued_item["name_zh"],
                "identity_confirmation_required": issued_item["identity_confirmation_required"],
                "identity_confirmation_source": issued_item["identity_confirmation_source"],
                "identity_confirmation_id": issued_item["identity_confirmation_id"],
                "expires_at": issued["expires_at"],
            }
            created_at = utc_iso()
            self.sql.execute(
                "INSERT INTO nutrition_identity_confirmations "
                "(confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id, "
                "source_scan_revision, issued_scan_revision, item_id, source_item_revision, "
                "issued_item_revision, original_name, confirmed_name, source_item_set_hash, "
                "issued_item_set_hash, result_payload, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id,
                 scan_revision, issued["scan_revision"], item_id, item_revision,
                 issued_item["item_revision"], source_item["name_zh"], confirmed_name,
                 source["item_set_hash"], issued["item_set_hash"], to_json(result), created_at,
                 float(issued["expires_at"])),
            )
            row = self.sql.query_one(
                "SELECT confirmation_id, user_id, actor_id, idempotency_key, request_hash, scan_id, "
                "source_scan_revision, issued_scan_revision, item_id, source_item_revision, "
                "issued_item_revision, original_name, confirmed_name, source_item_set_hash, "
                "issued_item_set_hash, result_payload, created_at, expires_at "
                "FROM nutrition_identity_confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            )
            return self._document(row)


__all__ = ["NutritionIdentityConfirmationError", "NutritionIdentityConfirmationRepository"]
