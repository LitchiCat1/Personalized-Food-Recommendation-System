"""Durable idempotency and single-flight state for nutrition enrichment.

This repository is intentionally independent of the HTTP route and provider
clients.  It persists the request identity, the canonical request payload,
lease ownership and the provider result.  A route can therefore survive a
process restart without turning a retry into a second provider call.

SQLite is the only durable SQL backend. ``sql=None`` is an explicit in-memory
mode for unit tests only; it must not be used by a production enrichment route.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import secrets
import threading
import time

from repositories.sqlite_db import from_json, to_json, utc_iso


MAX_ID = 256
MAX_FINGERPRINT = 64
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESULT_BYTES = 768 * 1024
MAX_ERROR_BYTES = 16 * 1024
_HEX = frozenset("0123456789abcdef")
_RETRYABLE = frozenset({"timeout", "rate_limited", "upstream_error", "busy", "not_found"})
_TERMINAL = frozenset({"accepted", "partial", "complete", "success", "invalid_output", "source_conflict"})
_STATUSES = _RETRYABLE | _TERMINAL


class NutritionEnrichmentRepositoryError(ValueError):
    """Typed repository error which a future route can map to HTTP."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_enrichment_requests (
    request_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    request_revision INTEGER,
    request_payload TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_payload TEXT,
    error_payload TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_enrichment_requests_user
    ON nutrition_enrichment_requests (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_nutrition_enrichment_requests_lease
    ON nutrition_enrichment_requests (status, lease_expires_at);
"""


def _fail(code, message):
    raise NutritionEnrichmentRepositoryError(code, message)


def _text(value, field, maximum=MAX_ID):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _revision(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        _fail("invalid_request", "request_revision is invalid")
    return value


def _fingerprint(value):
    if (not isinstance(value, str) or len(value) != MAX_FINGERPRINT
            or any(character not in _HEX for character in value)):
        _fail("invalid_request", "fingerprint is invalid")
    return value


def _json_bytes(value, *, limit, field):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise NutritionEnrichmentRepositoryError("invalid_request", f"{field} must be finite JSON") from error
    if len(encoded) > limit:
        _fail("oversized_request", f"{field} exceeds the repository size budget")
    return encoded


def request_hash(payload):
    """Return the server-side canonical hash of a request payload."""
    return hashlib.sha256(_json_bytes(payload, limit=MAX_REQUEST_BYTES,
                                      field="request_payload")).hexdigest()


def _now_seconds(clock):
    value = clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_clock", "The repository clock is invalid")
    return float(value)


def _iso_from_seconds(value):
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _row_json(row, field):
    return from_json(row[field]) if row and row.get(field) is not None else None


class NutritionEnrichmentOutcome:
    def __init__(self, status, result=None, *, error=None, request=None):
        self.status = status
        self.result = deepcopy(result)
        self.error = deepcopy(error)
        self.request = deepcopy(request)


class NutritionEnrichmentLease:
    """A durable owner/follower handle returned by :meth:`begin`."""

    def __init__(self, repository, document, *, owner, lease_owner=None):
        self._repository = repository
        self.request_id = document["request_id"]
        self.user_id = document["user_id"]
        self.idempotency_key = document["idempotency_key"]
        self.fingerprint = document["fingerprint"]
        self.owner = bool(owner)
        self.lease_owner = lease_owner
        self._initial_status = document["status"]

    @property
    def replay(self):
        return not self.owner and self._initial_status != "pending"

    @property
    def status(self):
        document = self.get()
        return document["status"] if document is not None else None

    @property
    def result(self):
        document = self.get()
        return deepcopy(document.get("result")) if document is not None else None

    @property
    def error(self):
        document = self.get()
        return deepcopy(document.get("error")) if document is not None else None

    @property
    def request(self):
        document = self.get()
        return deepcopy(document.get("request")) if document is not None else None

    def get(self):
        return self._repository.get(self.request_id, user_id=self.user_id)

    def wait(self, timeout=None, poll_interval=0.02):
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0 or not math.isfinite(timeout):
                _fail("invalid_timeout", "timeout is invalid")
        if (isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float))
                or poll_interval <= 0 or not math.isfinite(poll_interval)):
            _fail("invalid_timeout", "poll_interval is invalid")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            document = self.get()
            if document is None:
                _fail("not_found", "Enrichment request no longer exists")
            if document["status"] != "pending":
                return NutritionEnrichmentOutcome(document["status"], document.get("result"),
                                                  error=document.get("error"), request=document)
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _fail("single_flight_timeout", "The in-flight enrichment did not finish")
                time.sleep(min(poll_interval, remaining))
            else:
                time.sleep(poll_interval)

    def complete(self, status, result=None, *, error=None):
        if not self.owner:
            _fail("not_owner", "Only the lease owner can complete a request")
        return self._repository.complete(self.request_id, lease_owner=self.lease_owner,
                                         status=status, result=result, error=error)

    def abort(self, *, error=None):
        return self.complete("upstream_error", None, error=error)


class NutritionEnrichmentRequestRepository:
    """Durable request identity, result and lease repository."""

    def __init__(self, sql=None, *, lease_seconds=120, clock=time.time):
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) \
                or lease_seconds <= 0 or not math.isfinite(lease_seconds):
            _fail("invalid_lease", "lease_seconds is invalid")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        self.sql = sql
        self.durable = sql is not None
        if self.durable and getattr(sql, "dialect", None) != "sqlite":
            _fail("unsupported_database", "Enrichment repository requires SQLite")
        self.lease_seconds = float(lease_seconds)
        self.clock = clock
        self._lock = threading.RLock()
        self._requests = {}
        self._by_key = {}
        self._by_fingerprint = {}
        if self.durable:
            self.sql.executescript(SQLITE_TABLES)

    def _row(self, request_id):
        return self.sql.query_one(
            "SELECT request_id, user_id, idempotency_key, fingerprint, request_revision, "
            "request_payload, request_hash, status, result_payload, error_payload, lease_owner, "
            "lease_expires_at, attempts, created_at, updated_at, completed_at "
            "FROM nutrition_enrichment_requests WHERE request_id = ?", (request_id,))

    def _key_row(self, user_id, idempotency_key):
        return self.sql.query_one(
            "SELECT request_id, user_id, idempotency_key, fingerprint, request_revision, "
            "request_payload, request_hash, status, result_payload, error_payload, lease_owner, "
            "lease_expires_at, attempts, created_at, updated_at, completed_at "
            "FROM nutrition_enrichment_requests WHERE user_id = ? AND idempotency_key = ?",
            (user_id, idempotency_key))

    def _fingerprint_row(self, fingerprint):
        return self.sql.query_one(
            "SELECT request_id, user_id, idempotency_key, fingerprint, request_revision, "
            "request_payload, request_hash, status, result_payload, error_payload, lease_owner, "
            "lease_expires_at, attempts, created_at, updated_at, completed_at "
            "FROM nutrition_enrichment_requests WHERE fingerprint = ?", (fingerprint,))

    @staticmethod
    def _document(row):
        if not row:
            return None
        return {
            "request_id": row["request_id"], "user_id": row["user_id"],
            "idempotency_key": row["idempotency_key"], "fingerprint": row["fingerprint"],
            "request_revision": row["request_revision"],
            "request": deepcopy(_row_json(row, "request_payload")),
            "request_hash": row["request_hash"], "status": row["status"],
            "result": deepcopy(_row_json(row, "result_payload")),
            "error": deepcopy(_row_json(row, "error_payload")),
            "lease_owner": row["lease_owner"], "lease_expires_at": row["lease_expires_at"],
            "attempts": int(row["attempts"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"], "completed_at": row["completed_at"],
        }

    def _memory_row(self, request_id):
        return deepcopy(self._requests.get(request_id))

    def _check_existing(self, row, *, user_id, idempotency_key, fingerprint, payload_hash, request_revision):
        if row["fingerprint"] != fingerprint or row["request_hash"] != payload_hash \
                or row.get("request_revision") != request_revision:
            _fail("idempotency_conflict", "The idempotency key was used for another request")
        if row["user_id"] != user_id:
            _fail("ownership_conflict", "The request belongs to another user")
        return row

    def _expired(self, row, now):
        expiry = _parse_iso(row.get("lease_expires_at"))
        return row["status"] == "pending" and (expiry is None or expiry <= now)

    def _new_lease(self, row, *, owner, lease_owner=None):
        return NutritionEnrichmentLease(self, row, owner=owner, lease_owner=lease_owner)

    def begin(self, *, user_id, idempotency_key, fingerprint, request=None,
              request_payload=None, request_revision=None, lease_owner=None):
        """Insert or join a request and return an owner/follower lease.

        ``request_payload`` is accepted as an explicit alias for ``request``
        to make route call sites unambiguous.  The payload is server-built and
        is hashed here; clients must never be allowed to select this document.
        """
        user_id = _text(user_id, "user_id")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        fingerprint = _fingerprint(fingerprint)
        request_revision = _revision(request_revision)
        if request is not None and request_payload is not None and request != request_payload:
            _fail("invalid_request", "request and request_payload disagree")
        payload = request if request_payload is None else request_payload
        if payload is None:
            payload = {"fingerprint": fingerprint, "request_revision": request_revision}
        encoded = _json_bytes(payload, limit=MAX_REQUEST_BYTES, field="request_payload")
        payload_hash = hashlib.sha256(encoded).hexdigest()
        owner_token = _text(lease_owner, "lease_owner", 256) if lease_owner is not None else secrets.token_urlsafe(24)
        now = _now_seconds(self.clock)
        now_iso = _iso_from_seconds(now)
        expiry_iso = _iso_from_seconds(now + self.lease_seconds)

        if self.durable:
            with self.sql.transaction():
                def existing_lease(row, *, by_fingerprint=False):
                    document = self._document(row)
                    if by_fingerprint:
                        if document["user_id"] != user_id:
                            _fail("ownership_conflict", "The request fingerprint belongs to another user")
                        if (document["request_hash"] != payload_hash
                                or document["request_revision"] != request_revision):
                            _fail("idempotency_conflict", "The request fingerprint was used for another request")
                    else:
                        self._check_existing(document, user_id=user_id,
                                             idempotency_key=idempotency_key,
                                             fingerprint=fingerprint,
                                             payload_hash=payload_hash,
                                             request_revision=request_revision)
                    if document["status"] == "pending":
                        if self._expired(document, now):
                            self.sql.execute(
                                "UPDATE nutrition_enrichment_requests SET lease_owner = ?, lease_expires_at = ?, "
                                "attempts = attempts + 1, updated_at = ? WHERE request_id = ?",
                                (owner_token, expiry_iso, now_iso, document["request_id"]))
                            document = self._document(self._row(document["request_id"]))
                            return self._new_lease(document, owner=True, lease_owner=owner_token)
                        return self._new_lease(document, owner=False)
                    if document["status"] in _RETRYABLE:
                        self.sql.execute(
                            "UPDATE nutrition_enrichment_requests SET status = ?, result_payload = NULL, "
                            "error_payload = NULL, lease_owner = ?, lease_expires_at = ?, attempts = attempts + 1, "
                            "updated_at = ?, completed_at = NULL WHERE request_id = ?",
                            ("pending", owner_token, expiry_iso, now_iso, document["request_id"]))
                        document = self._document(self._row(document["request_id"]))
                        return self._new_lease(document, owner=True, lease_owner=owner_token)
                    return self._new_lease(document, owner=False)

                row = self._key_row(user_id, idempotency_key)
                if row:
                    return existing_lease(row)
                row = self._fingerprint_row(fingerprint)
                if row:
                    return existing_lease(row, by_fingerprint=True)
                # ON CONFLICT is required here: two processes can both observe
                # no row above and race to create the same idempotency key or
                # fingerprint.  The loser must reload the winner's row rather
                # than leaking a database UniqueViolation as HTTP 500.
                for _ in range(3):
                    request_id = secrets.token_urlsafe(18)
                    inserted = self.sql.execute(
                        "INSERT INTO nutrition_enrichment_requests "
                        "(request_id, user_id, idempotency_key, fingerprint, request_revision, request_payload, "
                        "request_hash, status, lease_owner, lease_expires_at, attempts, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                        (request_id, user_id, idempotency_key, fingerprint, request_revision,
                         to_json(payload), payload_hash, "pending", owner_token, expiry_iso, 1, now_iso, now_iso))
                    if inserted:
                        document = self._document(self._row(request_id))
                        return self._new_lease(document, owner=True, lease_owner=owner_token)
                    row = self._key_row(user_id, idempotency_key)
                    if row:
                        return existing_lease(row)
                    row = self._fingerprint_row(fingerprint)
                    if row:
                        return existing_lease(row, by_fingerprint=True)
                _fail("storage_conflict", "Could not establish the enrichment request identity")

        with self._lock:
            row = self._by_key.get((user_id, idempotency_key))
            if row is None:
                row = self._by_fingerprint.get(fingerprint)
            if row is not None:
                self._check_existing(row, user_id=user_id, idempotency_key=idempotency_key,
                                     fingerprint=fingerprint, payload_hash=payload_hash,
                                     request_revision=request_revision)
                if row["status"] == "pending" and self._expired(row, now):
                    row.update(status="pending", lease_owner=owner_token,
                               lease_expires_at=expiry_iso, attempts=row["attempts"] + 1,
                               updated_at=now_iso)
                    self._by_key[(user_id, idempotency_key)] = row
                    return self._new_lease(row, owner=True, lease_owner=owner_token)
                if row["status"] in _RETRYABLE:
                    row.update(status="pending", result=None, error=None, lease_owner=owner_token,
                               lease_expires_at=expiry_iso, attempts=row["attempts"] + 1,
                               updated_at=now_iso, completed_at=None)
                    self._by_key[(user_id, idempotency_key)] = row
                    return self._new_lease(row, owner=True, lease_owner=owner_token)
                return self._new_lease(row, owner=False)
            request_id = secrets.token_urlsafe(18)
            row = {"request_id": request_id, "user_id": user_id, "idempotency_key": idempotency_key,
                   "fingerprint": fingerprint, "request_revision": request_revision,
                   "request": deepcopy(payload), "request_hash": payload_hash, "status": "pending",
                   "result": None, "error": None, "lease_owner": owner_token,
                   "lease_expires_at": expiry_iso, "attempts": 1, "created_at": now_iso,
                   "updated_at": now_iso, "completed_at": None}
            self._requests[request_id] = row
            self._by_key[(user_id, idempotency_key)] = row
            self._by_fingerprint[fingerprint] = row
            return self._new_lease(row, owner=True, lease_owner=owner_token)

    def get(self, request_id, *, user_id=None):
        request_id = _text(request_id, "request_id")
        if user_id is not None:
            user_id = _text(user_id, "user_id")
        row = self._row(request_id) if self.durable else self._memory_row(request_id)
        document = self._document(row) if self.durable else row
        if document is None:
            return None
        if user_id is not None and document["user_id"] != user_id:
            _fail("ownership_conflict", "The request belongs to another user")
        return document

    def get_by_idempotency_key(self, *, user_id, idempotency_key):
        """Read an existing request identity without creating a lease.

        The enrichment route uses this only when a one-time scan authority was
        already consumed: an existing request may be replayed or retried by
        the coordinator, while a new idempotency key must not reuse that scan.
        Fingerprint and payload validation remain the coordinator's authority.
        """
        user_id = _text(user_id, "user_id")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        if self.durable:
            row = self._key_row(user_id, idempotency_key)
            return self._document(row)
        with self._lock:
            row = self._by_key.get((user_id, idempotency_key))
            return deepcopy(row) if row is not None else None

    def complete(self, request_id, *, lease_owner, status, result=None, error=None):
        request_id = _text(request_id, "request_id")
        lease_owner = _text(lease_owner, "lease_owner", 256)
        status = _text(status, "status", 64)
        if status not in _STATUSES:
            _fail("invalid_outcome", "Unsupported enrichment outcome")
        if result is not None:
            _json_bytes(result, limit=MAX_RESULT_BYTES, field="result")
        if error is not None:
            _json_bytes(error, limit=MAX_ERROR_BYTES, field="error")
        now_iso = _iso_from_seconds(_now_seconds(self.clock))
        completed_iso = None if status in _RETRYABLE else now_iso
        if self.durable:
            with self.sql.transaction():
                row = self._row(request_id)
                if not row:
                    _fail("not_found", "Enrichment request does not exist")
                document = self._document(row)
                if document["status"] != "pending":
                    _fail("already_completed", "The enrichment has already completed")
                if document["lease_owner"] != lease_owner:
                    _fail("not_owner", "Only the current lease owner can complete a request")
                self.sql.execute(
                    "UPDATE nutrition_enrichment_requests SET status = ?, result_payload = ?, error_payload = ?, "
                    "lease_owner = NULL, lease_expires_at = NULL, updated_at = ?, completed_at = ? WHERE request_id = ?",
                    (status, to_json(result) if result is not None else None,
                     to_json(error) if error is not None else None, now_iso, completed_iso, request_id))
                return NutritionEnrichmentOutcome(status, result, error=error,
                                                  request=self._document(self._row(request_id)))
        with self._lock:
            row = self._requests.get(request_id)
            if row is None:
                _fail("not_found", "Enrichment request does not exist")
            if row["status"] != "pending":
                _fail("already_completed", "The enrichment has already completed")
            if row["lease_owner"] != lease_owner:
                _fail("not_owner", "Only the current lease owner can complete a request")
            row.update(status=status, result=deepcopy(result), error=deepcopy(error),
                       lease_owner=None, lease_expires_at=None, updated_at=now_iso,
                       completed_at=completed_iso)
            return NutritionEnrichmentOutcome(status, result, error=error, request=deepcopy(row))

    def reclaim_expired(self, *, limit=100):
        """Return count of expired pending requests; reclamation happens in begin()."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            _fail("invalid_limit", "limit is invalid")
        now = _now_seconds(self.clock)
        if self.durable:
            # This method is intentionally observational.  A caller cannot
            # steal a lease without an idempotency key and server-built body.
            rows = self.sql.query_all(
                "SELECT request_id, lease_expires_at FROM nutrition_enrichment_requests "
                "WHERE status = 'pending' ORDER BY created_at LIMIT ?", (limit,))
            return [row["request_id"] for row in rows if (_parse_iso(row["lease_expires_at"]) or 0) <= now]
        with self._lock:
            return [row["request_id"] for row in list(self._requests.values())
                    if row["status"] == "pending" and (_parse_iso(row["lease_expires_at"]) or 0) <= now][:limit]


# Keep route naming independent from the storage-specific class name.  These
# aliases are intentionally local and do not create a second implementation.
NutritionEnrichmentRepository = NutritionEnrichmentRequestRepository
EnrichmentRequestRepository = NutritionEnrichmentRequestRepository

