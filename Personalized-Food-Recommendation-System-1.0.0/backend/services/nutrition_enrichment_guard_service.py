"""Process-local single-flight, idempotency and quota guard for enrichment.

This is an integration boundary, not a durable queue or a distributed lock.
All state is process-local and disappears on restart.  A production route must
replace the maps with a shared store and atomic compare/insert operations before
it enables paid web enrichment.
"""

from copy import deepcopy
import hashlib
import json
import math
import threading
import time


MAX_REQUEST_BYTES = 128 * 1024
MAX_ITEMS = 64
MAX_PROFILES = 64
RETRYABLE_STATUSES = {"timeout", "rate_limited", "upstream_error", "busy"}
NOT_FOUND_STATUS = "not_found"
SUCCESS_STATUSES = {"accepted", "partial", "complete", "success"}
TERMINAL_STATUSES = SUCCESS_STATUSES | {NOT_FOUND_STATUS, "invalid_output", "source_conflict"}
ALL_STATUSES = RETRYABLE_STATUSES | TERMINAL_STATUSES


class NutritionEnrichmentGuardError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class NutritionEnrichmentOutcome:
    def __init__(self, status, result=None):
        self.status = status
        self.result = deepcopy(result)


def _fail(code, message):
    raise NutritionEnrichmentGuardError(code, message)


def _text(value, field, maximum=256):
    if (not isinstance(value, str) or not value or len(value) > maximum or value.strip() != value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _number(value, field, *, lower=None, upper=None):
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite:
        _fail("invalid_request", f"{field} is invalid")
    if (lower is not None and value < lower) or (upper is not None and value > upper):
        _fail("invalid_request", f"{field} is outside the permitted range")
    return value


def _canonical(value):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        _fail("invalid_request", "Enrichment request must be finite JSON")
    encoded_bytes = encoded.encode("utf-8")
    if len(encoded_bytes) > MAX_REQUEST_BYTES:
        _fail("oversized_request", "Enrichment request exceeds its size budget")
    return encoded_bytes


def _item(item):
    if not isinstance(item, dict):
        _fail("invalid_request", "Each enrichment item must be an object")
    allowed = {"item_id", "item_revision", "name_zh", "confidence", "weight_confidence",
               "estimated_weight_g", "food_state", "preparation_method", "components_scope",
               "brand", "variant", "validation_issues", "identity_confirmation_required",
               "identity_confirmation_source", "identity_confirmation_id"}
    if set(item) - allowed:
        _fail("invalid_request", "Enrichment item contains unsupported fields")
    if "identity_confirmation_required" in item and type(item["identity_confirmation_required"]) is not bool:
        _fail("invalid_request", "identity_confirmation_required must be a boolean")
    confirmation_source = item.get("identity_confirmation_source")
    confirmation_id = item.get("identity_confirmation_id")
    if confirmation_source is not None and confirmation_source != "user":
        _fail("invalid_request", "identity_confirmation_source is invalid")
    if confirmation_id is not None:
        _text(confirmation_id, "identity_confirmation_id")
    if ((confirmation_source == "user") != (confirmation_id is not None)
            or (confirmation_source == "user" and item.get("identity_confirmation_required") is not False)):
        _fail("invalid_request", "User identity confirmation provenance is incomplete")
    _text(item.get("item_id"), "item_id")
    revision = item.get("item_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        _fail("invalid_request", "item_revision is invalid")
    _text(item.get("name_zh"), "name_zh", 300)
    for field in ("confidence", "weight_confidence"):
        value = item.get(field)
        if value is not None:
            _number(value, field, lower=0, upper=1)
    weight = item.get("estimated_weight_g")
    if weight is not None:
        _number(weight, "estimated_weight_g", lower=0, upper=2000)
        if weight == 0:
            _fail("invalid_request", "estimated_weight_g must be positive")
    enum_values = {
        "food_state": {"prepared", "raw", "dry", "unknown"},
        "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised", "steamed", "mixed", "unknown"},
        "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides", "unknown"},
    }
    for field, allowed_values in enum_values.items():
        value = item.get(field)
        if value is not None and value not in allowed_values:
            _fail("invalid_request", f"{field} is invalid")
    for field in ("brand", "variant"):
        value = item.get(field)
        if value is not None:
            _text(value, field)
    issues = item.get("validation_issues", [])
    if (not isinstance(issues, list) or len(issues) > 32
            or any(not isinstance(issue, str) or not issue or len(issue) > 128 for issue in issues)):
        _fail("invalid_request", "validation_issues are invalid")
    return deepcopy(item)


