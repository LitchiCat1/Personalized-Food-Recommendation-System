"""Durable server-owned scan contexts and authority replay records.

The scanner is the only trusted producer of a scan context.  An enrichment
route must load the context through this repository before issuing authority
or calling a provider: the user, scan revision, and complete item set are
checked against the durable row rather than request JSON alone.

This module intentionally has no HTTP or provider dependency. It supports
SQLite plus an explicit in-memory mode for unit tests. The durable enrichment
path requires SQLite transactions and unique constraints.
"""

from copy import deepcopy
import hashlib
import json
import math
import threading
import time

from repositories.sqlite_db import from_json, to_json, utc_iso


MAX_ID = 256
MAX_NAME = 300
MAX_ITEMS = 64
MAX_CONTEXT_BYTES = 512 * 1024
MAX_JTI = 128
_HEX = set("0123456789abcdef")
_STATUSES = {"active", "consumed", "expired", "revoked", "superseded"}


class ScanContextRepositoryError(ValueError):
    """Typed repository boundary error; routes can map ``code`` to HTTP."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_scan_contexts (
    scan_id TEXT NOT NULL,
    scan_revision INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    item_set_hash TEXT NOT NULL,
    items TEXT NOT NULL,
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL,
    consumed_at REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scan_id, scan_revision)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_scan_contexts_user
    ON nutrition_scan_contexts (user_id, scan_id, scan_revision);
CREATE INDEX IF NOT EXISTS idx_nutrition_scan_contexts_expiry
    ON nutrition_scan_contexts (status, expires_at);
CREATE TABLE IF NOT EXISTS nutrition_scan_authority_replays (
    jti TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    scan_revision INTEGER NOT NULL,
    consumed_at REAL NOT NULL,
    FOREIGN KEY (scan_id, scan_revision)
        REFERENCES nutrition_scan_contexts (scan_id, scan_revision)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_scan_replays_context
    ON nutrition_scan_authority_replays (user_id, scan_id, scan_revision);
"""


def _fail(code, message):
    raise ScanContextRepositoryError(code, message)


def _id(value, field, maximum=MAX_ID):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail("invalid_id", f"{field} is invalid")
    return value


def _revision(value, field="scan_revision"):
    if type(value) is not int or value < 0:
        _fail("invalid_revision", f"{field} is invalid")
    return value


def _clock_value(clock):
    value = clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_clock", "The scan context clock is invalid")
    return float(value)


def _canonical(value):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ScanContextRepositoryError("invalid_context", "Context must be finite canonical JSON") from error
    if len(encoded) > MAX_CONTEXT_BYTES:
        _fail("oversized_context", "Scan context exceeds its size budget")
    return encoded


def _item(item):
    if not isinstance(item, dict):
        _fail("invalid_items", "Each scan item must be an object")
    allowed = {"item_id", "item_revision", "name_zh", "confidence", "weight_confidence",
               "estimated_weight_g", "food_state", "preparation_method", "components_scope",
               "brand", "variant", "validation_issues", "identity_confirmation_required",
               "identity_confirmation_source", "identity_confirmation_id"}
    if set(item) - allowed:
        _fail("invalid_items", "Scan item contains unsupported fields")
    if "identity_confirmation_required" in item and type(item["identity_confirmation_required"]) is not bool:
        _fail("invalid_items", "identity_confirmation_required must be a boolean")
    confirmation_source = item.get("identity_confirmation_source")
    confirmation_id = item.get("identity_confirmation_id")
    if confirmation_source is not None and confirmation_source != "user":
        _fail("invalid_items", "identity_confirmation_source is invalid")
    if confirmation_id is not None:
        _id(confirmation_id, "identity_confirmation_id")
    if ((confirmation_source == "user") != (confirmation_id is not None)
            or (confirmation_source == "user" and item.get("identity_confirmation_required") is not False)):
        _fail("invalid_items", "User identity confirmation provenance is incomplete")
    _id(item.get("item_id"), "item_id")
    if type(item.get("item_revision")) is not int or item["item_revision"] < 0:
        _fail("invalid_items", "item_revision is invalid")
    name = item.get("name_zh")
    if (not isinstance(name, str) or not name or len(name) > MAX_NAME
            or name.strip() != name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        _fail("invalid_items", "name_zh is invalid")
    for field in ("confidence", "weight_confidence"):
        value = item.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value < 0 or value > 1):
            _fail("invalid_items", f"{field} is invalid")
    weight = item.get("estimated_weight_g")
    if weight is not None:
        if (isinstance(weight, bool) or not isinstance(weight, (int, float))
                or not math.isfinite(weight) or weight <= 0 or weight > 2000):
            _fail("invalid_items", "estimated_weight_g is invalid")
    enums = {
        "food_state": {"prepared", "raw", "dry", "unknown"},
        "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted",
                               "braised", "steamed", "mixed", "unknown"},
        "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides", "unknown"},
    }
    for field, values in enums.items():
        value = item.get(field)
        if value is not None and value not in values:
            _fail("invalid_items", f"{field} is invalid")
    for field in ("brand", "variant"):
        value = item.get(field)
        if value is not None:
            _id(value, field, 300)
    issues = item.get("validation_issues", [])
    if (not isinstance(issues, list) or len(issues) > 32
            or any(not isinstance(issue, str) or not issue or len(issue) > 128
                   or issue.strip() != issue for issue in issues)):
        _fail("invalid_items", "validation_issues are invalid")
    return deepcopy(item)


