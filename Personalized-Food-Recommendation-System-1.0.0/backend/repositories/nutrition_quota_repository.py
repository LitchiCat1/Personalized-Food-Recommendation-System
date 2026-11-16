"""Durable user/global quota accounting for nutrition enrichment.

The repository is intentionally independent from the HTTP route and provider
client.  A reservation is the unit charged to both the user and global quota:
it is created atomically, then either consumed by a terminal provider outcome
or released by a retryable failure.  ``not_found`` is a consumed outcome; this
repository does not store a successful nutrition result or turn it into a
cache hit.
"""

import copy
import math
import threading
import time

from repositories.sqlite_db import utc_iso


MAX_ID = 256
RETRYABLE_STATUSES = {"timeout", "rate_limited", "upstream_error", "busy"}
NOT_FOUND_STATUS = "not_found"
SUCCESS_STATUSES = {"accepted", "partial", "complete", "success"}
CONSUMING_STATUSES = SUCCESS_STATUSES | {NOT_FOUND_STATUS, "invalid_output", "source_conflict"}
ALL_STATUSES = RETRYABLE_STATUSES | CONSUMING_STATUSES


class NutritionQuotaRepositoryError(ValueError):
    """Typed quota boundary error; HTTP code mapping belongs to the route."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_quota_user_windows (
    quota_window INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    reserved_count INTEGER NOT NULL DEFAULT 0 CHECK (reserved_count >= 0),
    consumed_count INTEGER NOT NULL DEFAULT 0 CHECK (consumed_count >= 0),
    PRIMARY KEY (quota_window, user_id)
);
CREATE TABLE IF NOT EXISTS nutrition_quota_global_windows (
    quota_window INTEGER PRIMARY KEY,
    reserved_count INTEGER NOT NULL DEFAULT 0 CHECK (reserved_count >= 0),
    consumed_count INTEGER NOT NULL DEFAULT 0 CHECK (consumed_count >= 0)
);
CREATE TABLE IF NOT EXISTS nutrition_quota_reservations (
    reservation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    quota_window INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nutrition_quota_reservations_user
    ON nutrition_quota_reservations (user_id, quota_window);
"""