def _profiles(profiles):
    if not isinstance(profiles, (list, tuple)) or len(profiles) > MAX_PROFILES:
        _fail("invalid_request", "profile authorities are invalid")
    result, seen = [], set()
    allowed = {"profile_id", "profile_hash", "source_id", "profile_revision"}
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != allowed:
            _fail("invalid_request", "Profile authority fields are invalid")
        profile_id = _text(profile.get("profile_id"), "profile_id")
        if profile_id in seen:
            _fail("invalid_request", "Profile IDs must be unique")
        seen.add(profile_id)
        digest = _text(profile.get("profile_hash"), "profile_hash", 64).lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            _fail("invalid_request", "profile_hash is invalid")
        _text(profile.get("source_id"), "source_id")
        revision = profile.get("profile_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            _fail("invalid_request", "profile_revision is invalid")
        normalized = deepcopy(profile)
        normalized["profile_hash"] = digest
        result.append(normalized)
    return sorted(result, key=lambda value: value["profile_id"])


def build_enrichment_request_fingerprint(*, user_id, scan_id, scan_revision, items,
                                         profiles=(), source_policy_id, source_policy_revision,
                                         request_kind="nutrition_enrichment"):
    """Return a deterministic fingerprint for a server-authorized request.

    Item and profile order is normalized so retries caused by transport ordering
    do not create a second provider call.  The caller must pass signed/server-
    owned identities; this helper does not authenticate or sign them.
    """
    _text(user_id, "user_id")
    _text(scan_id, "scan_id")
    if isinstance(scan_revision, bool) or not isinstance(scan_revision, int) or scan_revision < 0:
        _fail("invalid_request", "scan_revision is invalid")
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        _fail("invalid_request", "items are invalid")
    normalized_items = [_item(item) for item in items]
    ids = [item["item_id"] for item in normalized_items]
    if len(ids) != len(set(ids)):
        _fail("invalid_request", "Item IDs must be unique")
    normalized_items.sort(key=lambda value: value["item_id"])
    policy = {"policy_id": _text(source_policy_id, "source_policy_id"),
              "policy_revision": source_policy_revision}
    if isinstance(source_policy_revision, bool) or not isinstance(source_policy_revision, int) or source_policy_revision < 0:
        _fail("invalid_request", "source_policy_revision is invalid")
    request = {"request_kind": _text(request_kind, "request_kind", 64), "user_id": user_id,
               "scan_id": scan_id, "scan_revision": scan_revision, "items": normalized_items,
               "profiles": _profiles(profiles), "source_policy": policy}
    return hashlib.sha256(_canonical(request)).hexdigest()


class _Entry:
    def __init__(self, *, user_id, fingerprint, window, reservation):
        self.user_id = user_id
        self.fingerprint = fingerprint
        self.window = window
        self.reservation = reservation
        self.event = threading.Event()
        self.status = "pending"
        self.result = None


class EnrichmentLease:
    def __init__(self, guard, entry, *, owner):
        self._guard = guard
        self._entry = entry
        self.owner = owner

    @property
    def replay(self):
        return not self.owner and self._entry.status != "pending"

    def wait(self, timeout=None):
        if self.owner:
            return NutritionEnrichmentOutcome(self._entry.status, self._entry.result)
        if not self._entry.event.wait(timeout):
            _fail("single_flight_timeout", "The in-flight enrichment did not finish")
        return NutritionEnrichmentOutcome(self._entry.status, self._entry.result)

    def complete(self, status, result=None):
        if not self.owner:
            _fail("not_owner", "Only the single-flight owner can complete a request")
        return self._guard._finish(self._entry, status, result)

    def abort(self):
        if not self.owner:
            _fail("not_owner", "Only the single-flight owner can abort a request")
        return self._guard._finish(self._entry, "upstream_error", None)


class NutritionEnrichmentGuard:
    """In-process idempotency and quota state for a future HTTP route."""

    def __init__(self, *, per_user_limit=2, global_limit=2, window_seconds=86400, clock=time.time):
        for value, field in ((per_user_limit, "per_user_limit"), (global_limit, "global_limit"), (window_seconds, "window_seconds")):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                _fail("invalid_quota", f"{field} is invalid")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        self.per_user_limit = per_user_limit
        self.global_limit = global_limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._lock = threading.RLock()
        self._entries = {}
        self._fingerprints = {}
        self._user_usage = {}
        self._global_usage = {}

    def _window(self):
        now = self.clock()
        try:
            finite = math.isfinite(now)
        except (OverflowError, TypeError):
            finite = False
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not finite:
            _fail("invalid_clock", "The quota clock is invalid")
        return int(now // self.window_seconds)

    def _prune(self, window):
        for key in list(self._user_usage):
            if key[0] < window:
                del self._user_usage[key]
        for key in list(self._global_usage):
            if key < window:
                del self._global_usage[key]
        old_entries = {entry for entry in self._entries.values()
                       if entry.window < window and entry.status != "pending"}
        for entry in old_entries:
            self._remove_entry(entry)

    def _reserve(self, user_id, window):
        self._prune(window)
        user_key = (window, user_id)
        user_used = self._user_usage.get(user_key, 0)
        global_used = self._global_usage.get(window, 0)
        if user_used >= self.per_user_limit:
            _fail("user_quota_exceeded", "The user enrichment quota is exhausted")
        if global_used >= self.global_limit:
            _fail("global_quota_exceeded", "The global enrichment quota is exhausted")
        self._user_usage[user_key] = user_used + 1
        self._global_usage[window] = global_used + 1

    def _release(self, entry):
        user_key = (entry.window, entry.user_id)
        self._user_usage[user_key] = max(0, self._user_usage.get(user_key, 0) - 1)
        self._global_usage[entry.window] = max(0, self._global_usage.get(entry.window, 0) - 1)

    def begin(self, *, user_id, idempotency_key, fingerprint):
        _text(user_id, "user_id")
        _text(idempotency_key, "idempotency_key", 256)
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            _fail("invalid_request", "fingerprint is invalid")
        key = (user_id, idempotency_key)
        with self._lock:
            window = self._window()
            self._prune(window)
            existing = self._entries.get(key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    _fail("idempotency_conflict", "The idempotency key was used for another request")
                return EnrichmentLease(self, existing, owner=False)
            existing = self._fingerprints.get(fingerprint)
            if existing is not None:
                if existing.user_id != user_id:
                    _fail("idempotency_conflict", "The request fingerprint belongs to another user")
                self._entries[key] = existing
                return EnrichmentLease(self, existing, owner=False)
            self._reserve(user_id, window)
            entry = _Entry(user_id=user_id, fingerprint=fingerprint, window=window, reservation=True)
            self._entries[key] = entry
            self._fingerprints[fingerprint] = entry
            return EnrichmentLease(self, entry, owner=True)

    def _remove_entry(self, entry):
        for key, candidate in list(self._entries.items()):
            if candidate is entry:
                del self._entries[key]
        if self._fingerprints.get(entry.fingerprint) is entry:
            del self._fingerprints[entry.fingerprint]

    def _finish(self, entry, status, result):
        if status not in ALL_STATUSES:
            _fail("invalid_outcome", "Unsupported enrichment outcome")
        with self._lock:
            if entry.status != "pending":
                _fail("already_completed", "The enrichment has already completed")
            if status in RETRYABLE_STATUSES or status == NOT_FOUND_STATUS:
                # Retryable failures release the reservation. not_found commits
                # provider usage but is intentionally not retained as a cache hit.
                if status in RETRYABLE_STATUSES:
                    self._release(entry)
                self._remove_entry(entry)
            else:
                entry.result = deepcopy(result)
            entry.status = status
            entry.event.set()
            return NutritionEnrichmentOutcome(status, result)

    def quota_snapshot(self, user_id):
        _text(user_id, "user_id")
        with self._lock:
            window = self._window()
            self._prune(window)
            return {"window": window, "user_used": self._user_usage.get((window, user_id), 0),
                    "user_limit": self.per_user_limit, "global_used": self._global_usage.get(window, 0),
                    "global_limit": self.global_limit}