def _items(items):
    if not isinstance(items, (list, tuple)) or not items or len(items) > MAX_ITEMS:
        _fail("invalid_items", "Scan items are invalid")
    result = [_item(value) for value in items]
    ids = [value["item_id"] for value in result]
    if len(ids) != len(set(ids)):
        _fail("invalid_items", "Scan item IDs must be unique")
    # Order is presentation-only; the identity of the complete item set is not.
    return result


def item_set_hash(items):
    checked = _items(items)
    ordered = sorted(checked, key=lambda value: value["item_id"])
    return hashlib.sha256(_canonical(ordered)).hexdigest()


class NutritionScanContextRepository:
    """Durable scan context and replay boundary for enrichment authorization."""

    def __init__(self, sql=None, *, clock=time.time):
        if sql is not None and getattr(sql, "dialect", None) != "sqlite":
            _fail("unsupported_database", "Scan contexts require SQLite")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        self.sql = sql
        self.durable = sql is not None
        self.clock = clock
        self._lock = threading.RLock()
        self._contexts = {}
        self._replays = {}
        if self.durable:
            self.sql.executescript(SQLITE_TABLES)

    def _row(self, scan_id, revision):
        if not self.durable:
            return self._contexts.get((scan_id, revision))
        return self.sql.query_one(
            "SELECT scan_id, scan_revision, user_id, item_set_hash, items, issued_at, expires_at, "
            "status, consumed_at, created_at, updated_at FROM nutrition_scan_contexts "
            "WHERE scan_id = ? AND scan_revision = ?", (scan_id, revision))

    @staticmethod
    def _document(row):
        if not row:
            return None
        items = from_json(row["items"])
        return {"scan_id": row["scan_id"], "scan_revision": int(row["scan_revision"]),
                "user_id": row["user_id"], "item_set_hash": row["item_set_hash"],
                "items": deepcopy(items), "issued_at": float(row["issued_at"]),
                "expires_at": float(row["expires_at"]), "status": row["status"],
                "consumed_at": row.get("consumed_at"), "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at")}

    def _check_common(self, *, user_id, scan_id, scan_revision, items, now=None):
        user_id = _id(user_id, "user_id")
        scan_id = _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        checked = _items(items)
        now = _clock_value(self.clock) if now is None else now
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            _fail("invalid_clock", "The scan context clock is invalid")
        return user_id, scan_id, scan_revision, checked, float(now)

    def save_scan_context(self, *, user_id, scan_id, scan_revision, items,
                          ttl_seconds=120, issued_at=None, expires_at=None):
        """Create a scan revision, idempotently returning an exact duplicate."""
        user_id = _id(user_id, "user_id")
        scan_id = _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        checked = _items(items)
        digest = item_set_hash(checked)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) \
                or not math.isfinite(ttl_seconds) or ttl_seconds <= 0 or ttl_seconds > 15 * 60:
            _fail("invalid_expiry", "ttl_seconds is invalid")
        issued = _clock_value(self.clock) if issued_at is None else issued_at
        if isinstance(issued, bool) or not isinstance(issued, (int, float)) or not math.isfinite(issued):
            _fail("invalid_expiry", "issued_at is invalid")
        expiry = issued + float(ttl_seconds) if expires_at is None else expires_at
        if (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
                or not math.isfinite(expiry) or expiry <= issued
                or float(expiry) - float(issued) > 15 * 60):
            _fail("invalid_expiry", "expires_at is invalid")
        _canonical(checked)
        if self.durable:
            now_text = utc_iso()
            with self.sql.transaction():
                existing = self._row(scan_id, scan_revision)
                if existing:
                    document = self._document(existing)
                    if document["user_id"] != user_id:
                        _fail("wrong_user", "Scan context belongs to another user")
                    if document["item_set_hash"] != digest:
                        _fail("revision_conflict", "Scan revision already contains another item set")
                    return document
                latest = self.sql.query_one(
                    "SELECT scan_revision, user_id FROM nutrition_scan_contexts "
                    "WHERE scan_id = ? ORDER BY scan_revision DESC LIMIT 1", (scan_id,))
                if latest and latest["user_id"] != user_id:
                    _fail("wrong_user", "Scan context belongs to another user")
                if latest and scan_revision != int(latest["scan_revision"]) + 1:
                    _fail("revision_conflict", "Scan revisions must advance one at a time")
                self.sql.execute(
                    "UPDATE nutrition_scan_contexts SET status = ?, updated_at = ? "
                    "WHERE scan_id = ? AND status = ?",
                    ("superseded", now_text, scan_id, "active"))
                inserted = self.sql.execute(
                    "INSERT INTO nutrition_scan_contexts "
                    "(scan_id, scan_revision, user_id, item_set_hash, items, issued_at, expires_at, status, consumed_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (scan_id, scan_revision) DO NOTHING",
                    (scan_id, scan_revision, user_id, digest, to_json(checked), float(issued), float(expiry),
                     "active", None, now_text, now_text))
                if inserted == 0:
                    # Another process may have created this revision after the
                    # initial read; reload the durable row before deciding whether
                    # this is an idempotent replay or a conflicting revision.
                    concurrent = self._row(scan_id, scan_revision)
                    document = self._document(concurrent)
                    if document is None:
                        _fail("revision_conflict", "Scan revision could not be recorded")
                    if document["user_id"] != user_id:
                        _fail("wrong_user", "Scan context belongs to another user")
                    if document["item_set_hash"] != digest:
                        _fail("revision_conflict", "Scan revision already contains another item set")
                    return document
                return self._document(self._row(scan_id, scan_revision))
        with self._lock:
            key = (scan_id, scan_revision)
            existing = self._contexts.get(key)
            if existing:
                if existing["user_id"] != user_id:
                    _fail("wrong_user", "Scan context belongs to another user")
                if existing["item_set_hash"] != digest:
                    _fail("revision_conflict", "Scan revision already contains another item set")
                return deepcopy(existing)
            latest_context = max((context for context in self._contexts.values()
                                  if context["scan_id"] == scan_id),
                                 key=lambda context: context["scan_revision"], default=None)
            if latest_context and latest_context["user_id"] != user_id:
                _fail("wrong_user", "Scan context belongs to another user")
            if latest_context is not None and scan_revision != latest_context["scan_revision"] + 1:
                _fail("revision_conflict", "Scan revisions must advance one at a time")
            now_text = utc_iso()
            for context in self._contexts.values():
                if context["scan_id"] == scan_id and context["status"] == "active":
                    context["status"], context["updated_at"] = "superseded", now_text
            document = {"scan_id": scan_id, "scan_revision": scan_revision, "user_id": user_id,
                        "item_set_hash": digest, "items": checked, "issued_at": float(issued),
                        "expires_at": float(expiry), "status": "active", "consumed_at": None,
                        "created_at": now_text, "updated_at": now_text}
            self._contexts[key] = deepcopy(document)
            return deepcopy(document)

    def create_revision_in_transaction(self, *, user_id, scan_id, from_revision,
                                       items, issued_at, expires_at):
        """Create the next revision while the caller owns a SQLite transaction.

        This is intentionally a narrow internal primitive for confirmation
        workflows.  It validates that the source revision still owns the same
        complete item set, supersedes it, and inserts exactly one next revision.
        The method never starts or commits a transaction itself, so a caller can
        atomically persist a confirmation record alongside the new context.
        """
        if not self.durable:
            _fail("unsupported_database", "Atomic revision issuance requires SQLite")
        user_id = _id(user_id, "user_id")
        scan_id = _id(scan_id, "scan_id")
        from_revision = _revision(from_revision, "from_revision")
        checked = _items(items)
        if (isinstance(issued_at, bool) or not isinstance(issued_at, (int, float))
                or not math.isfinite(issued_at)):
            _fail("invalid_expiry", "issued_at is invalid")
        if (isinstance(expires_at, bool) or not isinstance(expires_at, (int, float))
                or not math.isfinite(expires_at) or expires_at <= issued_at):
            _fail("invalid_expiry", "expires_at is invalid")
        expected_hash = item_set_hash(checked)
        with self._lock:
            current = self._document(self._row(scan_id, from_revision))
            if current is None:
                _fail("scan_not_found", "Source scan context does not exist")
            if current["user_id"] != user_id:
                _fail("wrong_user", "Source scan context belongs to another user")
            if current["status"] != "active":
                _fail("stale_revision", "Source scan context is no longer active")
            if current["item_set_hash"] != expected_hash:
                _fail("item_set_mismatch", "New revision items do not match the source context")
            next_revision = from_revision + 1
            existing = self._row(scan_id, next_revision)
            if existing:
                document = self._document(existing)
                if document["user_id"] != user_id or document["item_set_hash"] != expected_hash:
                    _fail("revision_conflict", "Next scan revision already contains another item set")
                return deepcopy(document)
            now_text = utc_iso()
            self.sql.execute(
                "UPDATE nutrition_scan_contexts SET status = ?, updated_at = ? "
                "WHERE scan_id = ? AND scan_revision = ? AND status = ?",
                ("superseded", now_text, scan_id, from_revision, "active"),
            )
            inserted = self.sql.execute(
                "INSERT INTO nutrition_scan_contexts "
                "(scan_id, scan_revision, user_id, item_set_hash, items, issued_at, expires_at, status, consumed_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (scan_id, next_revision, user_id, expected_hash, to_json(checked),
                 float(issued_at), float(expires_at), "active", None, now_text, now_text),
            )
            if inserted != 1:
                _fail("revision_conflict", "Next scan revision could not be recorded")
            return self._document(self._row(scan_id, next_revision))

    def create_identity_revision_in_transaction(self, *, user_id, scan_id, from_revision,
                                                item_id, item_revision, confirmed_name,
                                                confirmation_id, issued_at, expires_at):
        """Issue one user-confirmed name while the caller owns a SQLite transaction."""
        if not self.durable:
            _fail("unsupported_database", "Identity revisions require SQLite")
        user_id = _id(user_id, "user_id")
        scan_id = _id(scan_id, "scan_id")
        from_revision = _revision(from_revision, "from_revision")
        item_id = _id(item_id, "item_id")
        item_revision = _revision(item_revision, "item_revision")
        confirmation_id = _id(confirmation_id, "identity_confirmation_id")
        if (not isinstance(confirmed_name, str) or not confirmed_name
                or len(confirmed_name) > 120 or confirmed_name.strip() != confirmed_name
                or any(ord(char) < 32 or ord(char) == 127 for char in confirmed_name)):
            _fail("invalid_items", "confirmed_name is invalid")
        for value, field in ((issued_at, "issued_at"), (expires_at, "expires_at")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                _fail("invalid_expiry", f"{field} is invalid")
        if expires_at <= issued_at or expires_at - issued_at > 15 * 60:
            _fail("invalid_expiry", "expires_at is invalid")

        with self._lock:
            current = self._document(self._row(scan_id, from_revision))
            if current is None:
                _fail("scan_not_found", "Source scan context does not exist")
            if current["user_id"] != user_id:
                _fail("wrong_user", "Source scan context belongs to another user")
            if current["status"] != "active":
                _fail("stale_revision", "Source scan context is no longer current")
            if _clock_value(self.clock) >= current["expires_at"]:
                self._expire_locked(current)
                _fail("expired", "Source scan context has expired")
            latest = self.sql.query_one(
                "SELECT MAX(scan_revision) AS revision FROM nutrition_scan_contexts WHERE scan_id = ?",
                (scan_id,),
            )
            if latest is None or int(latest["revision"]) != from_revision:
                _fail("stale_revision", "Source scan context is no longer current")

            items = deepcopy(current["items"])
            target = next((value for value in items if value["item_id"] == item_id), None)
            if target is None:
                _fail("item_not_found", "The scan item is unavailable")
            if target["item_revision"] != item_revision:
                _fail("stale_revision", "The scan item revision is no longer current")
            if (target.get("identity_confirmation_required") is not True
                    or target.get("identity_confirmation_source") == "user"):
                _fail("identity_confirmation_not_required", "This item is not awaiting identity confirmation")
            original_name = target["name_zh"]
            target["item_revision"] += 1
            target["name_zh"] = confirmed_name
            if confirmed_name != original_name:
                target["brand"] = None
                target["variant"] = None
            target["identity_confirmation_required"] = False
            target["identity_confirmation_source"] = "user"
            target["identity_confirmation_id"] = confirmation_id
            checked = _items(items)
            digest = item_set_hash(checked)
            next_revision = from_revision + 1
            if self._row(scan_id, next_revision) is not None:
                _fail("revision_conflict", "Next scan revision already exists")
            now_text = utc_iso()
            self.sql.execute(
                "UPDATE nutrition_scan_contexts SET status = ?, updated_at = ? "
                "WHERE scan_id = ? AND scan_revision = ? AND status = ?",
                ("superseded", now_text, scan_id, from_revision, "active"),
            )
            inserted = self.sql.execute(
                "INSERT INTO nutrition_scan_contexts "
                "(scan_id, scan_revision, user_id, item_set_hash, items, issued_at, expires_at, status, consumed_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (scan_id, next_revision, user_id, digest, to_json(checked), float(issued_at),
                 float(expires_at), "active", None, now_text, now_text),
            )
            if inserted != 1:
                _fail("revision_conflict", "Next scan revision could not be recorded")
            return self._document(self._row(scan_id, next_revision))

    def get_scan_context(self, *, user_id, scan_id, scan_revision, include_inactive=False, now=None):
        user_id = _id(user_id, "user_id")
        scan_id = _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        current = _clock_value(self.clock) if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
            _fail("invalid_clock", "The scan context clock is invalid")
        with self._lock:
            row = self._row(scan_id, scan_revision)
            document = self._document(row)
            if document is None:
                return None
            if document["user_id"] != user_id:
                _fail("wrong_user", "Scan context belongs to another user")
            if document["status"] == "active" and float(current) >= document["expires_at"]:
                self._expire_locked(document)
                document["status"] = "expired"
            if not include_inactive and document["status"] != "active":
                return None
            return deepcopy(document)

    def assert_complete_item_set(self, *, user_id, scan_id, scan_revision, items, include_inactive=False, now=None):
        """Verify that supplied items are exactly the stored set, including revisions."""
        user_id, scan_id, scan_revision, checked, _ = self._check_common(
            user_id=user_id, scan_id=scan_id, scan_revision=scan_revision, items=items, now=now)
        document = self.get_scan_context(user_id=user_id, scan_id=scan_id, scan_revision=scan_revision,
                                         include_inactive=include_inactive, now=now)
        if document is None:
            _fail("scan_unavailable", "Scan context is missing, expired, or consumed")
        if document["item_set_hash"] != item_set_hash(checked):
            _fail("item_set_mismatch", "Enrichment items do not match the complete scan item set")
        return document

    def _expire_locked(self, document):
        if document["status"] != "active":
            return
        if self.durable:
            self.sql.execute(
                "UPDATE nutrition_scan_contexts SET status = ?, updated_at = ? "
                "WHERE scan_id = ? AND scan_revision = ? AND status = ?",
                ("expired", utc_iso(), document["scan_id"], document["scan_revision"], "active"))
        else:
            current = self._contexts.get((document["scan_id"], document["scan_revision"]))
            if current:
                current["status"] = "expired"
                current["updated_at"] = utc_iso()

    def consume_scan_context(self, *, user_id, scan_id, scan_revision, items, jti=None, now=None):
        """Atomically validate and consume an active context, optionally recording token JTI."""
        user_id, scan_id, scan_revision, checked, current = self._check_common(
            user_id=user_id, scan_id=scan_id, scan_revision=scan_revision, items=items, now=now)
        if jti is not None:
            _id(jti, "jti", MAX_JTI)
        digest = item_set_hash(checked)
        with self._lock:
            transaction = self.sql.transaction() if self.durable else _MemoryTransaction()
            with transaction:
                row = self._row(scan_id, scan_revision)
                document = self._document(row)
                if document is None:
                    _fail("scan_not_found", "Scan context does not exist")
                if document["user_id"] != user_id:
                    _fail("wrong_user", "Scan context belongs to another user")
                if document["item_set_hash"] != digest:
                    _fail("item_set_mismatch", "Enrichment items do not match the complete scan item set")
                if document["status"] == "consumed":
                    _fail("replayed", "Scan context has already been consumed")
                if document["status"] == "expired":
                    _fail("expired", "Scan context has expired")
                if document["status"] == "revoked":
                    _fail("revoked", "Scan context has been revoked")
                if document["status"] == "superseded":
                    _fail("stale_revision", "Scan context revision is no longer current")
                expired = current >= document["expires_at"]
                if expired:
                    if self.durable:
                        self.sql.execute("UPDATE nutrition_scan_contexts SET status = ?, updated_at = ? WHERE scan_id = ? AND scan_revision = ?",
                                         ("expired", utc_iso(), scan_id, scan_revision))
                    else:
                        context = self._contexts[(scan_id, scan_revision)]
                        context["status"] = "expired"
                    document["status"] = "expired"
                else:
                    if jti is not None:
                        replay = self._replay(jti)
                        if replay:
                            if replay["user_id"] != user_id or replay["scan_id"] != scan_id or int(replay["scan_revision"]) != scan_revision:
                                _fail("replay_conflict", "Authority JTI is bound to another scan")
                            _fail("replayed", "Authority token has already been consumed")
                        self._insert_replay(jti, user_id, scan_id, scan_revision, current)
                    if self.durable:
                        self.sql.execute(
                            "UPDATE nutrition_scan_contexts SET status = ?, consumed_at = ?, updated_at = ? "
                            "WHERE scan_id = ? AND scan_revision = ? AND status = ?",
                            ("consumed", current, utc_iso(), scan_id, scan_revision, "active"))
                    else:
                        context = self._contexts[(scan_id, scan_revision)]
                        context["status"], context["consumed_at"], context["updated_at"] = "consumed", current, utc_iso()
                    document["status"], document["consumed_at"] = "consumed", current
            if expired:
                _fail("expired", "Scan context has expired")
            return document

    def _replay(self, jti):
        if self.durable:
            return self.sql.query_one(
                "SELECT jti, user_id, scan_id, scan_revision, consumed_at FROM nutrition_scan_authority_replays WHERE jti = ?",
                (jti,))
        return self._replays.get(jti)

    def _insert_replay(self, jti, user_id, scan_id, scan_revision, consumed_at):
        if self.durable:
            inserted = self.sql.execute(
                "INSERT INTO nutrition_scan_authority_replays "
                "(jti, user_id, scan_id, scan_revision, consumed_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (jti) DO NOTHING",
                (jti, user_id, scan_id, scan_revision, consumed_at))
            if inserted == 0:
                replay = self._replay(jti)
                if replay:
                    _fail("replayed", "Authority token has already been consumed")
                _fail("replay_conflict", "Authority JTI could not be recorded")
        else:
            if jti in self._replays:
                _fail("replayed", "Authority token has already been consumed")
            self._replays[jti] = {"jti": jti, "user_id": user_id, "scan_id": scan_id,
                                  "scan_revision": scan_revision, "consumed_at": consumed_at}

    def revoke_scan_context(self, *, user_id, scan_id, scan_revision, reason=None):
        user_id = _id(user_id, "user_id")
        scan_id = _id(scan_id, "scan_id")
        scan_revision = _revision(scan_revision)
        if reason is not None:
            _id(reason, "reason", 512)
        with self._lock:
            row = self._row(scan_id, scan_revision)
            document = self._document(row)
            if document is None:
                return None
            if document["user_id"] != user_id:
                _fail("wrong_user", "Scan context belongs to another user")
            if document["status"] == "consumed":
                _fail("already_consumed", "Consumed scan context cannot be revoked")
            if self.durable:
                self.sql.execute("UPDATE nutrition_scan_contexts SET status = ?, updated_at = ? WHERE scan_id = ? AND scan_revision = ?",
                                 ("revoked", utc_iso(), scan_id, scan_revision))
            else:
                self._contexts[(scan_id, scan_revision)]["status"] = "revoked"
            document["status"] = "revoked"
            return document


class _MemoryTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        return False

