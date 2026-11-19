"""Durable server-owned FoodData Central candidate snapshots.

The FDC selection prompt, model validator and user confirmation must all use
the exact same candidate bytes.  This repository stores that snapshot behind
the authenticated user and the already-persisted scan context.  Callers never
need to send the snapshot back to the server; they send a digest/reference and
the route loads the immutable document here.

SQLite is the only durable backend for this boundary.  ``sql=None`` is kept
for isolated unit tests only.
"""

from copy import deepcopy
from contextlib import nullcontext
import json
import math
import threading
import time

from repositories.sqlite_db import from_json, to_json, utc_iso
from services.fooddata_central_selection_service import (
    FdcCandidateSelectionError,
    build_fdc_candidate_snapshot,
)


MAX_ID = 256
MAX_SNAPSHOT_BYTES = 128 * 1024
_STATUSES = {"active", "expired", "revoked"}


class FdcCandidateSnapshotRepositoryError(ValueError):
    """Typed persistence error for route-level status mapping."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_fdc_candidate_snapshots (
    user_id TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    scan_revision INTEGER NOT NULL,
    item_set_digest TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scan_id, scan_revision)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_fdc_snapshots_user
    ON nutrition_fdc_candidate_snapshots (user_id, scan_id, scan_revision);
CREATE INDEX IF NOT EXISTS idx_nutrition_fdc_snapshots_expiry
    ON nutrition_fdc_candidate_snapshots (status, expires_at);
CREATE TABLE IF NOT EXISTS nutrition_fdc_candidate_search_reservations (
    scan_id TEXT NOT NULL,
    scan_revision INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_expires_at REAL NOT NULL,
    scan_expires_at REAL NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    attempts INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scan_id, scan_revision)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_fdc_search_reservations_expiry
    ON nutrition_fdc_candidate_search_reservations (scan_expires_at);
CREATE TABLE IF NOT EXISTS nutrition_fdc_search_no_hits (
    scan_id TEXT NOT NULL,
    scan_revision INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (scan_id, scan_revision, item_id),
    FOREIGN KEY (scan_id, scan_revision) REFERENCES nutrition_fdc_candidate_snapshots
        (scan_id, scan_revision) ON DELETE CASCADE
);
"""


def _fail(code, message):
    raise FdcCandidateSnapshotRepositoryError(code, message)


