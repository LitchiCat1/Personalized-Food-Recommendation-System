"""Short-lived authority tokens for the future nutrition enrichment route.

This module does not authenticate users, persist scans, or fetch profiles.  A
trusted route must authenticate the caller and obtain the signed input from the
server-owned scanner/profile repository before issuing a token.  The in-memory
consume set is process-local by design; production replay protection needs a
shared durable store and an atomic insert/compare operation.
"""

from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import math
import secrets
import threading
import time

from services.nutrition_evidence_service import IDENTITY_ENUMS


MAX_TOKEN_BYTES = 32 * 1024
MAX_ITEMS = 64
MAX_VALIDITY_SECONDS = 15 * 60
MAX_PROFILE_VALIDITY_SECONDS = 24 * 60 * 60
CLOCK_SKEW_SECONDS = 5
TOKEN_VERSION = 1
SCAN_TOKEN_TYPE = "scan_context"
PROFILE_TOKEN_TYPE = "profile_authority"
_TOKEN_TYPES = {SCAN_TOKEN_TYPE, PROFILE_TOKEN_TYPE}
_ID_HEX = set("0123456789abcdef")


class NutritionAuthorityError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise NutritionAuthorityError(code, message)


def _bounded_text(value, *, field, maximum=256):
    if (not isinstance(value, str) or not value or len(value) > maximum or value.strip() != value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail("invalid_claim", f"{field} is invalid")
    return value


def _id(value, field, maximum=256):
    return _bounded_text(value, field=field, maximum=maximum)


def _finite_number(value, field, *, lower=None, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_claim", f"{field} is invalid")
    if lower is not None and value < lower or upper is not None and value > upper:
        _fail("invalid_claim", f"{field} is outside its permitted range")
    return value


def _canonical(value):
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid_claim", "Token claims must be finite JSON")
    if len(encoded.encode("utf-8")) > MAX_TOKEN_BYTES:
        _fail("oversized_claim", "Token claims exceed the authority budget")
    return encoded.encode("utf-8")


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value, field):
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN_BYTES:
        _fail("invalid_token", f"{field} is invalid")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in value):
        _fail("invalid_token", f"{field} is invalid")
    try:
        padding = "=" * ((4 - len(value) % 4) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        _fail("invalid_token", f"{field} is invalid")


def _timestamp(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("invalid_claim", f"{field} is invalid")
    return value


def _profile_hash(profile):
    return hashlib.sha256(_canonical(profile)).hexdigest()


def _validate_identity(item, *, complete=False):
    if complete:
        allowed_fields = {"name", *IDENTITY_ENUMS, "brand", "variant"}
        if set(item) != allowed_fields:
            _fail("invalid_claim", "food identity contains unsupported fields")
    for field, allowed in IDENTITY_ENUMS.items():
        value = item.get(field)
        if complete and field not in item:
            _fail("invalid_claim", f"{field} is required")
        if value is not None and value not in allowed:
            _fail("invalid_claim", f"{field} is invalid")
    for field in ("brand", "variant"):
        value = item.get(field)
        if value is not None:
            _bounded_text(value, field=field)


def _validated_scan_items(items):
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        _fail("invalid_claim", "scan items are invalid")
    result, seen = [], set()
    allowed = {"item_id", "item_revision", "name_zh", "confidence", "weight_confidence",
               "estimated_weight_g", "food_state", "preparation_method", "components_scope",
               "brand", "variant", "validation_issues", "identity_confirmation_required",
               "identity_confirmation_source", "identity_confirmation_id"}
    for item in items:
        if not isinstance(item, dict) or set(item) - allowed:
            _fail("invalid_claim", "scan item contains unsupported fields")
        if "identity_confirmation_required" in item and type(item["identity_confirmation_required"]) is not bool:
            _fail("invalid_claim", "identity_confirmation_required must be a boolean")
        confirmation_source = item.get("identity_confirmation_source")
        confirmation_id = item.get("identity_confirmation_id")
        if confirmation_source is not None and confirmation_source != "user":
            _fail("invalid_claim", "identity_confirmation_source is invalid")
        if confirmation_id is not None:
            _id(confirmation_id, "identity_confirmation_id")
        if ((confirmation_source == "user") != (confirmation_id is not None)
                or (confirmation_source == "user" and item.get("identity_confirmation_required") is not False)):
            _fail("invalid_claim", "User identity confirmation provenance is incomplete")
        item_id = _id(item.get("item_id"), "item_id")
        if item_id in seen:
            _fail("invalid_claim", "scan item IDs must be unique")
        seen.add(item_id)
        revision = item.get("item_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            _fail("invalid_claim", "item_revision is invalid")
        name = _bounded_text(item.get("name_zh"), field="name_zh", maximum=300)
        confidence = item.get("confidence")
        if confidence is not None:
            _finite_number(confidence, "confidence", lower=0, upper=1)
        weight_confidence = item.get("weight_confidence")
        if weight_confidence is not None:
            _finite_number(weight_confidence, "weight_confidence", lower=0, upper=1)
        weight = item.get("estimated_weight_g")
        if weight is not None:
            _finite_number(weight, "estimated_weight_g", lower=0, upper=2000)
            if weight == 0:
                _fail("invalid_claim", "estimated_weight_g must be positive")
        _validate_identity(item)
        issues = item.get("validation_issues", [])
        if not isinstance(issues, list) or len(issues) > 32 or any(not isinstance(issue, str) or not issue or len(issue) > 128 for issue in issues):
            _fail("invalid_claim", "validation_issues are invalid")
        result.append({key: deepcopy(item[key]) for key in allowed if key in item})
    return result


class NutritionAuthorityService:
    """Issue and verify compact HMAC authority tokens for trusted routes."""

    def __init__(self, keys, *, active_kid=None, clock=time.time):
        if not isinstance(keys, dict) or not keys:
            _fail("invalid_keyring", "At least one signing key is required")
        normalized = {}
        for kid, secret in keys.items():
            _id(kid, "kid", 64)
            if not isinstance(secret, bytes) or len(secret) < 32:
                _fail("invalid_keyring", "Signing keys must contain at least 32 bytes")
            normalized[kid] = bytes(secret)
        if active_kid is None:
            active_kid = next(iter(normalized))
        if active_kid not in normalized:
            _fail("invalid_keyring", "The active signing key is missing")
        if not callable(clock):
            _fail("invalid_clock", "A clock callable is required")
        self._keys = normalized
        self._active_kid = active_kid
        self._clock = clock
        self._consumed = set()
        self._lock = threading.Lock()

    @staticmethod
    def profile_hash(profile):
        return _profile_hash(profile)

    def _now(self):
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            _fail("invalid_clock", "The authority clock is invalid")
        return int(value)

    def _issue(self, token_type, claims, ttl_seconds):
        if token_type not in _TOKEN_TYPES:
            _fail("invalid_claim", "Unknown authority token type")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            _fail("invalid_claim", "Token TTL is invalid")
        maximum = MAX_VALIDITY_SECONDS if token_type == SCAN_TOKEN_TYPE else MAX_PROFILE_VALIDITY_SECONDS
        if ttl_seconds > maximum:
            _fail("invalid_claim", "Token TTL exceeds its permitted maximum")
        issued = self._now()
        envelope = {"v": TOKEN_VERSION, "kid": self._active_kid, "typ": token_type,
                    "iat": issued, "exp": issued + ttl_seconds, "jti": _b64(secrets.token_bytes(16)),
                    "claims": claims}
        body = _canonical(envelope)
        signature = hmac.new(self._keys[self._active_kid], body, hashlib.sha256).digest()
        token = _b64(body) + "." + _b64(signature)
        if len(token.encode("ascii")) > MAX_TOKEN_BYTES:
            _fail("oversized_claim", "Authority token exceeds its size budget")
        return token

    def issue_scan_context(self, *, user_id, scan_id, scan_revision, items, ttl_seconds=120):
        claims = {"user_id": _id(user_id, "user_id"), "scan_id": _id(scan_id, "scan_id"),
                  "scan_revision": scan_revision, "items": _validated_scan_items(items),
                  "purpose": "nutrition_enrichment"}
        if isinstance(scan_revision, bool) or not isinstance(scan_revision, int) or scan_revision < 0:
            _fail("invalid_claim", "scan_revision is invalid")
        return self._issue(SCAN_TOKEN_TYPE, claims, ttl_seconds)

    def issue_profile_authority(self, *, user_id, profile_id, profile_hash, source_id,
                                profile_revision, food_identity, ttl_seconds=3600, reusable=False):
        _id_hash = _bounded_text(profile_hash, field="profile_hash", maximum=64).lower()
        if len(_id_hash) != 64 or any(character not in _ID_HEX for character in _id_hash):
            _fail("invalid_claim", "profile_hash is invalid")
        if not isinstance(reusable, bool):
            _fail("invalid_claim", "reusable is invalid")
        if not isinstance(profile_revision, int) or isinstance(profile_revision, bool) or profile_revision < 0:
            _fail("invalid_claim", "profile_revision is invalid")
        if not isinstance(food_identity, dict):
            _fail("invalid_claim", "food_identity is invalid")
        identity = deepcopy(food_identity)
        _bounded_text(identity.get("name"), field="food_identity.name", maximum=300)
        _validate_identity(identity, complete=True)
        claims = {"user_id": _id(user_id, "user_id"), "profile_id": _id(profile_id, "profile_id"),
                  "profile_hash": _id_hash, "source_id": _id(source_id, "source_id"),
                  "profile_revision": profile_revision, "food_identity": identity,
                  "reusable": reusable, "purpose": "nutrition_enrichment"}
        return self._issue(PROFILE_TOKEN_TYPE, claims, ttl_seconds)

    def verify(self, token, *, expected_type, user_id=None, now=None, consume=False):
        if expected_type not in _TOKEN_TYPES:
            _fail("invalid_claim", "Unknown expected token type")
        if not isinstance(token, str) or len(token.encode("utf-8")) > MAX_TOKEN_BYTES or token.count(".") != 1:
            _fail("invalid_token", "Authority token is invalid")
        encoded_body, encoded_signature = token.split(".")
        body = _unb64(encoded_body, "token body")
        signature = _unb64(encoded_signature, "token signature")
        try:
            envelope = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _fail("invalid_token", "Authority token is invalid")
        if not isinstance(envelope, dict) or set(envelope) != {"v", "kid", "typ", "iat", "exp", "jti", "claims"}:
            _fail("invalid_token", "Authority token claims are invalid")
        kid = envelope.get("kid")
        key = self._keys.get(kid)
        if key is None or not hmac.compare_digest(signature, hmac.new(key, body, hashlib.sha256).digest()):
            _fail("invalid_signature", "Authority token signature is invalid")
        if envelope.get("v") != TOKEN_VERSION or envelope.get("typ") != expected_type:
            _fail("invalid_token", "Authority token version or type is invalid")
        issued = _timestamp(envelope.get("iat"), "iat")
        expires = _timestamp(envelope.get("exp"), "exp")
        jti = _bounded_text(envelope.get("jti"), field="jti", maximum=128)
        maximum = MAX_VALIDITY_SECONDS if expected_type == SCAN_TOKEN_TYPE else MAX_PROFILE_VALIDITY_SECONDS
        if expires <= issued or expires - issued > maximum:
            _fail("invalid_token", "Authority token lifetime is invalid")
        current = self._now() if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
            _fail("invalid_clock", "The authority clock is invalid")
        if current < issued - CLOCK_SKEW_SECONDS:
            _fail("not_yet_valid", "Authority token is not yet valid")
        if current >= expires:
            _fail("expired", "Authority token has expired")
        claims = envelope.get("claims")
        if not isinstance(claims, dict) or claims.get("purpose") != "nutrition_enrichment":
            _fail("invalid_token", "Authority token purpose is invalid")
        if user_id is not None and claims.get("user_id") != user_id:
            _fail("wrong_user", "Authority token is bound to another user")
        if expected_type == SCAN_TOKEN_TYPE:
            if set(claims) != {"user_id", "scan_id", "scan_revision", "items", "purpose"}:
                _fail("invalid_token", "Scan authority claims are invalid")
            _id(claims["user_id"], "user_id")
            _id(claims["scan_id"], "scan_id")
            if isinstance(claims["scan_revision"], bool) or not isinstance(claims["scan_revision"], int) or claims["scan_revision"] < 0:
                _fail("invalid_token", "Scan authority revision is invalid")
            _validated_scan_items(claims["items"])
        else:
            required = {"user_id", "profile_id", "profile_hash", "source_id", "profile_revision",
                        "food_identity", "reusable", "purpose"}
            if set(claims) != required or not isinstance(claims["reusable"], bool):
                _fail("invalid_token", "Profile authority claims are invalid")
            _id(claims["user_id"], "user_id")
            if not isinstance(claims["profile_revision"], int) or isinstance(claims["profile_revision"], bool) or claims["profile_revision"] < 0:
                _fail("invalid_token", "Profile authority revision is invalid")
            profile_hash = claims["profile_hash"]
            if (not isinstance(profile_hash, str) or len(profile_hash) != 64
                    or any(character not in _ID_HEX for character in profile_hash)):
                _fail("invalid_token", "Profile authority hash is invalid")
            _id(claims["profile_id"], "profile_id")
            _id(claims["source_id"], "source_id")
            identity = claims["food_identity"]
            if not isinstance(identity, dict):
                _fail("invalid_token", "Profile authority identity is invalid")
            _bounded_text(identity.get("name"), field="food_identity.name", maximum=300)
            _validate_identity(identity, complete=True)
        with self._lock:
            if consume and jti in self._consumed:
                _fail("replayed", "Authority token has already been consumed")
            if consume:
                self._consumed.add(jti)
        return deepcopy(claims)

    def verify_with_jti(self, token, *, expected_type, user_id=None, now=None, consume=False):
        """Verify an authority token and return its durable replay identity.

        The public ``verify`` contract intentionally returns only the signed
        claims.  SQL-backed routes also need the envelope JTI so they can
        atomically consume it in their own replay table.  Verification is
        performed first (including the signature and expiry checks), then the
        already-verified envelope is decoded solely to expose that JTI.
        """
        claims = self.verify(token, expected_type=expected_type, user_id=user_id,
                             now=now, consume=consume)
        encoded_body = token.split(".", 1)[0]
        body = _unb64(encoded_body, "token body")
        try:
            envelope = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _fail("invalid_token", "Authority token is invalid")
        jti = _bounded_text(envelope.get("jti"), field="jti", maximum=128)
        return deepcopy(claims), jti

