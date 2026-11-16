"""Policy-gated successful nutrition profile cache.

The cache is deliberately narrower than the profile repository.  It stores
only a server-validated successful profile; ``not_found`` and all provider
failures have no write API and therefore cannot become negative cache entries.
Every read rechecks the current source policy revision and rights so a source
withdrawal or policy change immediately turns an old entry into a miss.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import threading
import time

from repositories.nutrition_profile_repository import profile_hash
from repositories.sqlite_db import from_json, to_json


MAX_ID = 256
MAX_IDENTITY_NAME = 300
MAX_PROFILE_BYTES = 768 * 1024
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_TTL_SECONDS = 90 * 24 * 60 * 60
_HEX = frozenset("0123456789abcdef")
_IDENTITY_FIELDS = ("name", "food_state", "preparation_method", "components_scope", "brand", "variant")
_IDENTITY_ENUMS = {
    "food_state": {"prepared", "raw", "dry", "unknown"},
    "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised", "steamed", "mixed", "unknown"},
    "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides", "unknown"},
}


class NutritionCacheRepositoryError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_profile_cache (
    cache_key TEXT PRIMARY KEY,
    base_key TEXT NOT NULL,
    cache_scope TEXT NOT NULL,
    owner_user_id TEXT,
    source_id TEXT NOT NULL,
    source_policy_id TEXT NOT NULL,
    source_policy_revision INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    retrieval_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    food_identity TEXT NOT NULL,
    profile TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nutrition_profile_cache_base
    ON nutrition_profile_cache (base_key, cache_scope, owner_user_id);
"""


def _fail(code, message):
    raise NutritionCacheRepositoryError(code, message)


def _text(value, field, maximum=MAX_ID):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail("invalid_value", f"{field} is invalid")
    return value


def _revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("invalid_value", "source_policy_revision is invalid")
    return value


def _finite_clock(clock):
    value = clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_clock", "The cache clock is invalid")
    return float(value)


def _iso(value):
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _parse_time(value):
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _canonical(value, *, limit=MAX_PROFILE_BYTES, field="value"):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise NutritionCacheRepositoryError("invalid_value", f"{field} must be finite JSON") from error
    if len(encoded) > limit:
        _fail("oversized_value", f"{field} exceeds the cache size budget")
    return encoded


