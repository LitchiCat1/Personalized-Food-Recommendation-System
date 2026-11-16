"""Durable server-owned source policies and nutrition profile snapshots.

This repository is deliberately separate from the HTTP route.  It is the
storage boundary used by a future authority/enrichment route: callers cannot
choose a source policy from request JSON, profile hashes are calculated here,
and updates require an explicit compare-and-set revision.
"""

from copy import deepcopy
import hashlib
import json
import re
import threading

from repositories.sqlite_db import from_json, to_json, utc_iso
from services.nutrition_authority_service import NutritionAuthorityService
from services.fdc_source_policy_service import FdcSourcePolicyError, validate_fdc_source_policy
from services.nutrition_profile_service import NutritionProfileError, validate_profile_consistency
from services.web_nutrition_service import NutritionSourceRegistry, WebNutritionError


MAX_ID = 256
MAX_POLICY_BYTES = 256 * 1024
MAX_PROFILE_BYTES = 768 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_STATUSES = {"active", "withdrawn"}


class NutritionRepositoryError(ValueError):
    """Typed repository boundary error; route code can map ``code`` to HTTP."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_source_policy_versions (
    source_id TEXT NOT NULL,
    policy_revision INTEGER NOT NULL,
    policy_id TEXT NOT NULL,
    status TEXT NOT NULL,
    policy TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_id, policy_revision)
);
CREATE TABLE IF NOT EXISTS nutrition_source_policies (
    source_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    policy_revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    policy TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nutrition_source_policy_status
    ON nutrition_source_policies (status, source_id);
CREATE TABLE IF NOT EXISTS nutrition_profiles (
    profile_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    profile_revision INTEGER NOT NULL,
    profile_hash TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_policy_revision INTEGER NOT NULL,
    reusable INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    food_identity TEXT NOT NULL,
    profile TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nutrition_profiles_user
    ON nutrition_profiles (user_id, profile_id);
CREATE INDEX IF NOT EXISTS idx_nutrition_profiles_source
    ON nutrition_profiles (source_id, source_policy_revision, status);
"""


def _bounded_id(value, field):
    if (not isinstance(value, str) or not value or len(value) > MAX_ID
            or value.strip() != value or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise NutritionRepositoryError("invalid_id", f"{field} is invalid")
    return value


def _canonical(value, *, limit, code="invalid_json"):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise NutritionRepositoryError(code, "Value must be finite canonical JSON") from error
    if len(encoded) > limit:
        raise NutritionRepositoryError("oversized_json", "Value exceeds the repository size budget")
    return encoded


def _revision(value, field="revision"):
    if type(value) is not int or value < 0:
        raise NutritionRepositoryError("invalid_revision", f"{field} is invalid")
    return value


def _identity(identity):
    if not isinstance(identity, dict):
        raise NutritionRepositoryError("invalid_identity", "food_identity must be an object")
    allowed = {"name", "food_state", "preparation_method", "components_scope", "brand", "variant"}
    if set(identity) != allowed:
        raise NutritionRepositoryError("invalid_identity", "food_identity contains unsupported fields")
    if (not isinstance(identity["name"], str) or not identity["name"].strip()
            or identity["name"].strip() != identity["name"] or len(identity["name"]) > 300
            or any(ord(char) < 32 or ord(char) == 127 for char in identity["name"])):
        raise NutritionRepositoryError("invalid_identity", "food_identity.name is invalid")
    enums = {
        "food_state": {"prepared", "raw", "dry", "unknown"},
        "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised", "steamed", "mixed", "unknown"},
        "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides", "unknown"},
    }
    for field, values in enums.items():
        if identity[field] not in values:
            raise NutritionRepositoryError("invalid_identity", f"food_identity.{field} is invalid")
    for field in ("brand", "variant"):
        value = identity[field]
        if (value is not None and
                (not isinstance(value, str) or not value.strip() or value.strip() != value
                 or len(value) > 300 or any(ord(char) < 32 or ord(char) == 127 for char in value))):
            raise NutritionRepositoryError("invalid_identity", f"food_identity.{field} is invalid")
    return deepcopy(identity)