def _text(value, field):
    if (not isinstance(value, str) or not value or len(value) > MAX_ID
            or value.strip() != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise NutritionQuotaRepositoryError("invalid_id", f"{field} is invalid")
    return value


def _status(value):
    if not isinstance(value, str) or value not in ALL_STATUSES:
        raise NutritionQuotaRepositoryError("invalid_outcome", "Unsupported quota outcome")
    return value


class NutritionQuotaRepository:
    """SQLite quota repository with an explicit memory test mode."""

    def __init__(self, sql=None, *, per_user_limit=2, global_limit=2,
                 window_seconds=86400, clock=time.time):
        for value, field in ((per_user_limit, "per_user_limit"),
                             (global_limit, "global_limit"),
                             (window_seconds, "window_seconds")):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise NutritionQuotaRepositoryError("invalid_quota", f"{field} is invalid")
        if not callable(clock):
            raise NutritionQuotaRepositoryError("invalid_clock", "A clock callable is required")
        self.sql = sql
        self.durable = sql is not None
        if self.durable and getattr(sql, "dialect", None) != "sqlite":
            raise NutritionQuotaRepositoryError(
                "unsupported_database", "Quota repository requires SQLite")
        self.per_user_limit = per_user_limit
        self.global_limit = global_limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._lock = threading.RLock()
        self._user_windows = {}
        self._global_windows = {}
        self._reservations = {}
        if self.durable:
            self.sql.executescript(SQLITE_TABLES)

    def _window(self):
        now = self.clock()
        try:
            finite = math.isfinite(now)
        except (TypeError, OverflowError):
            finite = False
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not finite:
            raise NutritionQuotaRepositoryError("invalid_clock", "The quota clock is invalid")
        return int(now // self.window_seconds)

    def _reservation_row(self, reservation_id):
        return self.sql.query_one(
            "SELECT reservation_id, user_id, quota_window, status, created_at, updated_at "
            "FROM nutrition_quota_reservations WHERE reservation_id = ?",
            (reservation_id,))

    def _user_row(self, window, user_id):
        return self.sql.query_one(
            "SELECT quota_window, user_id, reserved_count, consumed_count "
            "FROM nutrition_quota_user_windows WHERE quota_window = ? AND user_id = ?",
            (window, user_id))

    def _global_row(self, window):
        return self.sql.query_one(
            "SELECT quota_window, reserved_count, consumed_count "
            "FROM nutrition_quota_global_windows WHERE quota_window = ?",
            (window,))

    @staticmethod
    def _document(row):
        if not row:
            return None
        return {
            "reservation_id": row["reservation_id"],
            "user_id": row["user_id"],
            "window": int(row["quota_window"]),
            "status": row["status"],
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _counter(row):
        if not row:
            return {"reserved_count": 0, "consumed_count": 0}
        return {"reserved_count": int(row["reserved_count"]),
                "consumed_count": int(row["consumed_count"])}

    def _ensure_rows(self, window, user_id):
        self.sql.execute(
            "INSERT INTO nutrition_quota_global_windows "
            "(quota_window, reserved_count, consumed_count) VALUES (?, 0, 0) "
            "ON CONFLICT (quota_window) DO NOTHING", (window,))
        self.sql.execute(
            "INSERT INTO nutrition_quota_user_windows "
            "(quota_window, user_id, reserved_count, consumed_count) VALUES (?, ?, 0, 0) "
            "ON CONFLICT (quota_window, user_id) DO NOTHING", (window, user_id))

    def reserve(self, *, user_id, reservation_id):
        """Atomically reserve one user and one global quota slot.

        Repeating the same reservation ID for the same user is idempotent and
        returns the existing state.  A reservation ID cannot move between
        users, which prevents a caller from replaying another user's lease.
        """
        user_id = _text(user_id, "user_id")
        reservation_id = _text(reservation_id, "reservation_id")
        if self.durable:
            window = self._window()
            with self.sql.transaction():
                # A reservation ID is globally unique.  The first read is a
                # fast idempotency path, but it cannot protect a missing row
                # SQLite's BEGIN IMMEDIATE serializes writers before the
                # counters and reservation are read; the insert is also
                # conflict-safe if another process committed first.
                existing = self._reservation_row(reservation_id)
                if existing:
                    if existing["user_id"] != user_id:
                        raise NutritionQuotaRepositoryError(
                            "ownership_conflict", "Reservation belongs to another user")
                    return self._document(existing)
                self._ensure_rows(window, user_id)
                global_row = self._global_row(window)
                user_row = self._user_row(window, user_id)
                existing = self._reservation_row(reservation_id)
                if existing:
                    if existing["user_id"] != user_id:
                        raise NutritionQuotaRepositoryError(
                            "ownership_conflict", "Reservation belongs to another user")
                    return self._document(existing)
                global_count = self._counter(global_row)
                user_count = self._counter(user_row)
                if user_count["reserved_count"] + user_count["consumed_count"] >= self.per_user_limit:
                    raise NutritionQuotaRepositoryError(
                        "user_quota_exceeded", "The user enrichment quota is exhausted")
                if global_count["reserved_count"] + global_count["consumed_count"] >= self.global_limit:
                    raise NutritionQuotaRepositoryError(
                        "global_quota_exceeded", "The global enrichment quota is exhausted")
                now = utc_iso()
                inserted = self.sql.execute(
                    "INSERT INTO nutrition_quota_reservations "
                    "(reservation_id, user_id, quota_window, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (reservation_id) DO NOTHING",
                    (reservation_id, user_id, window, "pending", now, now))
                if not inserted:
                    # This can only happen when another transaction won the
                    # same reservation ID race.  Do not charge quota twice.
                    existing = self._reservation_row(reservation_id)
                    if not existing:
                        raise NutritionQuotaRepositoryError(
                            "quota_race", "Reservation conflict could not be reloaded")
                    if existing["user_id"] != user_id:
                        raise NutritionQuotaRepositoryError(
                            "ownership_conflict", "Reservation belongs to another user")
                    return self._document(existing)
                self.sql.execute(
                    "UPDATE nutrition_quota_global_windows SET reserved_count = reserved_count + 1 "
                    "WHERE quota_window = ?", (window,))
                self.sql.execute(
                    "UPDATE nutrition_quota_user_windows SET reserved_count = reserved_count + 1 "
                    "WHERE quota_window = ? AND user_id = ?", (window, user_id))
                return self._document(self._reservation_row(reservation_id))
        with self._lock:
            existing = self._reservations.get(reservation_id)
            if existing:
                if existing["user_id"] != user_id:
                    raise NutritionQuotaRepositoryError(
                        "ownership_conflict", "Reservation belongs to another user")
                return copy.deepcopy(existing)
            window = self._window()
            global_count = self._global_windows.setdefault(window, {"reserved_count": 0, "consumed_count": 0})
            user_count = self._user_windows.setdefault((window, user_id), {"reserved_count": 0, "consumed_count": 0})
            if user_count["reserved_count"] + user_count["consumed_count"] >= self.per_user_limit:
                raise NutritionQuotaRepositoryError(
                    "user_quota_exceeded", "The user enrichment quota is exhausted")
            if global_count["reserved_count"] + global_count["consumed_count"] >= self.global_limit:
                raise NutritionQuotaRepositoryError(
                    "global_quota_exceeded", "The global enrichment quota is exhausted")
            now = utc_iso()
            document = {"reservation_id": reservation_id, "user_id": user_id,
                        "window": window, "status": "pending",
                        "created_at": now, "updated_at": now}
            global_count["reserved_count"] += 1
            user_count["reserved_count"] += 1
            self._reservations[reservation_id] = document
            return copy.deepcopy(document)

    def get_reservation(self, reservation_id, *, user_id=None):
        reservation_id = _text(reservation_id, "reservation_id")
        if user_id is not None:
            user_id = _text(user_id, "user_id")
        row = self._reservation_row(reservation_id) if self.durable else self._reservations.get(reservation_id)
        document = self._document(row) if self.durable else copy.deepcopy(row)
        if document is None:
            return None
        if user_id is not None and document["user_id"] != user_id:
            raise NutritionQuotaRepositoryError(
                "ownership_conflict", "Reservation belongs to another user")
        return document

    def finish(self, *, user_id, reservation_id, status):
        """Finalize a reservation and update both quota counters atomically."""
        user_id = _text(user_id, "user_id")
        reservation_id = _text(reservation_id, "reservation_id")
        status = _status(status)
        if self.durable:
            with self.sql.transaction():
                row = self._reservation_row(reservation_id)
                if not row:
                    raise NutritionQuotaRepositoryError("not_found", "Quota reservation does not exist")
                if row["user_id"] != user_id:
                    raise NutritionQuotaRepositoryError(
                        "ownership_conflict", "Reservation belongs to another user")
                current = row["status"]
                if current != "pending":
                    if current == status:
                        return self._document(row)
                    raise NutritionQuotaRepositoryError(
                        "already_completed", "The quota reservation has already completed")
                window = int(row["quota_window"])
                user_row = self._user_row(window, user_id)
                global_row = self._global_row(window)
                if not user_row or not global_row:
                    raise NutritionQuotaRepositoryError("quota_corrupt", "Quota counters are missing")
                if int(user_row["reserved_count"]) <= 0 or int(global_row["reserved_count"]) <= 0:
                    raise NutritionQuotaRepositoryError("quota_corrupt", "Quota reservation count is invalid")
                self.sql.execute(
                    "UPDATE nutrition_quota_user_windows SET reserved_count = reserved_count - 1" 
                    + (", consumed_count = consumed_count + 1" if status in CONSUMING_STATUSES else "")
                    + " WHERE quota_window = ? AND user_id = ?", (window, user_id))
                self.sql.execute(
                    "UPDATE nutrition_quota_global_windows SET reserved_count = reserved_count - 1"
                    + (", consumed_count = consumed_count + 1" if status in CONSUMING_STATUSES else "")
                    + " WHERE quota_window = ?", (window,))
                now = utc_iso()
                self.sql.execute(
                    "UPDATE nutrition_quota_reservations SET status = ?, updated_at = ? "
                    "WHERE reservation_id = ?", (status, now, reservation_id))
                return self._document(self._reservation_row(reservation_id))
        with self._lock:
            row = self._reservations.get(reservation_id)
            if not row:
                raise NutritionQuotaRepositoryError("not_found", "Quota reservation does not exist")
            if row["user_id"] != user_id:
                raise NutritionQuotaRepositoryError(
                    "ownership_conflict", "Reservation belongs to another user")
            current = row["status"]
            if current != "pending":
                if current == status:
                    return copy.deepcopy(row)
                raise NutritionQuotaRepositoryError(
                    "already_completed", "The quota reservation has already completed")
            window = row["window"]
            user_count = self._user_windows.get((window, user_id))
            global_count = self._global_windows.get(window)
            if not user_count or not global_count or user_count["reserved_count"] <= 0 or global_count["reserved_count"] <= 0:
                raise NutritionQuotaRepositoryError("quota_corrupt", "Quota reservation count is invalid")
            user_count["reserved_count"] -= 1
            global_count["reserved_count"] -= 1
            if status in CONSUMING_STATUSES:
                user_count["consumed_count"] += 1
                global_count["consumed_count"] += 1
            row["status"] = status
            row["updated_at"] = utc_iso()
            return copy.deepcopy(row)

    def release(self, *, user_id, reservation_id, status="upstream_error"):
        """Release a reservation after a retryable provider failure."""
        if status not in RETRYABLE_STATUSES:
            raise NutritionQuotaRepositoryError(
                "invalid_outcome", "Quota release requires a retryable outcome")
        return self.finish(user_id=user_id, reservation_id=reservation_id, status=status)

    def commit(self, *, user_id, reservation_id, status="success"):
        """Consume a reservation; ``not_found`` is deliberately consumed too."""
        if status not in CONSUMING_STATUSES:
            raise NutritionQuotaRepositoryError(
                "invalid_outcome", "Quota commit requires a terminal outcome")
        return self.finish(user_id=user_id, reservation_id=reservation_id, status=status)

    def quota_snapshot(self, user_id):
        user_id = _text(user_id, "user_id")
        window = self._window()
        if self.durable:
            user_row = self._user_row(window, user_id)
            global_row = self._global_row(window)
        else:
            user_row = self._user_windows.get((window, user_id))
            global_row = self._global_windows.get(window)
        user_count = self._counter(user_row)
        global_count = self._counter(global_row)
        user_used = user_count["reserved_count"] + user_count["consumed_count"]
        global_used = global_count["reserved_count"] + global_count["consumed_count"]
        return {
            "window": window,
            "user_id": user_id,
            "per_user_limit": self.per_user_limit,
            "global_limit": self.global_limit,
            "user_reserved": user_count["reserved_count"],
            "user_consumed": user_count["consumed_count"],
            "user_used": user_used,
            "user_remaining": max(0, self.per_user_limit - user_used),
            "global_reserved": global_count["reserved_count"],
            "global_consumed": global_count["consumed_count"],
            "global_used": global_used,
            "global_remaining": max(0, self.global_limit - global_used),
        }


__all__ = [
    "ALL_STATUSES", "CONSUMING_STATUSES", "NOT_FOUND_STATUS",
    "RETRYABLE_STATUSES", "SQLITE_TABLES",
    "NutritionQuotaRepository", "NutritionQuotaRepositoryError",
]