def _identity(identity):
    if not isinstance(identity, dict) or set(identity) != set(_IDENTITY_FIELDS):
        _fail("invalid_identity", "food_identity fields are invalid")
    name = identity.get("name")
    if (not isinstance(name, str) or not name or name.strip() != name
            or len(name) > MAX_IDENTITY_NAME
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        _fail("invalid_identity", "food_identity.name is invalid")
    for field, values in _IDENTITY_ENUMS.items():
        if identity.get(field) not in values:
            _fail("invalid_identity", f"food_identity.{field} is invalid")
    for field in ("brand", "variant"):
        value = identity.get(field)
        if value is not None and (not isinstance(value, str) or not value or value.strip() != value
                                  or len(value) > MAX_IDENTITY_NAME
                                  or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            _fail("invalid_identity", f"food_identity.{field} is invalid")
    return deepcopy(identity)


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX for char in value.lower()):
        _fail("invalid_provenance", "content_hash is invalid")
    return value.lower()


def _policy_rights(source):
    if not isinstance(source, dict):
        _fail("source_unavailable", "Source policy is missing or withdrawn")
    if source.get("status") != "active":
        _fail("source_unavailable", "Source policy is missing or withdrawn")
    policy = source.get("policy")
    rights = policy.get("rights") if isinstance(policy, dict) else None
    spec = policy.get("source_spec") if isinstance(policy, dict) else None
    if not isinstance(rights, dict) or not isinstance(spec, dict):
        _fail("invalid_policy", "Source policy rights are incomplete")
    if not rights.get("snapshot_allowed") or not rights.get("reuse_allowed"):
        _fail("rights_not_allowed", "Source policy does not allow profile caching")
    reuse_scope = rights.get("reuse_scope")
    cache_scope = rights.get("provider_cache_scope")
    if reuse_scope == "cross_user":
        if cache_scope != "cross_user_approved":
            _fail("reuse_not_allowed", "Cross-user cache reuse is not approved")
        scope = "cross_user"
    elif reuse_scope == "server_internal":
        if cache_scope not in ("server_internal", "cross_user_approved"):
            _fail("reuse_not_allowed", "Server-internal cache reuse is not approved")
        scope = "server_internal"
    else:
        _fail("reuse_not_allowed", "Source policy does not permit a reusable cache")
    return policy, rights, spec, scope


class NutritionProfileCacheRepository:
    """TTL cache whose entries are valid only under their current source policy."""

    def __init__(self, source_repository, sql=None, *, clock=time.time,
                 default_ttl_seconds=DEFAULT_TTL_SECONDS):
        if source_repository is None or not hasattr(source_repository, "get_source_policy"):
            _fail("invalid_repository", "A source policy repository is required")
        if (isinstance(default_ttl_seconds, bool) or not isinstance(default_ttl_seconds, (int, float))
                or not math.isfinite(default_ttl_seconds) or default_ttl_seconds <= 0
                or default_ttl_seconds > MAX_TTL_SECONDS):
            _fail("invalid_ttl", "default_ttl_seconds is invalid")
        if not callable(clock):
            _fail("invalid_clock", "A cache clock is required")
        self.source_repository = source_repository
        self.sql = sql
        self.durable = sql is not None
        if self.durable and getattr(sql, "dialect", None) != "sqlite":
            _fail("unsupported_database", "Nutrition cache requires SQLite")
        self.clock = clock
        self.default_ttl_seconds = float(default_ttl_seconds)
        self._lock = threading.RLock()
        self._entries = {}
        if self.durable:
            self.sql.executescript(SQLITE_TABLES)

    @staticmethod
    def cache_key(*, food_identity, source_id, source_policy_id, source_policy_revision,
                  source_url, adapter_version, retrieval_version, owner_user_id=None,
                  cache_scope=None, content_hash=None):
        """Return the canonical key; every authority/version dimension is bound."""
        identity = _identity(food_identity)
        values = {
            "food_identity": identity,
            "source_id": _text(source_id, "source_id"),
            "source_policy_id": _text(source_policy_id, "source_policy_id"),
            "source_policy_revision": _revision(source_policy_revision),
            "source_url": _text(source_url, "source_url", 4096),
            "adapter_version": _text(adapter_version, "adapter_version"),
            "retrieval_version": _text(retrieval_version, "retrieval_version"),
            "owner_user_id": owner_user_id,
            "cache_scope": cache_scope,
            "content_hash": content_hash,
        }
        if owner_user_id is not None:
            values["owner_user_id"] = _text(owner_user_id, "owner_user_id")
        if cache_scope is not None:
            if cache_scope not in ("cross_user", "server_internal"):
                _fail("invalid_value", "cache_scope is invalid")
        if content_hash is not None:
            values["content_hash"] = _hash(content_hash)
        return hashlib.sha256(_canonical(values, field="cache_key")).hexdigest()

    @staticmethod
    def _base_key(**kwargs):
        kwargs = dict(kwargs)
        kwargs["owner_user_id"] = None
        return NutritionProfileCacheRepository.cache_key(**kwargs)

    def _source(self, source_id, revision):
        try:
            resolver = getattr(self.source_repository,
                               "resolve_source_policy_reference", None)
            source = (resolver(source_id) if callable(resolver) else
                      self.source_repository.get_source_policy(source_id))
        except Exception as error:
            if getattr(error, "code", None) in {"invalid_id", "revision_conflict"}:
                _fail("source_unavailable", "Source policy is missing or withdrawn")
            raise
        if source is None or source.get("revision") != revision or source.get("status") != "active":
            _fail("source_unavailable", "Source policy is missing or withdrawn")
        return source

    def _row(self, cache_key):
        return self.sql.query_one(
            "SELECT cache_key, base_key, cache_scope, owner_user_id, source_id, source_policy_id, "
            "source_policy_revision, source_url, adapter_version, retrieval_version, content_hash, "
            "profile_hash, food_identity, profile, created_at, expires_at "
            "FROM nutrition_profile_cache WHERE cache_key = ?", (cache_key,))

    @staticmethod
    def _document(row):
        if not row:
            return None
        return {
            "cache_key": row["cache_key"], "base_key": row["base_key"],
            "cache_scope": row["cache_scope"], "owner_user_id": row["owner_user_id"],
            "source_id": row["source_id"], "source_policy_id": row["source_policy_id"],
            "source_policy_revision": int(row["source_policy_revision"]),
            "source_url": row["source_url"], "adapter_version": row["adapter_version"],
            "retrieval_version": row["retrieval_version"], "content_hash": row["content_hash"],
            "profile_hash": row["profile_hash"],
            "food_identity": deepcopy(from_json(row["food_identity"])),
            "profile": deepcopy(from_json(row["profile"])),
            "created_at": row["created_at"], "expires_at": row["expires_at"],
        }

    def put_success(self, *, food_identity, profile, source_id, source_policy_revision,
                    user_id=None, ttl_seconds=None):
        """Persist one successful profile if current source rights allow reuse."""
        identity = _identity(food_identity)
        source_id = _text(source_id, "source_id")
        revision = _revision(source_policy_revision)
        if user_id is not None:
            user_id = _text(user_id, "user_id")
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl)
                or ttl <= 0 or ttl > MAX_TTL_SECONDS):
            _fail("invalid_ttl", "ttl_seconds is invalid")
        source = self._source(source_id, revision)
        # Keep the public cache API compatible with policy-id callers while
        # storing and querying only the canonical source id.
        source_id = source["source_id"]
        policy, rights, spec, scope = _policy_rights(source)
        target = policy.get("target_identity")
        accepted_names = policy.get("accepted_names")
        if (not isinstance(target, dict) or not isinstance(accepted_names, (list, tuple))
                or identity["name"] not in accepted_names
                or any(identity[field] != target.get(field) for field in _IDENTITY_FIELDS[1:])):
            _fail("source_conflict", "Food identity does not match the reviewed source policy")
        if scope == "server_internal" and user_id is None:
            _fail("owner_required", "Server-internal cache entries require an owner user")
        if scope == "cross_user":
            user_id = None
        details = profile.get("source_details") if isinstance(profile, dict) else None
        if not isinstance(details, dict):
            _fail("invalid_provenance", "Profile source details are required")
        if (details.get("source_id") != source_id or details.get("source_url") != spec.get("source_url")
                or details.get("adapter_version") != spec.get("adapter_version")):
            _fail("source_conflict", "Profile provenance does not match the source policy")
        content_hash = _hash(details.get("content_hash"))
        retrieval_version = _text(details.get("retrieval_version"), "retrieval_version")
        digest = profile_hash(profile)
        _canonical(profile, field="profile")
        policy_id = _text(policy.get("policy_id"), "source_policy_id")
        source_url = _text(spec.get("source_url"), "source_url", 4096)
        adapter_version = _text(spec.get("adapter_version"), "adapter_version")
        key_args = {"food_identity": identity, "source_id": source_id,
                    "source_policy_id": policy_id, "source_policy_revision": revision,
                    "source_url": source_url, "adapter_version": adapter_version,
                    "retrieval_version": retrieval_version, "owner_user_id": user_id,
                    "cache_scope": scope, "content_hash": content_hash}
        cache_key = self.cache_key(**key_args)
        base_key = self._base_key(**key_args)
        now = _finite_clock(self.clock)
        created = _iso(now)
        expires = _iso(now + float(ttl))
        values = (cache_key, base_key, scope, user_id, source_id, policy_id, revision,
                  source_url, adapter_version, retrieval_version, content_hash, digest,
                  to_json(identity), to_json(profile), created, expires)
        if self.durable:
            with self.sql.transaction():
                self.sql.execute(
                    "INSERT INTO nutrition_profile_cache "
                    "(cache_key, base_key, cache_scope, owner_user_id, source_id, source_policy_id, "
                    "source_policy_revision, source_url, adapter_version, retrieval_version, content_hash, "
                    "profile_hash, food_identity, profile, created_at, expires_at) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (cache_key) DO UPDATE SET base_key = excluded.base_key, "
                    "cache_scope = excluded.cache_scope, owner_user_id = excluded.owner_user_id, "
                    "profile_hash = excluded.profile_hash, food_identity = excluded.food_identity, "
                    "profile = excluded.profile, created_at = excluded.created_at, expires_at = excluded.expires_at",
                    values)
                return self.get(food_identity=identity, source_id=source_id,
                                source_policy_revision=revision, user_id=user_id)
        with self._lock:
            self._entries[cache_key] = {
                "cache_key": cache_key, "base_key": base_key, "cache_scope": scope,
                "owner_user_id": user_id, "source_id": source_id, "source_policy_id": policy_id,
                "source_policy_revision": revision, "source_url": source_url,
                "adapter_version": adapter_version, "retrieval_version": retrieval_version,
                "content_hash": content_hash, "profile_hash": digest,
                "food_identity": deepcopy(identity), "profile": deepcopy(profile),
                "created_at": created, "expires_at": expires,
            }
            return deepcopy(self._entries[cache_key])

    def get(self, *, food_identity, source_id, source_policy_revision, user_id=None):
        """Read a valid positive entry; stale, withdrawn or expired entries miss."""
        identity = _identity(food_identity)
        source_id = _text(source_id, "source_id")
        revision = _revision(source_policy_revision)
        if user_id is not None:
            user_id = _text(user_id, "user_id")
        try:
            source = self._source(source_id, revision)
        except NutritionCacheRepositoryError:
            return None
        if source is None or source.get("status") != "active" or source.get("revision") != revision:
            return None
        source_id = source["source_id"]
        policy = source.get("policy") if isinstance(source, dict) else None
        spec = policy.get("source_spec") if isinstance(policy, dict) else None
        if not isinstance(policy, dict) or not isinstance(spec, dict):
            return None
        try:
            _, _, _, scope = _policy_rights(source)
        except NutritionCacheRepositoryError:
            return None
        policy_id = policy.get("policy_id")
        source_url = spec.get("source_url")
        adapter_version = spec.get("adapter_version")
        if not all(isinstance(value, str) and value for value in (policy_id, source_url, adapter_version)):
            return None
        # Retrieval version is part of the key.  Query the bounded base prefix
        # instead of guessing it, then verify every provenance field below.
        candidates = self._candidate_rows(identity, source_id, policy_id, revision,
                                          source_url, adapter_version, user_id, scope)
        now = _finite_clock(self.clock)
        for row in candidates:
            document = self._document(row) if self.durable else deepcopy(row)
            if document is None or (document["cache_scope"] == "server_internal"
                                    and document["owner_user_id"] != user_id):
                continue
            if (_parse_time(document["expires_at"]) is None
                    or _parse_time(document["expires_at"]) <= now):
                continue
            try:
                if profile_hash(document["profile"]) != document["profile_hash"]:
                    continue
            except Exception:
                continue
            return document
        return None

    def _candidate_rows(self, identity, source_id, policy_id, revision, source_url,
                        adapter_version, user_id, scope):
        # The base key includes retrieval_version, so use a small bounded scan
        # over this source/policy identity rather than dropping that dimension.
        if self.durable:
            rows = self.sql.query_all(
                "SELECT cache_key, base_key, cache_scope, owner_user_id, source_id, source_policy_id, "
                "source_policy_revision, source_url, adapter_version, retrieval_version, content_hash, "
                "profile_hash, food_identity, profile, created_at, expires_at "
                "FROM nutrition_profile_cache WHERE source_id = ? AND source_policy_id = ? "
                "AND source_policy_revision = ? AND source_url = ? AND adapter_version = ? "
                "AND cache_scope = ? AND (owner_user_id IS NULL OR owner_user_id = ?) "
                "ORDER BY created_at DESC",
                (source_id, policy_id, revision, source_url, adapter_version, scope, user_id))
            return [row for row in rows if from_json(row["food_identity"]) == identity]
        with self._lock:
            rows = [deepcopy(row) for row in self._entries.values()
                    if row["source_id"] == source_id and row["source_policy_id"] == policy_id
                    and row["source_policy_revision"] == revision and row["source_url"] == source_url
                    and row["adapter_version"] == adapter_version and row["cache_scope"] == scope
                    and (row["owner_user_id"] is None or row["owner_user_id"] == user_id)
                    and row["food_identity"] == identity]
            return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def purge_expired(self, *, limit=1000):
        """Bounded maintenance for TTL rows; source withdrawal remains a read-time miss."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 10000:
            _fail("invalid_limit", "limit is invalid")
        now = _finite_clock(self.clock)
        if self.durable:
            rows = self.sql.query_all(
                "SELECT cache_key, expires_at FROM nutrition_profile_cache "
                "ORDER BY expires_at LIMIT ?", (limit,))
            expired = [row["cache_key"] for row in rows
                       if (_parse_time(row["expires_at"]) or 0) <= now]
            if expired:
                with self.sql.transaction():
                    for cache_key in expired:
                        self.sql.execute("DELETE FROM nutrition_profile_cache WHERE cache_key = ?", (cache_key,))
            return len(expired)
        with self._lock:
            expired = [key for key, row in self._entries.items()
                       if (_parse_time(row["expires_at"]) or 0) <= now][:limit]
            for key in expired:
                del self._entries[key]
            return len(expired)


NutritionCacheRepository = NutritionProfileCacheRepository


__all__ = [
    "DEFAULT_TTL_SECONDS", "MAX_TTL_SECONDS", "SQLITE_TABLES",
    "NutritionCacheRepository", "NutritionCacheRepositoryError", "NutritionProfileCacheRepository",
]