def _policy(policy):
    if not isinstance(policy, dict):
        raise NutritionRepositoryError("invalid_policy", "A source policy is required")
    try:
        # This is the existing reviewed-policy contract.  It intentionally
        # rejects client-shaped policies and unreviewed rights metadata.
        NutritionSourceRegistry([policy])
    except WebNutritionError as error:
        raise NutritionRepositoryError("invalid_policy", str(error)) from None
    # FDC policies use a dedicated provider contract.  Do not make the
    # generic Web/Tavily registry infer fixed endpoint/version semantics.
    candidate_spec = policy.get("source_spec", {})
    # A fixed FDC-looking endpoint must not be downgraded to the generic
    # Web/Tavily contract by changing provider_kind.  Otherwise a caller could
    # bypass the FDC ID/table/version binding while retaining the same source.
    fdc_shape = (isinstance(candidate_spec, dict) and (
        candidate_spec.get("provider_kind") == "usda_fdc_api"
        or "fdc_id" in candidate_spec
        or str(candidate_spec.get("source_id", "")).startswith("usda-fdc-")
        or str(candidate_spec.get("source_url", "")).startswith("https://api.nal.usda.gov/fdc/v1/food/")
        or str(candidate_spec.get("table_id", "")).startswith("fdc-")))
    if fdc_shape:
        try:
            policy = validate_fdc_source_policy(policy)
        except FdcSourcePolicyError as error:
            raise NutritionRepositoryError(error.code, str(error)) from None
    source_id = _bounded_id(policy["source_spec"]["source_id"], "source_id")
    policy_id = _bounded_id(policy["policy_id"], "policy_id")
    _canonical(policy, limit=MAX_POLICY_BYTES, code="invalid_policy")
    return deepcopy(policy), source_id, policy_id


def _profile(profile):
    _canonical(profile, limit=MAX_PROFILE_BYTES, code="invalid_profile")
    try:
        validate_profile_consistency(profile, [])
    except NutritionProfileError as error:
        raise NutritionRepositoryError("invalid_profile", str(error)) from None
    return deepcopy(profile)


def profile_hash(profile):
    """Return the same canonical hash used by ``NutritionAuthorityService``."""
    checked = _profile(profile)
    try:
        return NutritionAuthorityService.profile_hash(checked)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise NutritionRepositoryError("invalid_profile", "Profile cannot be signed") from error


def _row_json(row, field):
    return from_json(row[field])