def _id(value, field):
    if (not isinstance(value, str) or not value or len(value) > MAX_ID
            or value.strip() != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("invalid_request", "scan_revision is invalid")
    return value


def _clock(clock):
    value = clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_clock", "The snapshot clock is invalid")
    return float(value)


def _canonical_json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise FdcCandidateSnapshotRepositoryError(
            "invalid_request", "Snapshot must be finite canonical JSON") from error
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        _fail("oversized_request", "Snapshot exceeds its size budget")
    return encoded


def _snapshot(value):
    if not isinstance(value, dict):
        _fail("invalid_request", "FDC candidate snapshot is invalid")
    try:
        # Validation also recomputes every digest and rejects unknown fields.
        normalized = _validate_snapshot(value)
    except FdcCandidateSelectionError as error:
        raise FdcCandidateSnapshotRepositoryError(error.code, str(error)) from error
    _canonical_json(normalized)
    return deepcopy(normalized)


def _digest(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        _fail("invalid_request", "snapshot_digest is invalid")
    return value


def _validate_snapshot(value):
    """Call the selection service's strict envelope validation without I/O."""
    # Kept in a tiny adapter to avoid making the service's private helper part
    # of its public API.  A prompt builder round-trips the same validation.
    from services.fooddata_central_selection_service import _validate_snapshot as validate
    return validate(value)


def _candidate_mapping(snapshot):
    return {item["item_id"]: deepcopy(item["candidates"]) for item in snapshot["items"]}


class FdcCandidateSnapshotRepository:
    """Persist and retrieve immutable candidate snapshots bound to scan state."""

    def __init__(self, sql=None, *, scan_context_repository=None, clock=time.time):
        if sql is not None and getattr(sql, "dialect", None) != "sqlite":
            _fail("unsupported_database", "FDC candidate snapshots require SQLite")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        self.sql = sql
        self.durable = sql is not None
        self.scan_context_repository = scan_context_repository
        self.clock = clock
        # Durable operations use SQLite's connection/transaction lock only;
        # confirmation may call this repository inside an existing transaction.
        self._lock = threading.RLock()
        self._snapshots = {}
        if self.durable:
            self.sql.executescript(SQLITE_TABLES)
            self.sql.execute(
                "DELETE FROM nutrition_fdc_candidate_search_reservations WHERE scan_expires_at <= ?",
                (_clock(self.clock),),
            )

    def _row(self, scan_id, scan_revision):
        if not self.durable:
            return self._snapshots.get((scan_id, scan_revision))
        return self.sql.query_one(
            "SELECT user_id, scan_id, scan_revision, item_set_digest, snapshot_digest, snapshot, "
            "issued_at, expires_at, status, created_at, updated_at "
            "FROM nutrition_fdc_candidate_snapshots WHERE scan_id = ? AND scan_revision = ?",
            (scan_id, scan_revision),
        )

    @staticmethod
    def _document(row):
        if not row:
            return None
        try:
            snapshot = _snapshot(from_json(row["snapshot"]))
        except FdcCandidateSnapshotRepositoryError as error:
            raise FdcCandidateSnapshotRepositoryError(
                "snapshot_corrupt", "Persisted FDC candidate snapshot failed validation") from error
        if (snapshot["snapshot_digest"] != row["snapshot_digest"]
                or snapshot["item_set_digest"] != row["item_set_digest"]
                or snapshot["scan_revision"] != int(row["scan_revision"])):
            _fail("snapshot_corrupt", "Persisted FDC candidate snapshot binding is inconsistent")
        return {
            "user_id": row["user_id"], "scan_id": row["scan_id"],
            "scan_revision": int(row["scan_revision"]),
            "item_set_digest": row["item_set_digest"],
            "snapshot_digest": row["snapshot_digest"],
            "snapshot": snapshot,
            "issued_at": float(row["issued_at"]), "expires_at": float(row["expires_at"]),
            "status": row["status"], "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _get_active_scan(self, *, user_id, scan_id, scan_revision, now):
        if self.scan_context_repository is None:
            _fail("storage_unavailable", "A server-owned scan context repository is required")
        try:
            context = self.scan_context_repository.get_scan_context(
                user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                include_inactive=False, now=now,
            )
        except Exception as error:
            if isinstance(error, FdcCandidateSnapshotRepositoryError):
                raise
            code = getattr(error, "code", "scan_unavailable")
            raise FdcCandidateSnapshotRepositoryError(code, str(error)) from error
        if context is None:
            _fail("scan_unavailable", "The server-owned scan context is unavailable")
        return context

    def save_candidates(self, *, user_id, scan_id, scan_revision, candidates_by_item,
                        reservation_owner=None, no_hit_item_ids=()):
        """Create and persist a snapshot from trusted server-side search results.

        This method intentionally accepts neither a client snapshot nor a
        client digest.  It reloads the authenticated scan context, projects
        its identity, and creates the digest-bound snapshot itself.  The
        caller must only pass candidates returned by the configured FDC
        provider, never request JSON.
        """
        user_id, scan_id = _id(user_id, "user_id"), _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        now = _clock(self.clock)
        context = self._get_active_scan(user_id=user_id, scan_id=scan_id,
                                        scan_revision=scan_revision, now=now)
        try:
            normalized = build_fdc_candidate_snapshot(
                context["items"], candidates_by_item, scan_revision=scan_revision)
        except FdcCandidateSelectionError as error:
            raise FdcCandidateSnapshotRepositoryError(error.code, str(error)) from error
        empty_item_ids = {item["item_id"] for item in normalized["items"] if not item["candidates"]}
        if (not isinstance(no_hit_item_ids, (tuple, list))
                or any(not isinstance(item_id, str) or item_id not in empty_item_ids
                       for item_id in no_hit_item_ids)
                or len(set(no_hit_item_ids)) != len(no_hit_item_ids)):
            _fail("invalid_request", "FDC no-hit evidence must reference unique empty candidate groups")
        _canonical_json(normalized)
        issued, expiry = float(context["issued_at"]), float(context["expires_at"])
        if expiry <= now:
            _fail("expired", "Scan context has expired")
        return self._save_snapshot(user_id=user_id, scan_id=scan_id,
                                   scan_revision=scan_revision, snapshot=normalized,
                                   issued_at=issued, expires_at=expiry,
                                   reservation_owner=reservation_owner,
                                   no_hit_item_ids=no_hit_item_ids)

    def _save_snapshot(self, *, user_id, scan_id, scan_revision, snapshot, issued_at, expires_at,
                       reservation_owner=None, no_hit_item_ids=()):
        """Private persistence primitive; production code cannot supply client snapshots."""
        normalized = _snapshot(snapshot)
        if normalized["scan_revision"] != scan_revision:
            _fail("plan_mismatch", "Snapshot belongs to another scan revision")
        key = (scan_id, scan_revision)
        document = {
            "user_id": user_id, "scan_id": scan_id, "scan_revision": scan_revision,
            "item_set_digest": normalized["item_set_digest"],
            "snapshot_digest": normalized["snapshot_digest"],
            "snapshot": normalized, "issued_at": issued_at, "expires_at": expires_at,
            "status": "active", "created_at": utc_iso(), "updated_at": utc_iso(),
        }
        with (nullcontext() if self.durable else self._lock):
            if self.durable:
                with self.sql.transaction():
                    if reservation_owner is not None:
                        self._assert_search_reservation_owner(
                            user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                            lease_owner=reservation_owner)
                    existing = self._row(scan_id, scan_revision)
                    if existing:
                        prior = self._document(existing)
                        if prior["user_id"] != user_id:
                            _fail("wrong_user", "Snapshot belongs to another user")
                        if prior["snapshot_digest"] != document["snapshot_digest"]:
                            _fail("snapshot_conflict", "Scan revision already has another candidate snapshot")
                        if reservation_owner is not None:
                            self._finish_search_reservation(
                                user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                                lease_owner=reservation_owner)
                        return prior
                    inserted = self.sql.execute(
                        "INSERT INTO nutrition_fdc_candidate_snapshots "
                        "(user_id, scan_id, scan_revision, item_set_digest, snapshot_digest, snapshot, "
                        "issued_at, expires_at, status, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (scan_id, scan_revision) DO NOTHING",
                        (user_id, scan_id, scan_revision, document["item_set_digest"],
                         document["snapshot_digest"], to_json(normalized), issued_at, expires_at,
                         "active", document["created_at"], document["updated_at"]),
                    )
                    if inserted == 0:
                        concurrent = self._document(self._row(scan_id, scan_revision))
                        if concurrent is None:
                            _fail("snapshot_conflict", "Candidate snapshot could not be recorded")
                        if concurrent["user_id"] != user_id:
                            _fail("wrong_user", "Snapshot belongs to another user")
                        if concurrent["snapshot_digest"] != document["snapshot_digest"]:
                            _fail("snapshot_conflict", "Scan revision already has another candidate snapshot")
                        if reservation_owner is not None:
                            self._finish_search_reservation(
                                user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                                lease_owner=reservation_owner)
                        return concurrent
                    for item_id in no_hit_item_ids:
                        self.sql.execute(
                            "INSERT INTO nutrition_fdc_search_no_hits (scan_id, scan_revision, item_id) "
                            "VALUES (?, ?, ?)", (scan_id, scan_revision, item_id))
                    if reservation_owner is not None:
                        self._finish_search_reservation(
                            user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                            lease_owner=reservation_owner)
                    return self._document(self._row(scan_id, scan_revision))
            existing = self._row(scan_id, scan_revision)
            if existing:
                prior = self._document(existing)
                if prior["user_id"] != user_id:
                    _fail("wrong_user", "Snapshot belongs to another user")
                if prior["snapshot_digest"] != document["snapshot_digest"]:
                    _fail("snapshot_conflict", "Scan revision already has another candidate snapshot")
                return prior
            self._snapshots[key] = deepcopy(document)
            return deepcopy(document)

    def has_confirmed_search_miss(self, *, user_id, scan_id, scan_revision, item_id):
        """Read an explicit, unexpired Search result, never infer it from an empty list."""
        if not self.durable:
            return False
        now = _clock(self.clock)
        return self.sql.query_one(
            "SELECT 1 FROM nutrition_fdc_search_no_hits h "
            "JOIN nutrition_fdc_candidate_snapshots s USING (scan_id, scan_revision) "
            "JOIN nutrition_scan_contexts c USING (scan_id, scan_revision) "
            "WHERE h.scan_id = ? AND h.scan_revision = ? AND h.item_id = ? "
            "AND s.user_id = ? AND c.user_id = s.user_id "
            "AND ((s.status = 'active' AND c.status = 'active') "
            "OR (s.status IN ('active', 'superseded') AND c.status = 'consumed')) "
            "AND s.expires_at > ? AND c.expires_at > ?",
            (scan_id, scan_revision, item_id, user_id, now, now),
        ) is not None

    def reserve_search(self, *, user_id, scan_id, scan_revision, lease_owner,
                       lease_seconds=60.0):
        """Claim a short SQLite lease so only one process searches a scan revision."""
        if not self.durable:
            _fail("storage_unavailable", "Cross-process FDC search requires SQLite")
        user_id, scan_id = _id(user_id, "user_id"), _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        lease_owner = _id(lease_owner, "lease_owner")
        if (isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float))
                or not math.isfinite(lease_seconds) or lease_seconds <= 0):
            _fail("invalid_expiry", "Search reservation lease is invalid")
        now = _clock(self.clock)
        context = self._get_active_scan(user_id=user_id, scan_id=scan_id,
                                        scan_revision=scan_revision, now=now)
        scan_expires_at = float(context["expires_at"])
        if scan_expires_at <= now:
            _fail("expired", "Scan context has expired")
        lease_expires_at = now + float(lease_seconds)
        timestamp = utc_iso()
        key = (scan_id, scan_revision)
        with self.sql.transaction():
            self._assert_active_scan_in_transaction(
                user_id=user_id, scan_id=scan_id, scan_revision=scan_revision)
            existing = self._document(self._row(scan_id, scan_revision))
            if existing is not None:
                if existing["user_id"] != user_id:
                    _fail("wrong_user", "Snapshot belongs to another user")
                if existing["status"] != "active" or existing["expires_at"] <= _clock(self.clock):
                    _fail("snapshot_unavailable", "FDC candidate snapshot is no longer active")
                return {"owner": False, "lease_owner": None,
                        "lease_expires_at": float(existing["expires_at"])}
            self.sql.execute(
                "DELETE FROM nutrition_fdc_candidate_search_reservations WHERE scan_expires_at <= ?",
                (now,),
            )
            row = self._search_reservation_row(*key)
            if row is not None and row["user_id"] != user_id:
                _fail("wrong_user", "Search reservation belongs to another user")
            if row is None:
                inserted = self.sql.execute(
                    "INSERT INTO nutrition_fdc_candidate_search_reservations "
                    "(scan_id, scan_revision, user_id, lease_owner, lease_expires_at, scan_expires_at, "
                    "status, attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (scan_id, scan_revision) DO NOTHING",
                    (scan_id, scan_revision, user_id, lease_owner, lease_expires_at,
                     scan_expires_at, "pending", 1, timestamp, timestamp),
                )
                row = self._search_reservation_row(*key)
                if inserted == 1:
                    return {"owner": True, "lease_owner": lease_owner,
                            "lease_expires_at": float(row["lease_expires_at"])}
            if row["user_id"] != user_id:
                _fail("wrong_user", "Search reservation belongs to another user")
            if row["status"] == "pending" and float(row["lease_expires_at"]) > now:
                return {"owner": False, "lease_owner": row["lease_owner"],
                        "lease_expires_at": float(row["lease_expires_at"])}
            self.sql.execute(
                "UPDATE nutrition_fdc_candidate_search_reservations SET lease_owner = ?, "
                "lease_expires_at = ?, scan_expires_at = ?, status = ?, error_code = NULL, "
                "attempts = attempts + 1, updated_at = ? "
                "WHERE scan_id = ? AND scan_revision = ? "
                "AND (status = ? OR (status = ? AND lease_expires_at <= ?))",
                (lease_owner, lease_expires_at, scan_expires_at, "pending", timestamp,
                 scan_id, scan_revision, "failed", "pending", now),
            )
            row = self._search_reservation_row(*key)
            if row["lease_owner"] == lease_owner:
                return {"owner": True, "lease_owner": lease_owner,
                        "lease_expires_at": float(row["lease_expires_at"])}
            return {"owner": False, "lease_owner": row["lease_owner"],
                    "lease_expires_at": float(row["lease_expires_at"])}

    def get_search_reservation(self, *, user_id, scan_id, scan_revision):
        """Read the current lease without taking SQLite's writer lock."""
        if not self.durable:
            _fail("storage_unavailable", "Cross-process FDC search requires SQLite")
        user_id, scan_id = _id(user_id, "user_id"), _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        row = self._search_reservation_row(scan_id, scan_revision)
        if row is None:
            return None
        if row["user_id"] != user_id:
            _fail("wrong_user", "Search reservation belongs to another user")
        return {
            "status": row["status"], "lease_owner": row["lease_owner"],
            "lease_expires_at": float(row["lease_expires_at"]),
            "lease_active": float(row["lease_expires_at"]) > _clock(self.clock),
            "error_code": row["error_code"],
        }

    def release_search(self, *, user_id, scan_id, scan_revision, lease_owner):
        """Release an abandoned lease only when its process still owns it."""
        if not self.durable:
            return False
        with self.sql.transaction():
            return bool(self.sql.execute(
                "DELETE FROM nutrition_fdc_candidate_search_reservations "
                "WHERE user_id = ? AND scan_id = ? AND scan_revision = ? AND lease_owner = ?",
                (user_id, scan_id, scan_revision, lease_owner),
            ))

    def fail_search(self, *, user_id, scan_id, scan_revision, lease_owner, error_code):
        """Publish a short durable failure outcome for existing followers to observe."""
        if not self.durable:
            return False
        user_id, scan_id = _id(user_id, "user_id"), _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        lease_owner = _id(lease_owner, "lease_owner")
        error_code = _id(error_code, "error_code")
        now = _clock(self.clock)
        with self.sql.transaction():
            return bool(self.sql.execute(
                "UPDATE nutrition_fdc_candidate_search_reservations SET status = ?, error_code = ?, "
                "lease_expires_at = ?, updated_at = ? WHERE user_id = ? AND scan_id = ? "
                "AND scan_revision = ? AND lease_owner = ? AND status = ?",
                ("failed", error_code, now, utc_iso(), user_id, scan_id,
                 scan_revision, lease_owner, "pending"),
            ))

    def _search_reservation_row(self, scan_id, scan_revision):
        return self.sql.query_one(
            "SELECT user_id, lease_owner, lease_expires_at, scan_expires_at, status, error_code "
            "FROM nutrition_fdc_candidate_search_reservations "
            "WHERE scan_id = ? AND scan_revision = ?", (scan_id, scan_revision),
        )

    def _assert_search_reservation_owner(self, *, user_id, scan_id, scan_revision, lease_owner):
        row = self._search_reservation_row(scan_id, scan_revision)
        now = _clock(self.clock)
        if row is None:
            _fail("reservation_lost", "FDC search reservation is no longer active")
        if row["user_id"] != user_id:
            _fail("wrong_user", "Search reservation belongs to another user")
        if (row["status"] != "pending" or row["lease_owner"] != lease_owner
                or float(row["lease_expires_at"]) <= now):
            _fail("reservation_lost", "FDC search reservation is no longer owned")
        if float(row["scan_expires_at"]) <= now:
            _fail("expired", "Scan context has expired")
        self._assert_active_scan_in_transaction(
            user_id=user_id, scan_id=scan_id, scan_revision=scan_revision)

    def _assert_active_scan_in_transaction(self, *, user_id, scan_id, scan_revision):
        # The SQL writer lock is held. Do not acquire the scan repository lock
        # here: its ordinary readers acquire those same locks in reverse order.
        row = self._scan_state(scan_id, scan_revision)
        if row is not None and row["user_id"] != user_id:
            _fail("wrong_user", "Scan context belongs to another user")
        if row is None or row["status"] != "active" or float(row["expires_at"]) <= _clock(self.clock):
            _fail("scan_unavailable", "The server-owned scan context is unavailable")

    def _scan_state(self, scan_id, scan_revision):
        if getattr(self.scan_context_repository, "sql", None) is not self.sql:
            _fail("storage_unavailable", "FDC search requires the same SQLite scan repository")
        return self.sql.query_one(
            "SELECT user_id, status, expires_at FROM nutrition_scan_contexts "
            "WHERE scan_id = ? AND scan_revision = ?", (scan_id, scan_revision),
        )

    def _finish_search_reservation(self, *, user_id, scan_id, scan_revision, lease_owner):
        deleted = self.sql.execute(
            "DELETE FROM nutrition_fdc_candidate_search_reservations "
            "WHERE user_id = ? AND scan_id = ? AND scan_revision = ? AND lease_owner = ?",
            (user_id, scan_id, scan_revision, lease_owner),
        )
        if deleted != 1:
            _fail("reservation_lost", "FDC search reservation is no longer owned")

    def get_snapshot(self, *, user_id, scan_id, scan_revision, snapshot_digest=None,
                     include_inactive=False, now=None):
        user_id, scan_id = _id(user_id, "user_id"), _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        if snapshot_digest is not None:
            _digest(snapshot_digest)
        current = _clock(self.clock) if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
            _fail("invalid_clock", "The snapshot clock is invalid")
        with (nullcontext() if self.durable else self._lock):
            document = self._document(self._row(scan_id, scan_revision))
            if document is None:
                return None
            if document["user_id"] != user_id:
                _fail("wrong_user", "Snapshot belongs to another user")
            if snapshot_digest is not None and document["snapshot_digest"] != snapshot_digest:
                _fail("snapshot_mismatch", "Snapshot digest does not match the stored document")
            # A snapshot is only usable while its server-owned scan revision is
            # active.  This prevents a client from replaying a valid old digest
            # after the scanner created a newer revision or revoked the scan.
            if self.scan_context_repository is not None:
                if self.durable:
                    context = self._scan_state(scan_id, scan_revision)
                    if context is not None:
                        if context["user_id"] != user_id:
                            _fail("wrong_user", "Scan context belongs to another user")
                        if context["status"] == "active" and float(context["expires_at"]) <= current:
                            context["status"] = "expired"
                else:
                    context = self.scan_context_repository.get_scan_context(
                        user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                        include_inactive=True, now=current)
                if context is None:
                    return None
                if context["status"] != "active":
                    document["status"] = (
                        "expired" if context["status"] == "expired" else
                        "revoked" if context["status"] == "revoked" else "superseded"
                    )
                    if self.durable:
                        self.sql.execute(
                            "UPDATE nutrition_fdc_candidate_snapshots SET status = ?, updated_at = ? "
                            "WHERE scan_id = ? AND scan_revision = ? AND status = ?",
                            (document["status"], utc_iso(), scan_id, scan_revision, "active"),
                        )
                    else:
                        self._snapshots[(scan_id, scan_revision)]["status"] = document["status"]
            if document["status"] == "active" and float(current) >= document["expires_at"]:
                document["status"] = "expired"
                if self.durable:
                    self.sql.execute(
                        "UPDATE nutrition_fdc_candidate_snapshots SET status = ?, updated_at = ? "
                        "WHERE scan_id = ? AND scan_revision = ? AND status = ?",
                        ("expired", utc_iso(), scan_id, scan_revision, "active"),
                    )
                else:
                    self._snapshots[(scan_id, scan_revision)]["status"] = "expired"
            if not include_inactive and document["status"] != "active":
                return None
            return deepcopy(document)

    def revoke_snapshot(self, *, user_id, scan_id, scan_revision):
        document = self.get_snapshot(user_id=user_id, scan_id=scan_id,
                                     scan_revision=scan_revision, include_inactive=True)
        if document is None:
            return None
        if document["status"] == "expired":
            return document
        with (nullcontext() if self.durable else self._lock):
            if self.durable:
                self.sql.execute(
                    "UPDATE nutrition_fdc_candidate_snapshots SET status = ?, updated_at = ? "
                    "WHERE scan_id = ? AND scan_revision = ?",
                    ("revoked", utc_iso(), scan_id, scan_revision),
                )
            else:
                self._snapshots[(scan_id, scan_revision)]["status"] = "revoked"
            document["status"] = "revoked"
            return document


__all__ = ["FdcCandidateSnapshotRepository", "FdcCandidateSnapshotRepositoryError", "SQLITE_TABLES"]
