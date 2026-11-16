"""Authenticated nutrition-enrichment request boundary.

The legacy vision endpoint remains unchanged.  This module accepts only a
server-owned scan snapshot, performs the official local lookup first, and
enters the durable coordinator only for items still missing nutrition data.
The HTTP layer supplies authentication and maps the typed errors to status
codes; no provider credential or client-selected source is accepted here.
When configured, a scanner-issued authority token is verified at this
boundary and its JTI is consumed in the durable scan repository.
"""

from copy import deepcopy
import math
import time

from services.food_identity_service import requires_food_identity_confirmation
from services.nutrition_enrichment_coordinator import (
    NutritionEnrichmentCoordinator,
    NutritionEnrichmentCoordinatorError,
)
from services.nutrition_authority_service import (
    NutritionAuthorityError,
    SCAN_TOKEN_TYPE,
)
from repositories.scan_context_repository import item_set_hash
from services.nutrition_profile_service import (
    NutritionProfileError,
    aggregate_nutrition_coverage,
    calculate_portion,
)
from services.vision_food_service import VISION_FOOD_MIN_CONFIDENCE


MAX_WAIT_SECONDS = 30.0
_IDENTITY_FIELDS = ("food_state", "preparation_method", "components_scope", "brand", "variant")


class NutritionEnrichmentRouteError(ValueError):
    """Typed route-boundary error; the Flask route owns HTTP mapping."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise NutritionEnrichmentRouteError(code, message)


def _text(value, field, maximum=256):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value.strip() != value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail("invalid_request", f"{field} is invalid")
    return value


def _revision(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("invalid_request", f"{field} is invalid")
    return value


def _identity(item):
    return {"name": item["name_zh"], **{field: item.get(field) for field in _IDENTITY_FIELDS}}


def _web_enrichment_eligible(item):
    """Only send a scan item to web search when vision identity is usable.

    A low-confidence or validation-flagged item may still be returned as an
    unresolved scan item, but it must not spend provider quota or be made to
    look more certain by a nutrition lookup.  A later user-confirmation flow
    can create a new server-owned scan revision with corrected identity data.
    """
    confidence = item.get("confidence")
    return (not isinstance(confidence, bool) and isinstance(confidence, (int, float))
            and math.isfinite(confidence) and confidence >= VISION_FOOD_MIN_CONFIDENCE
            and not item.get("validation_issues")
            and not requires_food_identity_confirmation(item.get("name_zh")))


def _recognition_context(item):
    return {field: deepcopy(item.get(field)) for field in
            ("name_zh", "confidence", "weight_confidence", "estimated_weight_g", *_IDENTITY_FIELDS)}


def _item_result(item, *, status, origin, profile, portion=None, diagnostics=None):
    if portion is None:
        portion = calculate_portion(profile, item.get("estimated_weight_g"),
                                    portion_source="vision_estimate")
    result = {
        "item_id": item["item_id"], "item_revision": item["item_revision"],
        "original_visual_name": item["name_zh"], "status": status,
        "origin": origin, "recognition_context": _recognition_context(item),
        "nutrition_profile": deepcopy(profile), "portion": portion,
    }
    if diagnostics is not None:
        result["local_lookup"] = deepcopy(diagnostics)
    return result


def _validate_body(body):
    if not isinstance(body, dict):
        _fail("invalid_request", "Request body must be a JSON object")
    allowed = {"user_id", "scan_id", "scan_revision", "items", "idempotency_key",
               "source_policy_id", "source_policy_revision", "profiles", "wait_timeout",
               "scan_authority_token"}
    if set(body) - allowed:
        _fail("invalid_request", "Request contains unsupported fields")
    required = ("user_id", "scan_id", "scan_revision", "items", "idempotency_key",
                "source_policy_id", "source_policy_revision")
    if any(field not in body for field in required):
        _fail("invalid_request", "Request is missing a required field")
    _text(body["user_id"], "user_id")
    _text(body["scan_id"], "scan_id")
    _revision(body["scan_revision"], "scan_revision")
    _text(body["idempotency_key"], "idempotency_key")
    _text(body["source_policy_id"], "source_policy_id")
    _revision(body["source_policy_revision"], "source_policy_revision")
    if not isinstance(body["items"], list) or not body["items"]:
        _fail("invalid_request", "items must be a non-empty array")
    profiles = body.get("profiles", [])
    if not isinstance(profiles, list):
        _fail("invalid_request", "profiles must be an array")
    wait_timeout = body.get("wait_timeout", None)
    if wait_timeout is not None:
        if (isinstance(wait_timeout, bool) or not isinstance(wait_timeout, (int, float))
                or not math.isfinite(wait_timeout) or wait_timeout < 0 or wait_timeout > MAX_WAIT_SECONDS):
            _fail("invalid_request", "wait_timeout is invalid")
    return body


def _coverage(items):
    try:
        return aggregate_nutrition_coverage([
            {"item_id": item["item_id"], "profile": item.get("nutrition_profile"),
             "weight_g": item.get("recognition_context", {}).get("estimated_weight_g"),
             "portion_source": "vision_estimate"}
            for item in items
        ])
    except NutritionProfileError as error:
        _fail(getattr(error, "code", "invalid_output"), str(error))


def _combine(items, known, enriched):
    by_id = {item["item_id"]: deepcopy(item) for item in known}
    for item in enriched:
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str):
            _fail("invalid_output", "The enrichment provider returned an invalid item")
        item_id = item["item_id"]
        if item_id not in {candidate["item_id"] for candidate in items}:
            _fail("invalid_output", "The enrichment provider returned an unknown item")
        # A provider item is untrusted until it has the same shape produced
        # by the route's canonical item builder.  In particular, an
        # ``item_id``-only payload must not be allowed to masquerade as a
        # complete nutrition result with an all-unknown coverage envelope.
        if item_id not in by_id:
            required = {
                "item_id", "item_revision", "status", "origin",
                "recognition_context", "nutrition_profile", "portion",
            }
            if (not required.issubset(item)
                    or isinstance(item.get("item_revision"), bool)
                    or not isinstance(item.get("item_revision"), int)
                    or not isinstance(item.get("status"), str)
                    or not isinstance(item.get("origin"), (str, type(None)))
                    or not isinstance(item.get("recognition_context"), dict)
                    or not isinstance(item.get("portion"), dict)):
                _fail("invalid_output", "The enrichment provider returned an incomplete item")
            if item.get("status") in {"accepted", "complete"} and not isinstance(item.get("nutrition_profile"), dict):
                _fail("invalid_output", "A complete enrichment item requires a nutrition profile")
        # TFDA/USDA/cache results are authoritative for this request. A web
        # provider must never replace a known local profile with a less trusted
        # result for the same scan item.
        if item_id not in by_id:
            by_id[item_id] = deepcopy(item)
    expected_ids = {item["item_id"] for item in items}
    if set(by_id) != expected_ids:
        _fail("invalid_output", "The enrichment provider omitted a scan item")
    ordered = [by_id[item["item_id"]] for item in items]
    return {"schema_version": "NutritionEnrichmentRouteV1", "items": ordered,
            "nutrition_coverage": _coverage(ordered)}


def _normalize_provider_result(result, *, items, known):
    """Normalize provider output before it reaches the durable coordinator.

    The web service owns only cache/local misses, so its coverage describes a
    partial set. Rebuild the route result from the complete scan item set on
    every request and replay. Retryable statuses remain untouched because
    they intentionally have no nutrition result to normalize.
    """
    if not isinstance(result, dict):
        return {"status": "invalid_output", "result": None}
    explicit = result.get("status")
    if explicit in {"timeout", "rate_limited", "upstream_error", "busy",
                    "source_conflict", "not_found", "invalid_output"}:
        return deepcopy(result)
    raw = result.get("result", result) if isinstance(explicit, str) else result
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return {"status": "invalid_output", "result": deepcopy(raw) if isinstance(raw, dict) else None}
    try:
        normalized = _combine(items, known, raw["items"])
    except NutritionEnrichmentRouteError:
        return {"status": "invalid_output", "result": deepcopy(raw)}
    # Preserve diagnostics for operators, but never preserve the provider's
    # stale coverage field.
    for key in ("events", "production_enabled"):
        if key in raw:
            normalized[key] = deepcopy(raw[key])
    return {"status": explicit, "result": normalized} if isinstance(explicit, str) else normalized


def _cache_successful_web_profiles(*, cache_repository, result, items, user_id,
                                   source_policy_revision):
    """Best-effort persistence for complete, provider-backed profiles.

    The cache repository is the policy/provenance authority.  This boundary
    only selects entries that are explicitly successful web results; it never
    writes misses, retryable failures, partial profiles, or client-shaped
    data.  A cache write must not turn an otherwise durable enrichment result
    into an HTTP failure, so repository errors are intentionally isolated per
    item.
    """
    if cache_repository is None or not isinstance(result, dict):
        return
    provider_items = result.get("items")
    if not isinstance(provider_items, list):
        return
    by_id = {item.get("item_id"): item for item in provider_items
             if isinstance(item, dict) and isinstance(item.get("item_id"), str)}
    for item in items:
        entry = by_id.get(item.get("item_id"))
        if not isinstance(entry, dict) or entry.get("origin") != "web":
            continue
        if entry.get("status") not in {"accepted", "complete"}:
            continue
        profile = entry.get("nutrition_profile")
        if (not isinstance(profile, dict)
                or profile.get("nutrition_status") != "complete"
                or profile.get("has_required_point_values") is not True):
            continue
        details = profile.get("source_details")
        source_id = details.get("source_id") if isinstance(details, dict) else None
        if not isinstance(source_id, str) or not source_id:
            continue
        try:
            cache_repository.put_success(
                food_identity=_identity(item), profile=deepcopy(profile),
                source_id=source_id, source_policy_revision=source_policy_revision,
                user_id=user_id,
            )
        except Exception:
            # Cache is an optimisation.  The profile has already been
            # durably recorded by the request repository and remains usable
            # for this response even when rights/provenance/DB writes reject.
            continue


def _resolve_source_policy(profile_repository, reference, revision):
    """Resolve the legacy source-id alias or the reviewed policy id."""
    resolver = getattr(profile_repository, "resolve_source_policy_reference", None)
    try:
        if callable(resolver):
            return resolver(reference, revision=revision)
        return profile_repository.get_source_policy(reference, revision=revision)
    except Exception as error:
        raise NutritionEnrichmentRouteError(
            getattr(error, "code", "source_unavailable"), str(error)) from error


def _validate_provider_authorities(*, user_id, body, profile_repository):
    """Fail before constructing a paid provider when source/profile is stale."""
    if profile_repository is None:
        return
    source = _resolve_source_policy(
        profile_repository, body["source_policy_id"], body["source_policy_revision"])
    if source is None or source.get("status") != "active":
        _fail("source_unavailable", "Source policy is missing or withdrawn")
    for reference in body.get("profiles", []):
        if not isinstance(reference, dict) or set(reference) != {
                "profile_id", "profile_hash", "source_id", "profile_revision"}:
            _fail("invalid_request", "Profile reference fields are invalid")
        profile_id = _text(reference.get("profile_id"), "profile_id")
        profile_hash = _text(reference.get("profile_hash"), "profile_hash", 64).lower()
        if len(profile_hash) != 64 or any(char not in "0123456789abcdef" for char in profile_hash):
            _fail("invalid_request", "profile_hash is invalid")
        profile_revision = _revision(reference.get("profile_revision"), "profile_revision")
        source_id = _text(reference.get("source_id"), "source_id")
        try:
            document = profile_repository.get_profile_for_user(
                user_id, profile_id, revision=profile_revision)
        except Exception as error:
            raise NutritionEnrichmentRouteError(getattr(error, "code", "profile_unavailable"), str(error)) from error
        if (document is None or document.get("profile_hash") != profile_hash
                or document.get("source_id") != source_id
                or document.get("source_id") != source.get("source_id")):
            _fail("profile_conflict", "Profile reference is stale")
    return source


def _consume_scan_authority(*, authority_service, token, user_id, body, context,
                            scan_context_repository, consume=True):
    """Verify a scanner-issued token and durably consume its JTI.

    The signed token is only an assertion.  The SQL repository remains the
    source of truth for the complete item set and owns the atomic replay
    record, so a client cannot manufacture a valid-looking item list or reuse
    a token across scans/users.
    """
    if authority_service is None:
        return
    if not isinstance(token, str) or not token:
        _fail("invalid_request", "scan_authority_token is required")
    try:
        claims, jti = authority_service.verify_with_jti(
            token, expected_type=SCAN_TOKEN_TYPE, user_id=user_id)
    except NutritionAuthorityError as error:
        # Keep the public boundary stable without exposing token parsing or
        # signing details.  A user binding failure remains an authorization
        # error; expiry/replay retain their conflict semantics.
        code = getattr(error, "code", "invalid_token")
        if code not in {"wrong_user", "expired", "replayed", "not_yet_valid"}:
            code = "authority_invalid"
        _fail(code, str(error))
    if (claims.get("scan_id") != body["scan_id"]
            or claims.get("scan_revision") != body["scan_revision"]):
        _fail("authority_conflict", "Scan authority does not match the request")
    try:
        claim_hash = item_set_hash(claims.get("items"))
    except Exception as error:
        _fail("authority_invalid", "Scan authority item set is invalid")
    if claim_hash != context.get("item_set_hash"):
        _fail("authority_conflict", "Scan authority does not match the complete scan")
    if not consume:
        return jti
    try:
        scan_context_repository.consume_scan_context(
            user_id=user_id, scan_id=body["scan_id"],
            scan_revision=body["scan_revision"], items=context["items"], jti=jti)
    except Exception as error:
        code = getattr(error, "code", "scan_unavailable")
        raise NutritionEnrichmentRouteError(code, str(error)) from error


def process_enrichment_request(body, *, authenticated_user_id, scan_context_repository,
                               profile_repository, request_repository, quota_repository,
                               cache_repository, local_lookup, provider_factory=None,
                               feature_enabled=False, clock=time.monotonic,
                               authority_service=None):
    """Process one authenticated request using server-owned dependencies.

    ``provider_factory`` is called only when at least one item misses both
    official data and a positive cache entry.  It receives the server-owned
    items and must return a callable accepted by ``NutritionEnrichmentCoordinator``.
    """
    body = _validate_body(body)
    user_id = _text(authenticated_user_id, "authenticated_user_id")
    if body["user_id"] != user_id:
        _fail("wrong_user", "Request belongs to another user")

    items = deepcopy(body["items"])
    context_was_consumed = False
    try:
        context = scan_context_repository.assert_complete_item_set(
            user_id=user_id, scan_id=body["scan_id"], scan_revision=body["scan_revision"], items=items,
            include_inactive=authority_service is not None)
        if context.get("status") == "consumed":
            context_was_consumed = True
            existing = None
            lookup = getattr(request_repository, "get_by_idempotency_key", None)
            if callable(lookup):
                try:
                    existing = lookup(user_id=user_id, idempotency_key=body["idempotency_key"])
                except Exception as error:
                    _fail(getattr(error, "code", "request_unavailable"), str(error))
            if existing is None:
                _fail("scan_unavailable", "Scan context has already been consumed")
        elif context.get("status") != "active":
            _fail("scan_unavailable", "Scan context is not active")
    except Exception as error:
        code = getattr(error, "code", "scan_unavailable")
        raise NutritionEnrichmentRouteError(code, str(error)) from error
    # Use the durable item document after comparison.  This prevents callers
    # from changing non-authoritative recognition fields between requests.
    items = deepcopy(context["items"])

    known, missing, ineligible = [], [], []
    resolved_source = None
    for item in items:
        try:
            local = local_lookup(deepcopy(item))
        except Exception as error:
            _fail(getattr(error, "code", "local_error"), str(error))
        if not isinstance(local, dict):
            _fail("invalid_local_result", "The local lookup returned an invalid result")
        if local.get("status") == "matched" and isinstance(local.get("nutrition_profile"), dict):
            try:
                known.append(_item_result(item, status="accepted", origin="local",
                                          profile=local["nutrition_profile"],
                                          diagnostics=local.get("diagnostics")))
            except NutritionProfileError as error:
                _fail(getattr(error, "code", "local_error"), str(error))
            continue
        if not _web_enrichment_eligible(item):
            # Do not read a web-derived cache entry for an uncertain visual
            # identity. Official local hits above remain allowed; a later
            # confirmation must create a new scan revision.
            ineligible.append(item)
            continue
        cached = None
        if cache_repository is not None:
            if resolved_source is None and profile_repository is not None:
                try:
                    resolved_source = _resolve_source_policy(
                        profile_repository, body["source_policy_id"],
                        body["source_policy_revision"])
                except NutritionEnrichmentRouteError:
                    # The authoritative check below returns the stable public
                    # error.  Treat an unresolved policy as a cache miss here.
                    resolved_source = None
            cache_source_id = (resolved_source or {}).get(
                "source_id", body["source_policy_id"])
            try:
                cached = cache_repository.get(
                    food_identity=_identity(item), source_id=cache_source_id,
                    source_policy_revision=body["source_policy_revision"], user_id=user_id)
            except Exception as error:
                # Cache is an optimisation. A stale/withdrawn policy is a miss;
                # malformed storage still fails closed rather than inventing data.
                if getattr(error, "code", "") not in {"source_unavailable", "source_conflict", "rights_not_allowed",
                                                        "reuse_not_allowed", "owner_required"}:
                    _fail(getattr(error, "code", "cache_error"), str(error))
        if cached and isinstance(cached.get("profile"), dict):
            try:
                known.append(_item_result(item, status="accepted", origin="cache",
                                          profile=cached["profile"]))
            except NutritionProfileError as error:
                _fail(getattr(error, "code", "cache_error"), str(error))
        else:
            missing.append(item)

    if ineligible:
        _fail("confirmation_required",
              "Uncertain, generic or validation-flagged scan items require identity confirmation before web enrichment")
    if not missing:
        return {"request_id": None, "status": "complete", "result": _combine(items, known, []),
                "error": None, "replayed": False, "local_only": True}
    resolved_source = _validate_provider_authorities(
        user_id=user_id, body=body, profile_repository=profile_repository)
    if not feature_enabled or not callable(provider_factory):
        _fail("feature_disabled", "Automatic web enrichment is not enabled")

    if authority_service is not None and not context_was_consumed:
        # Validate the signed assertion before constructing a provider.  This
        # keeps malformed, cross-scan, or missing tokens from reaching a paid
        # provider factory, while the durable JTI consume still happens only
        # after that factory has produced a callable.
        _consume_scan_authority(
            authority_service=authority_service,
            token=body.get("scan_authority_token"),
            user_id=user_id,
            body=body,
            context=context,
            scan_context_repository=scan_context_repository,
            consume=False,
        )

    try:
        provider = provider_factory(missing, known)
    except Exception as error:
        _fail(getattr(error, "code", "provider_unavailable"), str(error))
    if not callable(provider):
        _fail("provider_unavailable", "The enrichment provider is unavailable")

    # Normalize the provider boundary before the coordinator persists the
    # result. This also guarantees replay responses use the same complete
    # coverage as the first response.
    raw_provider = provider

    def provider_with_route_contract(payload):
        return _normalize_provider_result(
            raw_provider(payload), items=items, known=known)

    # Build and validate the provider before consuming the one-time authority.
    # A missing credential or malformed provider configuration must not burn a
    # scan that never reached an upstream call.
    if not context_was_consumed:
        _consume_scan_authority(
            authority_service=authority_service,
            token=body.get("scan_authority_token"),
            user_id=user_id,
            body=body,
            context=context,
            scan_context_repository=scan_context_repository,
            consume=True,
        )

    coordinator = NutritionEnrichmentCoordinator(
        scan_context_repository=scan_context_repository,
        profile_repository=profile_repository,
        request_repository=request_repository,
        quota_repository=quota_repository,
        provider=provider_with_route_contract,
        clock=clock,
        wait_timeout=body.get("wait_timeout", 0.0) or 0.0,
        authority_consumed=authority_service is not None,
    )
    try:
        outcome = coordinator.run(
            user_id=user_id, scan_id=body["scan_id"], scan_revision=body["scan_revision"],
            items=items, idempotency_key=body["idempotency_key"],
            source_policy_id=body["source_policy_id"],
            source_policy_revision=body["source_policy_revision"],
            profiles=body.get("profiles", []), wait_timeout=body.get("wait_timeout"),
        )
    except NutritionEnrichmentCoordinatorError as error:
        raise NutritionEnrichmentRouteError(error.code, str(error)) from error
    if outcome.get("status") in {"accepted", "complete", "partial", "success"}:
        _cache_successful_web_profiles(
            cache_repository=cache_repository, result=outcome.get("result"),
            items=items, user_id=user_id,
            source_policy_revision=body["source_policy_revision"],
        )
    return outcome


__all__ = ["NutritionEnrichmentRouteError", "process_enrichment_request"]