class NutritionProfileSourceRepository:
    """SQLite repository with an explicit non-durable memory mode."""

    def __init__(self, sql=None):
        self.sql = sql
        self.durable = sql is not None
        if self.durable and getattr(sql, "dialect", None) != "sqlite":
            raise NutritionRepositoryError("unsupported_database", "Nutrition repository requires SQLite")
        self._lock = threading.RLock()
        self._sources = {}
        self._profiles = {}
        if self.durable:
            self.sql.executescript(SQLITE_TABLES)

    def _source_row(self, source_id):
        return self.sql.query_one(
            "SELECT source_id, policy_id, policy_revision, status, policy, created_at, updated_at "
            "FROM nutrition_source_policies WHERE source_id = ?", (source_id,))

    def _source_version_row(self, source_id, revision):
        return self.sql.query_one(
            "SELECT source_id, policy_id, policy_revision, status, policy, created_at, created_at AS updated_at "
            "FROM nutrition_source_policy_versions WHERE source_id = ? AND policy_revision = ?",
            (source_id, revision))

    def _profile_row(self, profile_id):
        return self.sql.query_one(
            "SELECT profile_id, user_id, profile_revision, profile_hash, source_id, "
            "source_policy_revision, reusable, status, food_identity, profile, created_at, updated_at "
            "FROM nutrition_profiles WHERE profile_id = ?", (profile_id,))

    @staticmethod
    def _source_document(row):
        if not row:
            return None
        return {"source_id": row["source_id"], "policy_id": row["policy_id"],
                "revision": int(row["policy_revision"]), "status": row["status"],
                "policy": deepcopy(_row_json(row, "policy")),
                "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}

    @staticmethod
    def _profile_document(row):
        if not row:
            return None
        return {"profile_id": row["profile_id"], "user_id": row["user_id"],
                "profile_revision": int(row["profile_revision"]), "profile_hash": row["profile_hash"],
                "source_id": row["source_id"],
                "source_policy_revision": int(row["source_policy_revision"]),
                "reusable": bool(row["reusable"]), "status": row["status"],
                "food_identity": deepcopy(_row_json(row, "food_identity")),
                "profile": deepcopy(_row_json(row, "profile")),
                "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}

    def save_source_policy(self, policy, *, expected_revision=None):
        policy, source_id, policy_id = _policy(policy)
        if expected_revision is not None:
            _revision(expected_revision, "expected_revision")
        if self.durable:
            now = utc_iso()
            with self.sql.transaction():
                existing = self._source_row(source_id)
                if existing:
                    current = int(existing["policy_revision"])
                    if expected_revision != current:
                        raise NutritionRepositoryError("revision_conflict", "Source policy revision is stale")
                    revision = current + 1
                    self.sql.execute(
                        "UPDATE nutrition_source_policies SET policy_id = ?, policy_revision = ?, status = ?, "
                        "policy = ?, updated_at = ? WHERE source_id = ?",
                        (policy_id, revision, "active", to_json(policy), now, source_id),)
                    self.sql.execute(
                        "INSERT INTO nutrition_source_policy_versions "
                        "(source_id, policy_revision, policy_id, status, policy, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (source_id, revision, policy_id, "active", to_json(policy), now),)
                else:
                    if expected_revision not in (None, 0):
                        raise NutritionRepositoryError("revision_conflict", "Source policy does not exist")
                    revision = 0
                    self.sql.execute(
                        "INSERT INTO nutrition_source_policies "
                        "(source_id, policy_id, policy_revision, status, policy, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (source_id, policy_id, revision, "active", to_json(policy), now, now),)
                    self.sql.execute(
                        "INSERT INTO nutrition_source_policy_versions "
                        "(source_id, policy_revision, policy_id, status, policy, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (source_id, revision, policy_id, "active", to_json(policy), now),)
                return self.get_source_policy(source_id, include_withdrawn=True)
        with self._lock:
            existing = self._sources.get(source_id)
            if existing:
                if expected_revision != existing["revision"]:
                    raise NutritionRepositoryError("revision_conflict", "Source policy revision is stale")
                revision = existing["revision"] + 1
                created_at = existing["created_at"]
            else:
                if expected_revision not in (None, 0):
                    raise NutritionRepositoryError("revision_conflict", "Source policy does not exist")
                revision, created_at = 0, utc_iso()
            self._sources[source_id] = {"source_id": source_id, "policy_id": policy_id,
                "revision": revision, "status": "active", "policy": deepcopy(policy),
                "created_at": created_at, "updated_at": utc_iso()}
            return deepcopy(self._sources[source_id])

    def get_source_policy(self, source_id, *, revision=None, include_withdrawn=False):
        source_id = _bounded_id(source_id, "source_id")
        if revision is not None:
            _revision(revision)
        row = ((self._source_version_row(source_id, revision) if revision is not None
                else self._source_row(source_id)) if self.durable else self._sources.get(source_id))
        document = self._source_document(row) if self.durable else deepcopy(row)
        if document is None:
            return None
        if revision is not None and document["revision"] != revision:
            raise NutritionRepositoryError("revision_conflict", "Source policy revision is stale")
        if document["status"] != "active" and not include_withdrawn:
            return None
        return document

    def get_source_policy_by_policy_id(self, policy_id, *, revision=None,
                                       include_withdrawn=False):
        """Resolve a reviewed policy id without guessing its source id.

        ``policy_id`` is not globally constrained by the SQL schema, so an
        accidental duplicate must fail closed instead of selecting an
        arbitrary source.  The version table is used for historical
        revisions; the current table is used when no revision was supplied.
        """
        policy_id = _bounded_id(policy_id, "policy_id")
        if revision is not None:
            _revision(revision)
        if self.durable:
            if revision is None:
                rows = self.sql.query_all(
                    "SELECT source_id, policy_id, policy_revision, status, policy, created_at, created_at AS updated_at "
                    "FROM nutrition_source_policies WHERE policy_id = ?",
                    (policy_id,))
            else:
                rows = self.sql.query_all(
                    "SELECT source_id, policy_id, policy_revision, status, policy, created_at, created_at AS updated_at "
                    "FROM nutrition_source_policy_versions WHERE policy_id = ? AND policy_revision = ?",
                    (policy_id, revision))
            if len(rows) > 1:
                raise NutritionRepositoryError("source_conflict", "Source policy id is ambiguous")
            document = self._source_document(rows[0]) if rows else None
        else:
            matches = [value for value in self._sources.values()
                       if value.get("policy_id") == policy_id
                       and (revision is None or value.get("revision") == revision)]
            if len(matches) > 1:
                raise NutritionRepositoryError("source_conflict", "Source policy id is ambiguous")
            document = deepcopy(matches[0]) if matches else None
        if document is None:
            return None
        if revision is not None and document["revision"] != revision:
            raise NutritionRepositoryError("revision_conflict", "Source policy revision is stale")
        if document["status"] != "active" and not include_withdrawn:
            return None
        return document

    def resolve_source_policy_reference(self, reference, *, revision=None,
                                        include_withdrawn=False):
        """Resolve either a legacy source id or the reviewed policy id.

        The public request field historically carried a source id despite its
        ``source_policy_id`` name.  Keep that input compatible while making
        policy-id aliases explicit.  If both identifiers point to different
        sources, reject the reference rather than silently choosing one.
        """
        reference = _bounded_id(reference, "source_policy_id")
        if revision is not None:
            _revision(revision)
        by_source = self.get_source_policy(
            reference, include_withdrawn=include_withdrawn)
        by_policy = self.get_source_policy_by_policy_id(
            reference, include_withdrawn=include_withdrawn)
        candidates = {document["source_id"]: document for document in
                      (by_source, by_policy) if document is not None}
        if len(candidates) > 1:
            raise NutritionRepositoryError("source_conflict", "Source policy reference is ambiguous")
        document = next(iter(candidates.values())) if candidates else None
        if document is not None and revision is not None and document["revision"] != revision:
            raise NutritionRepositoryError("revision_conflict", "Source policy revision is stale")
        return deepcopy(document) if document else None

    def list_source_policies(self, *, include_withdrawn=False):
        if self.durable:
            rows = self.sql.query_all(
                "SELECT source_id, policy_id, policy_revision, status, policy, created_at, updated_at "
                "FROM nutrition_source_policies" + ("" if include_withdrawn else " WHERE status = 'active'")
                + " ORDER BY source_id")
            return [self._source_document(row) for row in rows]
        with self._lock:
            return [deepcopy(value) for value in sorted(self._sources.values(), key=lambda item: item["source_id"])
                    if include_withdrawn or value["status"] == "active"]

    def withdraw_source_policy(self, source_id, *, expected_revision):
        source_id = _bounded_id(source_id, "source_id")
        _revision(expected_revision, "expected_revision")
        if self.durable:
            with self.sql.transaction():
                existing = self._source_row(source_id)
                if not existing or int(existing["policy_revision"]) != expected_revision:
                    raise NutritionRepositoryError("revision_conflict", "Source policy revision is stale")
                self.sql.execute(
                    "UPDATE nutrition_source_policies SET policy_revision = ?, status = ?, updated_at = ? "
                    "WHERE source_id = ?", (expected_revision + 1, "withdrawn", utc_iso(), source_id),)
                self.sql.execute(
                    "INSERT INTO nutrition_source_policy_versions "
                    "(source_id, policy_revision, policy_id, status, policy, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (source_id, expected_revision + 1, existing["policy_id"], "withdrawn",
                     existing["policy"], utc_iso()),)
                return self.get_source_policy(source_id, include_withdrawn=True)
        with self._lock:
            existing = self._sources.get(source_id)
            if not existing or existing["revision"] != expected_revision:
                raise NutritionRepositoryError("revision_conflict", "Source policy revision is stale")
            existing["revision"] += 1
            existing["status"] = "withdrawn"
            existing["updated_at"] = utc_iso()
            return deepcopy(existing)

    def _require_source_for_profile(self, source_id, source_policy_revision, identity, reusable):
        source = self._source_row(source_id) if self.durable else self._sources.get(source_id)
        source = self._source_document(source) if self.durable else deepcopy(source)
        if source is None or source["status"] != "active":
            raise NutritionRepositoryError("source_unavailable", "Source policy is missing or withdrawn")
        if source["revision"] != source_policy_revision:
            raise NutritionRepositoryError("source_conflict", "Profile source policy revision is stale")
        policy = source["policy"]
        rights = policy["rights"]
        if not rights["snapshot_allowed"] or not rights["reuse_allowed"]:
            raise NutritionRepositoryError("rights_not_allowed", "Source policy does not allow profile persistence and reuse")
        target = policy["target_identity"]
        for field in ("food_state", "preparation_method", "components_scope", "brand", "variant"):
            if identity[field] != target.get(field):
                raise NutritionRepositoryError("source_conflict", "Profile food identity does not match the reviewed policy")
        if identity["name"] not in policy["accepted_names"]:
            raise NutritionRepositoryError("source_conflict", "Profile food name is not a reviewed alias")
        if reusable and not (rights["reuse_scope"] == "cross_user"
                             and rights["provider_cache_scope"] == "cross_user_approved"):
            raise NutritionRepositoryError("reuse_not_allowed", "Cross-user profile reuse is not approved")
        return source

    def _validate_profile_provenance(self, checked_profile, source):
        details = checked_profile.get("source_details")
        if not isinstance(details, dict):
            raise NutritionRepositoryError("invalid_provenance", "Profile source details are required")
        spec = source["policy"]["source_spec"]
        if details.get("source_id") != source["source_id"] or details.get("source_url") != spec["source_url"]:
            raise NutritionRepositoryError("source_conflict", "Profile provenance does not match the reviewed source")
        for field in ("content_hash", "adapter_version", "retrieval_version"):
            if not isinstance(details.get(field), str) or not details[field].strip():
                raise NutritionRepositoryError("invalid_provenance", f"Profile provenance {field} is required")
        if not _HASH.fullmatch(details["content_hash"]):
            raise NutritionRepositoryError("invalid_provenance", "Profile content_hash is invalid")
        if details["adapter_version"] != spec["adapter_version"]:
            raise NutritionRepositoryError("source_conflict", "Profile adapter version does not match the source policy")

        # FDC detail profiles carry a stricter, provider-specific provenance
        # contract than the legacy Web/Tavily adapter.  Keep this branch
        # opt-in so existing reviewed web policies remain wire-compatible.
        if spec.get("provider_kind") == "usda_fdc_api":
            for field in ("retrieval_version", "table_id", "fdc_id", "provider_kind"):
                expected = spec.get(field)
                if not isinstance(expected, str) or not expected.strip():
                    raise NutritionRepositoryError("invalid_policy", f"FDC source policy {field} is required")
                if details.get(field) != expected:
                    raise NutritionRepositoryError("source_conflict", f"Profile {field} does not match the FDC source policy")
            expected_identity = spec.get("food_identity")
            actual_identity = details.get("food_identity")
            if not isinstance(expected_identity, dict) or not isinstance(actual_identity, dict):
                raise NutritionRepositoryError("invalid_provenance", "FDC profile source identity is required")
            # Unknown/None are ordinary identity values here, not wildcards.
            if actual_identity != expected_identity:
                raise NutritionRepositoryError("source_conflict", "Profile FDC source identity does not match the source policy")
            provider_kind = details.get("provider_kind")
            if provider_kind is not None and provider_kind != "usda_fdc_api":
                raise NutritionRepositoryError("source_conflict", "Profile provider kind does not match the FDC source policy")

    def save_profile(self, *, profile_id, user_id, profile, food_identity,
                     source_id, source_policy_revision, reusable=False,
                     expected_revision=None):
        profile_id = _bounded_id(profile_id, "profile_id")
        user_id = _bounded_id(user_id, "user_id")
        source_id = _bounded_id(source_id, "source_id")
        source_policy_revision = _revision(source_policy_revision, "source_policy_revision")
        if not isinstance(reusable, bool):
            raise NutritionRepositoryError("invalid_reuse", "reusable must be boolean")
        if expected_revision is not None:
            _revision(expected_revision, "expected_revision")
        identity = _identity(food_identity)
        checked_profile = _profile(profile)
        digest = profile_hash(checked_profile)
        if self.durable:
            now = utc_iso()
            with self.sql.transaction():
                return self._save_profile_in_transaction(
                    profile_id=profile_id, user_id=user_id, checked_profile=checked_profile,
                    identity=identity, source_id=source_id,
                    source_policy_revision=source_policy_revision, reusable=reusable,
                    expected_revision=expected_revision, digest=digest, now=now)
        with self._lock:
            source = self._require_source_for_profile(source_id, source_policy_revision, identity, reusable)
            self._validate_profile_provenance(checked_profile, source)
            existing = self._profiles.get(profile_id)
            if existing:
                if existing["user_id"] != user_id:
                    raise NutritionRepositoryError("ownership_conflict", "Profile belongs to another user")
                if expected_revision != existing["profile_revision"]:
                    raise NutritionRepositoryError("revision_conflict", "Profile revision is stale")
                revision, created_at = existing["profile_revision"] + 1, existing["created_at"]
            else:
                if expected_revision not in (None, 0):
                    raise NutritionRepositoryError("revision_conflict", "Profile does not exist")
                revision, created_at = 0, utc_iso()
            self._profiles[profile_id] = {"profile_id": profile_id, "user_id": user_id,
                "profile_revision": revision, "profile_hash": digest, "source_id": source_id,
                "source_policy_revision": source_policy_revision, "reusable": reusable,
                "status": "active", "food_identity": deepcopy(identity),
                "profile": deepcopy(checked_profile), "created_at": created_at, "updated_at": utc_iso()}
            return deepcopy(self._profiles[profile_id])

    def _save_profile_in_transaction(self, *, profile_id, user_id,
                                     checked_profile, identity, source_id,
                                     source_policy_revision, reusable,
                                     expected_revision, digest=None, now=None):
        """Persist a validated profile while the caller owns the SQLite transaction.

        This is intentionally private.  It is used by an atomic preview accept
        flow that must write the profile and consume its preview in one
        ``BEGIN IMMEDIATE`` transaction.  The public ``save_profile`` method
        remains responsible for opening its own transaction and input checks.
        """
        if not self.durable:
            raise NutritionRepositoryError("unsupported_database", "Atomic profile writes require SQLite")
        profile_id = _bounded_id(profile_id, "profile_id")
        user_id = _bounded_id(user_id, "user_id")
        source_id = _bounded_id(source_id, "source_id")
        source_policy_revision = _revision(source_policy_revision, "source_policy_revision")
        if not isinstance(reusable, bool):
            raise NutritionRepositoryError("invalid_reuse", "reusable must be boolean")
        if expected_revision is not None:
            _revision(expected_revision, "expected_revision")
        identity = _identity(identity)
        checked_profile = _profile(checked_profile)
        digest = digest or profile_hash(checked_profile)
        if now is None:
            now = utc_iso()
        # Re-read source and profile under the caller's transaction.  The
        # outer BEGIN IMMEDIATE prevents a concurrent policy/profile writer
        # from changing the rows between these checks and the write.
        source_row = self._source_row(source_id)
        source = self._source_document(source_row)
        if source is None or source["status"] != "active":
            raise NutritionRepositoryError("source_unavailable", "Source policy is missing or withdrawn")
        self._require_source_for_profile(source_id, source_policy_revision, identity, reusable)
        self._validate_profile_provenance(checked_profile, source)
        existing = self._profile_row(profile_id)
        if existing:
            current = int(existing["profile_revision"])
            if existing["user_id"] != user_id:
                raise NutritionRepositoryError("ownership_conflict", "Profile belongs to another user")
            if expected_revision != current:
                raise NutritionRepositoryError("revision_conflict", "Profile revision is stale")
            revision = current + 1
            self.sql.execute(
                "UPDATE nutrition_profiles SET profile_revision = ?, profile_hash = ?, source_id = ?, "
                "source_policy_revision = ?, reusable = ?, status = ?, food_identity = ?, profile = ?, updated_at = ? "
                "WHERE profile_id = ?",
                (revision, digest, source_id, source_policy_revision, reusable, "active",
                 to_json(identity), to_json(checked_profile), now, profile_id),)
        else:
            if expected_revision not in (None, 0):
                raise NutritionRepositoryError("revision_conflict", "Profile does not exist")
            revision = 0
            self.sql.execute(
                "INSERT INTO nutrition_profiles "
                "(profile_id, user_id, profile_revision, profile_hash, source_id, source_policy_revision, reusable, status, food_identity, profile, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (profile_id, user_id, revision, digest, source_id, source_policy_revision, reusable,
                 "active", to_json(identity), to_json(checked_profile), now, now),)
        return self._profile_document(self._profile_row(profile_id))

    def get_profile_for_user(self, user_id, profile_id, *, revision=None,
                             include_withdrawn=False):
        user_id = _bounded_id(user_id, "user_id")
        profile_id = _bounded_id(profile_id, "profile_id")
        if revision is not None:
            _revision(revision, "revision")
        row = self._profile_row(profile_id) if self.durable else self._profiles.get(profile_id)
        document = self._profile_document(row) if self.durable else deepcopy(row)
        if document is None:
            return None
        if revision is not None and document["profile_revision"] != revision:
            raise NutritionRepositoryError("revision_conflict", "Profile revision is stale")
        if document["status"] != "active" and not include_withdrawn:
            return None
        source = self.get_source_policy(document["source_id"])
        source_invalid = source is None or source["revision"] != document["source_policy_revision"]
        if source_invalid and document["user_id"] == user_id and include_withdrawn:
            return document
        if source_invalid:
            # A source withdrawal or policy revision invalidates future
            # authority even for the profile owner. Historical records keep
            # their embedded snapshot and can be read by their own flows.
            # A non-owner must never fall through to the cross-user rights
            # check below: the withdrawn source policy is intentionally not
            # available for reuse, including when a caller asks to include
            # withdrawn historical records.
            raise NutritionRepositoryError("source_unavailable", "Profile source policy is no longer active")
        if document["user_id"] != user_id:
            if not document["reusable"]:
                raise NutritionRepositoryError("ownership_conflict", "Profile belongs to another user")
            # Cross-user reuse is rechecked against the current source policy;
            # a policy withdrawal immediately disables future authorities.
            rights = source["policy"]["rights"]
            if source_invalid or not (rights["reuse_scope"] == "cross_user"
                    and rights["provider_cache_scope"] == "cross_user_approved"):
                raise NutritionRepositoryError("reuse_not_allowed", "Cross-user profile reuse is not approved")
        return document

    def withdraw_profile(self, profile_id, *, expected_revision):
        profile_id = _bounded_id(profile_id, "profile_id")
        _revision(expected_revision, "expected_revision")
        if self.durable:
            with self.sql.transaction():
                existing = self._profile_row(profile_id)
                if not existing or int(existing["profile_revision"]) != expected_revision:
                    raise NutritionRepositoryError("revision_conflict", "Profile revision is stale")
                self.sql.execute(
                    "UPDATE nutrition_profiles SET profile_revision = ?, status = ?, updated_at = ? "
                    "WHERE profile_id = ?", (expected_revision + 1, "withdrawn", utc_iso(), profile_id),)
                row = self._profile_row(profile_id)
                return self._profile_document(row)
        with self._lock:
            existing = self._profiles.get(profile_id)
            if not existing or existing["profile_revision"] != expected_revision:
                raise NutritionRepositoryError("revision_conflict", "Profile revision is stale")
            existing["profile_revision"] += 1
            existing["status"] = "withdrawn"
            existing["updated_at"] = utc_iso()
            return deepcopy(existing)
